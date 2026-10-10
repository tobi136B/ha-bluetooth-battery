#!/usr/bin/env python3
"""
find_bluetooth_devices: Listet unter Windows alle gekoppelten Bluetooth Geräte
mit MAC Adresse und (falls Windows ihn kennt) Akkustand auf.

Die Ausgabe enthält einen fertigen Block für die Optionen des Home Assistant
Add-ons "Bluetooth Battery".

Nur Standardbibliothek, getestet für Python 3.12 bis 3.15. Liest die Daten über
PowerShell (Get-PnpDevice), es sind keine Administratorrechte nötig.

Aufruf:
    python find_bluetooth_devices.py            Tabelle und Add-on Block
    python find_bluetooth_devices.py --json     Ausgabe als JSON
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass

# Windows Geräteeigenschaft für den Bluetooth Akkustand (DEVPKEY_Bluetooth_Battery)
BATTERY_KEY = "{104EA319-6EE2-4701-BD47-8DDBF425BBE5} 2"

POWERSHELL_SCRIPT = rf"""
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$devices = @(Get-PnpDevice -ErrorAction SilentlyContinue |
    Where-Object {{ $_.InstanceId -match '^(BTHENUM|BTHLE|BTHLEDEVICE)\\' }})
$battery = @{{}}
if ($devices.Count -gt 0) {{
    Get-PnpDeviceProperty -InstanceId $devices.InstanceId -KeyName '{BATTERY_KEY}' -ErrorAction SilentlyContinue |
        Where-Object {{ $null -ne $_.Data }} |
        ForEach-Object {{ $battery[$_.InstanceId] = [int]$_.Data }}
}}
$devices | ForEach-Object {{
    [pscustomobject]@{{
        InstanceId   = $_.InstanceId
        FriendlyName = $_.FriendlyName
        Status       = [string]$_.Status
        Battery      = $battery[$_.InstanceId]
    }}
}} | ConvertTo-Json -Depth 3 -Compress
"""

# MAC Adresse aus der Windows Instanz ID, z.B.
#   BTHENUM\DEV_AABBCCDDEEFF\...                          (Classic, Hauptgerät)
#   BTHENUM\{0000111E-...}_LOCALMFG&0002\7&...&0&AABBCCDDEEFF_C00000000   (Classic, Dienst)
#   BTHLE\DEV_AABBCCDDEEFF\...                            (BLE, Hauptgerät)
#   BTHLEDEVICE\{0000180F-...}_DEV_VID&...._AABBCCDDEEFF\...                (BLE, Dienst)
MAC_PATTERNS = (
    re.compile(r"\\DEV_([0-9A-F]{12})(?:\\|$)", re.IGNORECASE),
    re.compile(r"&([0-9A-F]{12})_C[0-9A-F]{8}$", re.IGNORECASE),
    re.compile(r"_([0-9A-F]{12})\\", re.IGNORECASE),
)


@dataclass
class BluetoothDevice:
    mac: str
    name: str
    kind: str
    connected: bool
    battery: int | None


def extract_mac(instance_id: str) -> str | None:
    for pattern in MAC_PATTERNS:
        match = pattern.search(instance_id)
        if match:
            raw = match.group(1).upper()
            return ":".join(raw[index:index + 2] for index in range(0, 12, 2))
    return None


def is_main_device(instance_id: str) -> bool:
    """Das Hauptgerät trägt den Namen, die Dienst Einträge heißen z.B. "Freisprechfunktion"."""
    return re.match(r"^(BTHENUM|BTHLE)\\DEV_", instance_id, re.IGNORECASE) is not None


def group_devices(entries: list[dict]) -> list[BluetoothDevice]:
    """Fasst die PnP Einträge pro MAC Adresse zu einem Gerät zusammen."""
    devices: dict[str, BluetoothDevice] = {}
    for entry in entries:
        instance_id = entry.get("InstanceId") or ""
        mac = extract_mac(instance_id)
        if mac is None:
            continue
        device = devices.setdefault(
            mac,
            BluetoothDevice(mac=mac, name="", kind="BLE" if instance_id.upper().startswith("BTHLE") else "Classic",
                            connected=False, battery=None),
        )
        if is_main_device(instance_id) and entry.get("FriendlyName"):
            device.name = entry["FriendlyName"]
        elif not device.name and entry.get("FriendlyName"):
            device.name = entry["FriendlyName"]
        # "OK" heißt bei Bluetooth Geräten: aktuell verbunden bzw. aktiv
        if entry.get("Status") == "OK" and not is_main_device(instance_id):
            device.connected = True
        battery = entry.get("Battery")
        if isinstance(battery, int) and 0 <= battery <= 100:
            device.battery = battery if device.battery is None else max(device.battery, battery)
    return sorted(devices.values(), key=lambda device: device.name.lower())


def read_pnp_entries() -> list[dict]:
    if sys.platform != "win32":
        raise SystemExit("Dieses Skript läuft nur unter Windows.")
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", POWERSHELL_SCRIPT],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit("PowerShell Fehler:\n" + result.stderr.decode("utf-8", errors="replace"))
    output = result.stdout.decode("utf-8-sig", errors="replace").strip()
    if not output:
        return []
    data = json.loads(output)
    # ConvertTo-Json liefert bei genau einem Eintrag ein Objekt statt einer Liste
    return data if isinstance(data, list) else [data]


def format_table(devices: list[BluetoothDevice]) -> str:
    lines = [f"{'Name':32} {'MAC':17}  {'Typ':7}  {'Verbunden':9}  Akku", "-" * 78]
    for device in devices:
        battery = f"{device.battery} %" if device.battery is not None else "-"
        connected = "ja" if device.connected else "nein"
        lines.append(f"{device.name[:32]:32} {device.mac:17}  {device.kind:7}  {connected:9}  {battery}")
    return "\n".join(lines)


def format_addon_options(devices: list[BluetoothDevice]) -> str:
    lines = ["devices:"]
    for device in devices:
        name = (device.name or device.mac).replace('"', "'")
        lines.append(f'  - mac: "{device.mac}"')
        lines.append(f'    name: "{name}"')
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Gekoppelte Bluetooth Geräte mit MAC Adresse und Akkustand anzeigen")
    parser.add_argument("--json", action="store_true", help="Ausgabe als JSON")
    args = parser.parse_args()

    devices = group_devices(read_pnp_entries())
    if args.json:
        print(json.dumps([asdict(device) for device in devices], indent=2, ensure_ascii=False))
        return 0
    if not devices:
        print("Keine gekoppelten Bluetooth Geräte gefunden.")
        return 0
    print(format_table(devices))
    print()
    print("Block für die Add-on Optionen (nicht benötigte Geräte löschen):")
    print()
    print(format_addon_options(devices))
    return 0


if __name__ == "__main__":
    sys.exit(main())
