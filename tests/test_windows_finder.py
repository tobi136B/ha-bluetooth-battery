"""Tests für das Windows Skript, mit nachgebildeter PowerShell Ausgabe."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from find_bluetooth_devices import extract_mac, format_addon_options, group_devices  # noqa: E402

SAMPLE = [
    {"InstanceId": "BTHENUM\\DEV_AC800A123456\\7&1A2B3C4D&0&BLUETOOTHDEVICE_AC800A123456",
     "FriendlyName": "Bose QC SC", "Status": "OK", "Battery": None},
    {"InstanceId": "BTHENUM\\{0000111E-0000-1000-8000-00805F9B34FB}_VID&0002009E_PID&4020\\7&2B3C&0&AC800A123456_C00000000",
     "FriendlyName": "Bose QC SC Hands-Free", "Status": "OK", "Battery": 80},
    {"InstanceId": "BTHLE\\DEV_F1E2D3C4B5A6\\8&ABC&0&F1E2D3C4B5A6",
     "FriendlyName": "MX Master 3S", "Status": "OK", "Battery": None},
    {"InstanceId": "BTHLEDEVICE\\{0000180F-0000-1000-8000-00805F9B34FB}_DEV_VID&02046D_PID&B034_REV&0001_F1E2D3C4B5A6\\9&XYZ&0&0013",
     "FriendlyName": "Akku Dienst", "Status": "Unknown", "Battery": 55},
    {"InstanceId": "BTHENUM\\{00001101-0000-1000-8000-00805F9B34FB}_LOCALMFG&0000\\7&AAA&0&000000000000_00000000",
     "FriendlyName": "Standard Seriell", "Status": "OK", "Battery": None},
]


def test_extract_mac_variants() -> None:
    assert extract_mac(SAMPLE[0]["InstanceId"]) == "AC:80:0A:12:34:56"
    assert extract_mac(SAMPLE[1]["InstanceId"]) == "AC:80:0A:12:34:56"
    assert extract_mac(SAMPLE[2]["InstanceId"]) == "F1:E2:D3:C4:B5:A6"
    assert extract_mac(SAMPLE[3]["InstanceId"]) == "F1:E2:D3:C4:B5:A6"


def test_group_devices() -> None:
    devices = {device.mac: device for device in group_devices(SAMPLE)}
    bose = devices["AC:80:0A:12:34:56"]
    assert bose.name == "Bose QC SC" and bose.battery == 80 and bose.connected and bose.kind == "Classic"
    mouse = devices["F1:E2:D3:C4:B5:A6"]
    assert mouse.name == "MX Master 3S" and mouse.battery == 55 and mouse.kind == "BLE"
    assert "00:00:00:00:00:00" not in devices


def test_addon_block() -> None:
    block = format_addon_options(group_devices(SAMPLE[:2]))
    assert block == 'devices:\n  - mac: "AC:80:0A:12:34:56"\n    name: "Bose QC SC"'
