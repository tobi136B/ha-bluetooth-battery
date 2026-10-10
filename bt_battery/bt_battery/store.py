"""
Dauerhafte Geräteliste unter /data, damit gefundene Geräte und die Auswahl
"überwachen" einen Neustart des Add-ons überstehen.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

LOG = logging.getLogger(__name__)

DEFAULT_STORE_PATH = Path("/data/devices.json")


class DeviceStore:
    """Bekannte Geräte, nach MAC Adresse. Ohne Pfad nur im Speicher (für Tests)."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path
        self._devices: dict[str, dict] = {}
        if path is not None and path.exists():
            try:
                self._devices = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as error:
                LOG.warning("Geräteliste %s nicht lesbar, beginne leer: %s", path, error)

    def __contains__(self, mac: str) -> bool:
        return mac.upper() in self._devices

    def get(self, mac: str) -> dict | None:
        return self._devices.get(mac.upper())

    def items(self) -> list[tuple[str, dict]]:
        return list(self._devices.items())

    def monitored(self) -> list[tuple[str, dict]]:
        return [(mac, entry) for mac, entry in self._devices.items() if entry.get("monitored")]

    def mac_for_object_id(self, object_id: str) -> str | None:
        for mac in self._devices:
            if "bt_battery_" + mac.replace(":", "").lower() == object_id:
                return mac
        return None

    def remember(self, found: dict) -> bool:
        """Übernimmt ein gefundenes Gerät; gibt True zurück, wenn es neu ist."""
        mac = found["mac"].upper()
        entry = self._devices.get(mac)
        is_new = entry is None
        if is_new:
            entry = self._devices[mac] = {"name": "", "monitored": False}
        # Ein leerer Name überschreibt keinen bekannten
        if found.get("name"):
            entry["name"] = found["name"]
        entry["type"] = found.get("type", "")
        entry["battery_method"] = found.get("battery_method", "unknown")
        entry["last_seen"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return is_new

    def add(self, mac: str, name: str, monitored: bool) -> None:
        entry = self._devices.setdefault(mac.upper(), {"name": "", "monitored": False})
        entry["name"] = name or entry["name"] or mac.upper()
        entry["monitored"] = monitored

    def set_monitored(self, mac: str, monitored: bool) -> None:
        self._devices[mac.upper()]["monitored"] = monitored

    def save(self) -> None:
        if self._path is None:
            return
        temporary = self._path.with_suffix(".tmp")
        try:
            temporary.write_text(json.dumps(self._devices, indent=2, ensure_ascii=False), encoding="utf-8")
            temporary.replace(self._path)
        except OSError as error:
            LOG.warning("Geräteliste %s nicht speicherbar: %s", self._path, error)
