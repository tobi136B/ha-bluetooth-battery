"""
Anbindung an BlueZ über D-Bus.

Hinweis: Dieses Modul verzichtet bewusst auf "from __future__ import annotations",
weil dbus-fast die D-Bus Signaturen aus den Annotationen der Methoden liest.
"""

import asyncio
import logging
import os
from typing import Any, Callable

from dbus_fast import BusType, DBusError, Message, MessageType, Variant
from dbus_fast.aio import MessageBus
from dbus_fast.service import ServiceInterface, method

LOG = logging.getLogger(__name__)

BLUEZ = "org.bluez"
HFP_AG_UUID = "0000111f-0000-1000-8000-00805f9b34fb"
HFP_HF_UUID = "0000111e-0000-1000-8000-00805f9b34fb"
BATTERY_SERVICE_UUID = "0000180f-0000-1000-8000-00805f9b34fb"
PROFILE_PATH = "/io/github/tobi136b/bt_battery/hfp_ag"
AGENT_PATH = "/io/github/tobi136b/bt_battery/agent"


def mac_to_path(adapter: str, mac: str) -> str:
    return f"/org/bluez/{adapter}/dev_{mac.upper().replace(':', '_')}"


def path_to_mac(path: str) -> str:
    return path.rsplit("/", 1)[-1].removeprefix("dev_").replace("_", ":")


class HfpAgProfile(ServiceInterface):
    """org.bluez.Profile1: BlueZ übergibt hier die RFCOMM Verbindung als Dateideskriptor."""

    def __init__(
        self,
        on_connection: Callable[[str, int], None],
        on_disconnect_request: Callable[[str], None],
    ) -> None:
        super().__init__("org.bluez.Profile1")
        self._on_connection = on_connection
        self._on_disconnect_request = on_disconnect_request

    @method(name="Release")
    def release(self):
        LOG.info("Profil wurde von BlueZ freigegeben")

    @method(name="NewConnection")
    def new_connection(self, device: "o", fd: "h", properties: "a{sv}"):
        # dbus-fast übergibt den Deskriptor, wir sind ab hier für das Schließen zuständig
        self._on_connection(device, fd)

    @method(name="RequestDisconnection")
    def request_disconnection(self, device: "o"):
        self._on_disconnect_request(device)


class PairingAgent(ServiceInterface):
    """org.bluez.Agent1 ohne Ein-/Ausgabe: Kopfhörer koppeln per "Just Works"."""

    def __init__(self) -> None:
        super().__init__("org.bluez.Agent1")

    @method(name="Release")
    def release(self):
        pass

    @method(name="RequestPinCode")
    def request_pin_code(self, device: "o") -> "s":
        return "0000"

    @method(name="DisplayPinCode")
    def display_pin_code(self, device: "o", pincode: "s"):
        pass

    @method(name="RequestPasskey")
    def request_passkey(self, device: "o") -> "u":
        return 0

    @method(name="DisplayPasskey")
    def display_passkey(self, device: "o", passkey: "u", entered: "q"):
        pass

    @method(name="RequestConfirmation")
    def request_confirmation(self, device: "o", passkey: "u"):
        pass

    @method(name="RequestAuthorization")
    def request_authorization(self, device: "o"):
        pass

    @method(name="AuthorizeService")
    def authorize_service(self, device: "o", uuid: "s"):
        pass

    @method(name="Cancel")
    def cancel(self):
        pass


