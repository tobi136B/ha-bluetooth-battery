"""Einlesen der Add-on Optionen und der MQTT Zugangsdaten."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

MAC_PATTERN = re.compile(r"^([0-9A-F]{2}:){5}[0-9A-F]{2}$")


@dataclass(frozen=True)
class DeviceConfig:
    mac: str
    name: str

    @property
    def object_id(self) -> str:
        return "bt_battery_" + self.mac.replace(":", "").lower()


@dataclass(frozen=True)
class MqttConfig:
    host: str
    port: int = 1883
    username: str | None = None
    password: str | None = None


@dataclass(frozen=True)
class AppConfig:
    adapter: str
    poll_interval_seconds: int
    hold_seconds: int
    disconnect_after_read: bool
    log_level: str
    mqtt: MqttConfig
    devices: list[DeviceConfig] = field(default_factory=list)

    def device(self, mac: str) -> DeviceConfig | None:
        return next((device for device in self.devices if device.mac == mac.upper()), None)


def load_config(options_path: Path = Path("/data/options.json")) -> AppConfig:
    """Liest /data/options.json (vom Supervisor) und die MQTT Umgebungsvariablen aus run.sh."""
    options = json.loads(options_path.read_text(encoding="utf-8"))

    devices = []
    for entry in options.get("devices", []):
        mac = entry["mac"].strip().upper()
        if not MAC_PATTERN.match(mac):
            raise ValueError(f"Ungültige MAC Adresse: {entry['mac']}")
        devices.append(DeviceConfig(mac=mac, name=entry.get("name") or mac))

    mqtt = MqttConfig(
        host=os.environ.get("MQTT_HOST", "core-mosquitto"),
        port=int(os.environ.get("MQTT_PORT", "1883")),
        username=os.environ.get("MQTT_USER") or None,
        password=os.environ.get("MQTT_PASSWORD") or None,
    )
    return AppConfig(
        adapter=options.get("adapter", "hci0"),
        poll_interval_seconds=int(options.get("poll_interval_minutes", 15)) * 60,
        hold_seconds=int(options.get("hold_seconds", 20)),
        disconnect_after_read=bool(options.get("disconnect_after_read", True)),
        log_level=str(options.get("log_level", "info")).upper(),
        mqtt=mqtt,
        devices=devices,
    )
