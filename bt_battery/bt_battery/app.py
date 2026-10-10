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

from .bluez import HFP_HF_UUID, BlueZ, close_fd, path_to_mac
from .config import AppConfig, DeviceConfig
from .hfp import BatteryReport, HfpAgSession
from .mqtt_publisher import MqttPublisher

LOG = logging.getLogger(__name__)

CONNECT_TIMEOUT_SECONDS = 30
# Kurze Pause nach der Akkumeldung, damit der Kopfhörer seinen Verbindungsaufbau abschließen kann
DISCONNECT_DELAY_SECONDS = 2


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
    def __init__(self, config: AppConfig, bluez: BlueZ, publisher: MqttPublisher) -> None:
        self.config = config
        self.bluez = bluez
        self.publisher = publisher
        self._connections: dict[str, HfpConnection] = {}
        self._tasks: set[asyncio.Task] = set()

    # Rückrufe aus dem BlueZ Profil

    def on_new_connection(self, device_path: str, fd: int) -> None:
        mac = path_to_mac(device_path)
        device = self.config.device(mac)
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
            await self._poll_hfp(device)
        else:
            await self._poll_bluez_battery(device, state)

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

    async def _poll_bluez_battery(self, device: DeviceConfig, state: dict) -> None:
        """Übrige Geräte (v.a. BLE): Akkustand, den BlueZ selbst über org.bluez.Battery1 bereitstellt."""
        connected_by_us = False
        if not state.get("Connected"):
            try:
                await asyncio.wait_for(self.bluez.connect_device(device.mac), CONNECT_TIMEOUT_SECONDS)
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
            LOG.info("%s: kein Akkustand verfügbar (Gerät bietet keinen Akku Dienst an?)", device.name)
        finally:
            # Nur trennen, was wir selbst verbunden haben (z.B. keine Maus, die gerade benutzt wird)
            if connected_by_us and self.config.disconnect_after_read:
                await self.bluez.disconnect(device.mac)

    async def run(self) -> None:
        for device in self.config.devices:
            self.publisher.publish_discovery(device)
        while True:
            for device in self.config.devices:
                try:
                    await self.poll_device(device)
                except DBusError as error:
                    LOG.warning("%s: BlueZ Fehler: %s", device.name, error)
            await asyncio.sleep(self.config.poll_interval_seconds)