class BlueZ:
    """Hilfsfunktionen rund um Adapter, Geräte und Profilregistrierung."""

    def __init__(self, adapter: str) -> None:
        self.adapter = adapter
        self.adapter_path = f"/org/bluez/{adapter}"
        self.bus: MessageBus | None = None

    async def connect(self) -> None:
        # negotiate_unix_fd ist nötig, damit BlueZ uns den RFCOMM Socket übergeben kann
        self.bus = await MessageBus(bus_type=BusType.SYSTEM, negotiate_unix_fd=True).connect()

    async def _interface(self, path: str, interface: str) -> Any:
        introspection = await self.bus.introspect(BLUEZ, path)
        return self.bus.get_proxy_object(BLUEZ, path, introspection).get_interface(interface)

    async def register_agent(self, agent: PairingAgent) -> None:
        self.bus.export(AGENT_PATH, agent)
        agent_manager = await self._interface("/org/bluez", "org.bluez.AgentManager1")
        try:
            await agent_manager.call_register_agent(AGENT_PATH, "NoInputNoOutput")
            LOG.info("Kopplungsagent bei BlueZ registriert")
        except DBusError as error:
            LOG.warning("Kopplungsagent nicht registriert (%s), Kopplung evtl. nicht möglich", error)

    async def register_hfp_profile(self, profile: HfpAgProfile) -> bool:
        """
        Registriert den eigenen HFP Steuerkanal. Liefert False, wenn ein anderer
        Dienst auf dem Host (z.B. ein Audio Server) die HFP Gateway Rolle schon belegt.
        """
        self.bus.export(PROFILE_PATH, profile)
        profile_manager = await self._interface("/org/bluez", "org.bluez.ProfileManager1")
        try:
            await profile_manager.call_register_profile(
                PROFILE_PATH,
                HFP_AG_UUID,
                {
                    "Name": Variant("s", "Bluetooth Battery (HFP AG)"),
                    "Version": Variant("q", 0x0107),
                    "AutoConnect": Variant("b", True),
                },
            )
        except DBusError as error:
            self.bus.unexport(PROFILE_PATH)
            LOG.warning("Eigener HFP Steuerkanal nicht möglich: %s", error)
            return False
        LOG.info("HFP Steuerkanal bei BlueZ registriert")
        return True

    async def bus_names(self) -> list[str]:
        """Bekannte Dienstnamen auf dem System D-Bus (zur Fehlersuche)."""
        reply = await self.bus.call(
            Message(
                destination="org.freedesktop.DBus",
                path="/org/freedesktop/DBus",
                interface="org.freedesktop.DBus",
                member="ListNames",
            )
        )
        if reply.message_type == MessageType.ERROR:
            return []
        return sorted(name for name in reply.body[0] if not name.startswith(":"))

    async def power_on(self) -> None:
        adapter = await self._interface(self.adapter_path, "org.bluez.Adapter1")
        if not await adapter.get_powered():
            await adapter.set_powered(True)
            LOG.info("Adapter %s eingeschaltet", self.adapter)

    async def _managed_objects(self) -> dict[str, Any]:
        # Direkter Aufruf, weil nicht jede BlueZ Version ObjectManager in der Introspection auflistet
        reply = await self.bus.call(
            Message(
                destination=BLUEZ,
                path="/",
                interface="org.freedesktop.DBus.ObjectManager",
                member="GetManagedObjects",
            )
        )
        if reply.message_type == MessageType.ERROR:
            raise DBusError(reply.error_name, str(reply.body))
        return reply.body[0]

    @staticmethod
    def _device_from_interfaces(interfaces: dict[str, Any]) -> dict[str, Any] | None:
        device = interfaces.get("org.bluez.Device1")
        if device is None:
            return None
        state = {key: value.value for key, value in device.items()}
        # org.bluez.Battery1 existiert, sobald BlueZ einen Akkustand kennt (z.B. BLE Akku Dienst)
        battery = interfaces.get("org.bluez.Battery1")
        state["BatteryPercentage"] = battery["Percentage"].value if battery and "Percentage" in battery else None
        return state

    async def device_state(self, mac: str) -> dict[str, Any] | None:
        """Liefert die Device1 Eigenschaften eines Geräts oder None, wenn BlueZ es nicht kennt."""
        objects = await self._managed_objects()
        return self._device_from_interfaces(objects.get(mac_to_path(self.adapter, mac), {}))

    async def devices(self) -> list[dict[str, Any]]:
        """Alle Geräte, die BlueZ an diesem Adapter kennt (gekoppelt oder kürzlich gesehen)."""
        prefix = self.adapter_path + "/dev_"
        objects = await self._managed_objects()
        result = []
        for path, interfaces in objects.items():
            if path.startswith(prefix) and "/" not in path[len(prefix):]:
                state = self._device_from_interfaces(interfaces)
                if state is not None:
                    result.append(state)
        return result

    async def scan(self, seconds: int) -> None:
        """Sucht Classic und BLE Geräte in der Umgebung."""
        adapter = await self._interface(self.adapter_path, "org.bluez.Adapter1")
        await adapter.call_set_discovery_filter({"Transport": Variant("s", "auto")})
        await adapter.call_start_discovery()
        try:
            await asyncio.sleep(seconds)
        finally:
            try:
                await adapter.call_stop_discovery()
            except DBusError:
                pass

    async def pair(self, mac: str, discovery_seconds: int = 20) -> bool:
        """Sucht das Gerät (muss im Kopplungsmodus sein), koppelt es und setzt es vertrauenswürdig."""
        adapter = await self._interface(self.adapter_path, "org.bluez.Adapter1")
        path = mac_to_path(self.adapter, mac)

        if await self.device_state(mac) is None:
            await adapter.call_set_discovery_filter({"Transport": Variant("s", "auto")})
            await adapter.call_start_discovery()
            try:
                for _ in range(discovery_seconds):
                    await asyncio.sleep(1)
                    if await self.device_state(mac) is not None:
                        break
            finally:
                try:
                    await adapter.call_stop_discovery()
                except DBusError:
                    pass
            if await self.device_state(mac) is None:
                return False

        device = await self._interface(path, "org.bluez.Device1")
        try:
            await device.call_pair()
        except DBusError as error:
            if "AlreadyExists" not in str(error):
                LOG.warning("%s: Kopplung fehlgeschlagen: %s", mac, error)
                return False
        await device.set_trusted(True)
        return True

    async def connect_hfp(self, mac: str) -> None:
        device = await self._interface(mac_to_path(self.adapter, mac), "org.bluez.Device1")
        await device.call_connect_profile(HFP_HF_UUID)

    async def connect_device(self, mac: str) -> None:
        device = await self._interface(mac_to_path(self.adapter, mac), "org.bluez.Device1")
        await device.call_connect()

    async def disconnect(self, mac: str) -> None:
        device = await self._interface(mac_to_path(self.adapter, mac), "org.bluez.Device1")
        try:
            await device.call_disconnect()
        except DBusError as error:
            LOG.debug("%s: Trennen fehlgeschlagen: %s", mac, error)


def close_fd(fd: int) -> None:
    try:
        os.close(fd)
    except OSError:
        pass
