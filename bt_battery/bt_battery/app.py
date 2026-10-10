"""
Ablaufsteuerung: Geräte koppeln, regelmäßig verbinden, Akkustand melden.

Zwei Wege je nach Gerät:
* Geräte mit Freisprechprofil (Kopfhörer, Headsets): eigener HFP Steuerkanal
* alle übrigen (z.B. BLE Mäuse, Tastaturen, Controller): org.bluez.Battery1
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os

from dbus_fast import DBusError

from .bluez import BATTERY_SERVICE_UUID, HFP_HF_UUID, BlueZ, close_fd, path_to_mac
from .config import AppConfig, DeviceConfig
from .hfp import BatteryReport, HfpAgSession
from .mqtt_publisher import BASE_TOPIC, SCAN_COMMAND_TOPIC, MqttPublisher
from .store import DeviceStore

LOG = logging.getLogger(__name__)

CONNECT_TIMEOUT_SECONDS = 30
# Kurze Pause nach der Akkumeldung, damit der Kopfhörer seinen Verbindungsaufbau abschließen kann
DISCONNECT_DELAY_SECONDS = 2
# Gerätetypen (BlueZ "Icon"), die in HA zur Auswahl angeboten werden
OFFERED_TYPE_PREFIXES = ("audio-", "input-")


class HfpConnection:
    """Eine offene RFCOMM Verbindung zu einem Kopfhörer."""

    def __init__(self, device: DeviceConfig, fd: int, service: "BatteryService") -> None:
        self.device = device
        self.fd = fd
        self.battery_received = asyncio.Event()
        self._service = service
        self._loop = asyncio.get_running_loop()
        self._session = HfpAgSession(self._on_battery)
        os.set_blocking(fd, False)
        self._loop.add_reader(fd, self._on_readable)

    def _on_battery(self, report: BatteryReport) -> None:
        LOG.info("%s: %d %% (%s)", self.device.name, report.level, report.source)
        self._service.publisher.publish_battery(self.device, report.level, report.source)
        self.battery_received.set()

    def _on_readable(self) -> None:
        try:
            data = os.read(self.fd, 1024)
        except BlockingIOError:
            return
        except OSError as error:
            LOG.debug("%s: Lesefehler: %s", self.device.name, error)
            data = b""
        if not data:
            self.close()
            return
        response = self._session.feed(data)
        if response:
            try:
                os.write(self.fd, response)
            except OSError as error:
                LOG.debug("%s: Schreibfehler: %s", self.device.name, error)

    def close(self) -> None:
        if self.fd < 0:
            return
        self._loop.remove_reader(self.fd)
        close_fd(self.fd)
        self.fd = -1
        self._service.connection_closed(self)


class BatteryService:
    def __init__(
        self, config: AppConfig, bluez: BlueZ, publisher: MqttPublisher, store: DeviceStore | None = None
    ) -> None:
        self.config = config
        self.bluez = bluez
        self.publisher = publisher
        self.store = store if store is not None else DeviceStore()
        self._connections: dict[str, HfpConnection] = {}
        # Geräte aus den Optionen werden immer überwacht, dazu die in HA eingeschalteten
        for device in config.devices:
            self.store.add(device.mac, device.name, monitored=True)
        self.store.save()
        self._devices: dict[str, DeviceConfig] = {}
        self._sync_monitored()
        self._announced: set[str] = set()
        self._wake = asyncio.Event()
        self._scan_requested = False
        # False, wenn ein anderer Dienst die HFP Gateway Rolle belegt (siehe __main__)
        self.hfp_available = True
        self._tasks: set[asyncio.Task] = set()

    # Rückrufe aus dem BlueZ Profil

    def on_new_connection(self, device_path: str, fd: int) -> None:
        mac = path_to_mac(device_path)
        device = self._devices.get(mac.upper())
        if device is None:
            LOG.info("Verbindung von nicht konfiguriertem Gerät %s abgelehnt", mac)
            close_fd(fd)
            return
        if mac in self._connections:
            self._connections[mac].close()
        LOG.debug("%s: HFP Steuerkanal verbunden", device.name)
        connection = HfpConnection(device, fd, self)
        self._connections[mac] = connection
        self._spawn(self._supervise(connection))

    def on_disconnect_request(self, device_path: str) -> None:
        connection = self._connections.get(path_to_mac(device_path))
        if connection is not None:
            connection.close()

    def connection_closed(self, connection: HfpConnection) -> None:
        if self._connections.get(connection.device.mac) is connection:
            del self._connections[connection.device.mac]
        LOG.debug("%s: HFP Steuerkanal getrennt", connection.device.name)

    # Ablauf

    def _spawn(self, coroutine) -> None:
        task = asyncio.create_task(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _supervise(self, connection: HfpConnection) -> None:
        """Wartet auf die Akkumeldung und trennt danach, um den Verbindungsplatz freizugeben."""
        try:
            await asyncio.wait_for(connection.battery_received.wait(), self.config.hold_seconds)
            await asyncio.sleep(DISCONNECT_DELAY_SECONDS)
        except asyncio.TimeoutError:
            LOG.info("%s: keine Akkumeldung innerhalb von %d s", connection.device.name, self.config.hold_seconds)
        if self.config.disconnect_after_read and connection.fd >= 0:
            await self.bluez.disconnect(connection.device.mac)
            connection.close()

    async def _ensure_paired(self, device: DeviceConfig) -> bool:
        state = await self.bluez.device_state(device.mac)
        if state is not None and state.get("Paired"):
            return True
        LOG.info("%s: nicht gekoppelt, suche Gerät (bitte Kopplungsmodus aktivieren)", device.name)
        if await self.bluez.pair(device.mac):
            LOG.info("%s: erfolgreich gekoppelt", device.name)
            return True
        LOG.warning("%s: nicht gefunden oder Kopplung fehlgeschlagen, neuer Versuch im nächsten Durchlauf", device.name)
        return False

    async def poll_device(self, device: DeviceConfig) -> None:
        if device.mac in self._connections:
            return
        if not await self._ensure_paired(device):
            return
        state = await self.bluez.device_state(device.mac) or {}
        if HFP_HF_UUID in state.get("UUIDs", []):
            if self.hfp_available:
                await self._poll_hfp(device)
            else:
                # Der fremde HFP Dienst baut die Verbindung auf und meldet den Akku ggf. an BlueZ
                await self._poll_bluez_battery(device, state, self.bluez.connect_hfp)
        else:
            await self._poll_bluez_battery(device, state, self.bluez.connect_device)

    async def _poll_hfp(self, device: DeviceConfig) -> None:
        """Kopfhörer und Headsets: Akkustand über den HFP Steuerkanal."""
        try:
            await asyncio.wait_for(self.bluez.connect_hfp(device.mac), CONNECT_TIMEOUT_SECONDS)
        except (DBusError, asyncio.TimeoutError) as error:
            LOG.debug("%s: nicht erreichbar (%s)", device.name, error)
            return
        # Auf das Ende der Sitzung warten, damit Geräte nacheinander abgefragt werden
        connection = self._connections.get(device.mac)
        if connection is not None:
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(connection.battery_received.wait(), self.config.hold_seconds)

    async def _poll_bluez_battery(self, device: DeviceConfig, state: dict, connect) -> None:
        """Übrige Geräte (v.a. BLE): Akkustand, den BlueZ selbst über org.bluez.Battery1 bereitstellt."""
        connected_by_us = False
        if not state.get("Connected"):
            try:
                await asyncio.wait_for(connect(device.mac), CONNECT_TIMEOUT_SECONDS)
                connected_by_us = True
            except (DBusError, asyncio.TimeoutError) as error:
                LOG.debug("%s: nicht erreichbar (%s)", device.name, error)
                return
        try:
            # BlueZ liest den BLE Akku Dienst kurz nach dem Verbinden
            for _ in range(self.config.hold_seconds):
                level = state.get("BatteryPercentage")
                if level is not None:
                    LOG.info("%s: %d %% (bluez)", device.name, level)
                    self.publisher.publish_battery(device, int(level), "bluez")
                    return
                await asyncio.sleep(1)
                state = await self.bluez.device_state(device.mac) or {}
            LOG.info("%s: kein Akkustand verfügbar (Gerät oder Host meldet keinen Akku an BlueZ)", device.name)
        finally:
            # Nur trennen, was wir selbst verbunden haben (z.B. keine Maus, die gerade benutzt wird)
            if connected_by_us and self.config.disconnect_after_read:
                await self.bluez.disconnect(device.mac)

    # Gerätesuche

    @staticmethod
    def describe(state: dict) -> dict:
        """Kurzbeschreibung eines Geräts für Protokoll und Sensor "Found devices"."""
        uuids = state.get("UUIDs", [])
        if HFP_HF_UUID in uuids:
            method = "hfp"
        elif BATTERY_SERVICE_UUID in uuids or state.get("BatteryPercentage") is not None:
            method = "ble_battery"
        else:
            method = "unknown"
        return {
            "mac": state.get("Address", ""),
            # "Name" fehlt, wenn das Gerät keinen Namen sendet; "Alias" ist dann nur die Adresse
            "name": state.get("Name") or (state.get("Alias") if state.get("Paired") else "") or "",
            "type": state.get("Icon", ""),
            "paired": bool(state.get("Paired")),
            "rssi": state.get("RSSI"),
            "battery_method": method,
            "random_address": state.get("AddressType") == "random",
        }

    @staticmethod
    def is_offered(entry: dict) -> bool:
        """Geräte, für die in HA ein Schalter "Monitor battery" angelegt wird."""
        return (
            entry["paired"]
            or entry["battery_method"] != "unknown"
            or entry["type"].startswith(OFFERED_TYPE_PREFIXES)
        )

    async def scan_and_report(self) -> None:
        LOG.info("Suche %d s nach Bluetooth Geräten (Geräte einschalten, ggf. Kopplungsmodus)", self.config.scan_seconds)
        found = [self.describe(state) for state in await self.bluez.scan(self.config.scan_seconds)]
        # Gekoppelte und gerade gesehene Geräte zeigen, nach Signalstärke sortiert
        found = [entry for entry in found if entry["paired"] or entry["rssi"] is not None]
        # Namenlose Geräte mit Zufallsadresse sind fast immer fremde Handys, Uhren oder Tracker.
        # Geräte mit fester Adresse (z.B. Kopfhörer) bleiben auch ohne Namen sichtbar.
        def is_noise(entry: dict) -> bool:
            return not entry["name"] and not entry["paired"] and entry["random_address"]

        unnamed = [entry for entry in found if is_noise(entry)]
        found = [entry for entry in found if not is_noise(entry)]
        found.sort(key=lambda entry: entry["rssi"] if entry["rssi"] is not None else -999, reverse=True)
        for entry in unnamed:
            LOG.debug("  ohne Namen: %s", entry["mac"])
        LOG.info("%d Geräte gefunden, %d namenlose Geräte mit Zufallsadresse ausgeblendet:", len(found), len(unnamed))
        for entry in found:
            LOG.info(
                "  %s  %-30s %-16s gekoppelt=%s akku=%s",
                entry["mac"], entry["name"][:30], entry["type"], "ja" if entry["paired"] else "nein", entry["battery_method"],
            )
        if not found:
            LOG.info("Keine benannten Geräte gefunden. Kopfhörer erscheinen nur im Kopplungsmodus.")
        new_devices = [entry for entry in found if self.is_offered(entry) and self.store.remember(entry)]
        self.store.save()
        for entry in new_devices:
            LOG.info("Neu in Home Assistant: %s (%s)", entry["name"] or entry["mac"], entry["mac"])
        LOG.info("Zum Überwachen in Home Assistant beim Gerät den Schalter 'Monitor battery' einschalten")
        self.publisher.publish_scan_result(found)

    # Auswahl in Home Assistant

    def _device_config(self, mac: str) -> DeviceConfig:
        entry = self.store.get(mac) or {}
        return DeviceConfig(mac=mac, name=entry.get("name") or mac)

    def _sync_monitored(self) -> None:
        """Gleicht die abgefragten Geräte mit der gespeicherten Auswahl ab."""
        wanted = {mac for mac, _ in self.store.monitored()}
        for mac in list(self._devices):
            if mac not in wanted:
                del self._devices[mac]
        for mac in wanted:
            if mac not in self._devices:
                self._devices[mac] = self._device_config(mac)

    def handle_command(self, topic: str, payload: str) -> None:
        """MQTT Befehl aus Home Assistant (in der Ereignisschleife aufrufen)."""
        if topic == SCAN_COMMAND_TOPIC:
            LOG.info("Suche aus Home Assistant angefordert")
            self._scan_requested = True
            self._wake.set()
            return
        parts = topic.split("/")
        if len(parts) != 4 or parts[0] != BASE_TOPIC or parts[2:] != ["monitor", "set"]:
            return
        mac = self.store.mac_for_object_id(parts[1])
        if mac is None:
            return
        monitored = payload.strip().upper() == "ON"
        self.store.set_monitored(mac, monitored)
        self.store.save()
        self._sync_monitored()
        device = self._device_config(mac)
        LOG.info("%s: Überwachung %s", device.name, "eingeschaltet" if monitored else "ausgeschaltet")
        self.publisher.publish_device(device, monitored)
        if monitored:
            # Sofort abfragen statt bis zum nächsten Intervall zu warten
            self._wake.set()

    async def refresh_devices(self) -> None:
        """Ergänzt bei monitor_all_paired alle gekoppelten Geräte und meldet neue Geräte an HA."""
        if self.config.monitor_all_paired:
            for state in await self.bluez.devices():
                mac = state.get("Address", "").upper()
                if state.get("Paired") and mac and mac not in self._devices:
                    name = state.get("Alias") or state.get("Name") or mac
                    self.store.add(mac, name, monitored=True)
                    LOG.info("Gekoppeltes Gerät übernommen: %s (%s)", name, mac)
            self.store.save()
            self._sync_monitored()
        for mac, entry in self.store.items():
            if mac not in self._announced:
                self.publisher.publish_device(self._device_config(mac), bool(entry.get("monitored")))
                self._announced.add(mac)

    async def _scan(self) -> None:
        try:
            await self.scan_and_report()
        except DBusError as error:
            LOG.warning("Gerätesuche fehlgeschlagen: %s", error)

    async def run(self) -> None:
        self.publisher.publish_controls()
        if self.config.scan_on_start:
            await self._scan()
        while True:
            # Vor dem Abfragen zurücksetzen, damit Befehle während der Abfrage nicht verloren gehen
            self._wake.clear()
            if self._scan_requested:
                self._scan_requested = False
                await self._scan()
            await self.refresh_devices()
            if not self._devices:
                LOG.info("Noch kein Gerät ausgewählt: in Home Assistant beim Gerät 'Monitor battery' einschalten")
            for device in list(self._devices.values()):
                try:
                    await self.poll_device(device)
                except DBusError as error:
                    LOG.warning("%s: BlueZ Fehler: %s", device.name, error)
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._wake.wait(), self.config.poll_interval_seconds)
