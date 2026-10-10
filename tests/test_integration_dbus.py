"""
Integrationstest mit simuliertem BlueZ auf einem privaten D-Bus.

Prüft den kompletten Weg: Profilregistrierung, Übergabe des RFCOMM Sockets als
Dateideskriptor, HFP Verbindungsaufbau mit einem simulierten Kopfhörer,
Akkumeldung, Veröffentlichung und Trennen.
"""

import asyncio
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bt_battery"))

from dbus_fast import BusType, DBusError, Message, MessageType, Variant  # noqa: E402
from dbus_fast.aio import MessageBus  # noqa: E402
from dbus_fast.service import PropertyAccess, ServiceInterface, dbus_property, method  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("dbus-daemon") is None, reason="dbus-daemon fehlt")

MAC = "AA:BB:CC:DD:EE:01"
DEVICE_PATH = "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_01"


class FakeBluez:
    """Hält den Zustand des simulierten BlueZ und den simulierten Kopfhörer."""

    def __init__(self, bus: MessageBus) -> None:
        self.bus = bus
        self.client_name = ""
        self.profile_path = ""
        self.headphone_log: list[bytes] = []
        self.connected = False

    async def open_hfp(self) -> None:
        ag_side, hf_side = socket.socketpair()
        reply = await self.bus.call(
            Message(
                destination=self.client_name,
                path=self.profile_path,
                interface="org.bluez.Profile1",
                member="NewConnection",
                signature="oha{sv}",
                body=[DEVICE_PATH, 0, {}],
                unix_fds=[ag_side.fileno()],
            )
        )
        assert reply.message_type == MessageType.METHOD_RETURN, reply.body
        ag_side.close()
        self.connected = True
        asyncio.get_running_loop().create_task(self._headphone(hf_side))

    async def _headphone(self, sock: socket.socket) -> None:
        loop = asyncio.get_running_loop()
        sock.setblocking(False)
        for command in (b"AT+BRSF=959\r", b"AT+CIND=?\r", b"AT+CIND?\r", b"AT+CMER=3,0,0,1\r",
                        b"AT+XAPL=009E-4020-0100,3\r", b"AT+IPHONEACCEV=1,1,7\r"):
            await loop.sock_sendall(sock, command)
            self.headphone_log.append(await loop.sock_recv(sock, 1024))
        # Gegenstelle schließt nach dem Trennen
        self.headphone_log.append(await loop.sock_recv(sock, 1024))
        sock.close()

    async def request_disconnection(self) -> None:
        await self.bus.call(
            Message(
                destination=self.client_name,
                path=self.profile_path,
                interface="org.bluez.Profile1",
                member="RequestDisconnection",
                signature="o",
                body=[DEVICE_PATH],
            )
        )
        self.connected = False


class ProfileManager(ServiceInterface):
    def __init__(self, state: FakeBluez) -> None:
        super().__init__("org.bluez.ProfileManager1")
        self.state = state

    @method(name="RegisterProfile")
    def register_profile(self, path: "o", uuid: "s", options: "a{sv}"):
        assert uuid == "0000111f-0000-1000-8000-00805f9b34fb"
        self.state.profile_path = path


class AgentManager(ServiceInterface):
    def __init__(self) -> None:
        super().__init__("org.bluez.AgentManager1")

    @method(name="RegisterAgent")
    def register_agent(self, path: "o", capability: "s"):
        assert capability == "NoInputNoOutput"


class Adapter(ServiceInterface):
    def __init__(self) -> None:
        super().__init__("org.bluez.Adapter1")
        self._powered = False
        self.discovering = False

    @method(name="SetDiscoveryFilter")
    def set_discovery_filter(self, properties: "a{sv}"):
        pass

    @method(name="StartDiscovery")
    def start_discovery(self):
        self.discovering = True

    @method(name="StopDiscovery")
    def stop_discovery(self):
        self.discovering = False
        self.stopped_once = True

    @dbus_property(name="Powered")
    def powered(self) -> "b":
        return self._powered

    @powered.setter
    def powered(self, value: "b"):
        self._powered = value


class Device(ServiceInterface):
    def __init__(self, state: FakeBluez) -> None:
        super().__init__("org.bluez.Device1")
        self.state = state

    @dbus_property(access=PropertyAccess.READ, name="Paired")
    def paired(self) -> "b":
        return True

    @dbus_property(name="Trusted")
    def trusted(self) -> "b":
        return True

    @trusted.setter
    def trusted(self, value: "b"):
        pass

    @dbus_property(access=PropertyAccess.READ, name="Address")
    def address(self) -> "s":
        return MAC

    @dbus_property(access=PropertyAccess.READ, name="Alias")
    def alias(self) -> "s":
        return "Bose QC SC"

    @dbus_property(access=PropertyAccess.READ, name="Icon")
    def icon(self) -> "s":
        return "audio-headset"

    @dbus_property(access=PropertyAccess.READ, name="RSSI")
    def rssi(self) -> "n":
        return -50

    @dbus_property(access=PropertyAccess.READ, name="UUIDs")
    def uuids(self) -> "as":
        return ["0000111e-0000-1000-8000-00805f9b34fb", "0000110b-0000-1000-8000-00805f9b34fb"]

    @dbus_property(access=PropertyAccess.READ, name="Connected")
    def connected(self) -> "b":
        return self.state.connected

    @method(name="ConnectProfile")
    async def connect_profile(self, uuid: "s"):
        assert uuid == "0000111e-0000-1000-8000-00805f9b34fb"
        await self.state.open_hfp()

    @method(name="Disconnect")
    async def disconnect(self):
        await self.state.request_disconnection()


BLE_MAC = "AA:BB:CC:DD:EE:02"
BLE_PATH = "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_02"


class Battery(ServiceInterface):
    def __init__(self) -> None:
        super().__init__("org.bluez.Battery1")

    @dbus_property(access=PropertyAccess.READ, name="Percentage")
    def percentage(self) -> "y":
        return 42


class BleDevice(ServiceInterface):
    """BLE Maus: Akku Dienst erscheint als org.bluez.Battery1 erst nach dem Verbinden."""

    def __init__(self, bus: MessageBus) -> None:
        super().__init__("org.bluez.Device1")
        self.bus = bus
        self.is_connected = False
        self.disconnect_calls = 0

    @dbus_property(access=PropertyAccess.READ, name="Paired")
    def paired(self) -> "b":
        return True

    @dbus_property(access=PropertyAccess.READ, name="Connected")
    def connected(self) -> "b":
        return self.is_connected

    @dbus_property(access=PropertyAccess.READ, name="Address")
    def address(self) -> "s":
        return BLE_MAC

    @dbus_property(access=PropertyAccess.READ, name="Alias")
    def alias(self) -> "s":
        return "MX Master"

    @dbus_property(access=PropertyAccess.READ, name="UUIDs")
    def uuids(self) -> "as":
        return ["0000180f-0000-1000-8000-00805f9b34fb"]

    @method(name="Connect")
    def connect(self):
        self.is_connected = True
        self.bus.export(BLE_PATH, Battery())

    @method(name="Disconnect")
    def disconnect(self):
        self.is_connected = False
        self.disconnect_calls += 1


class UnnamedNeighbour(ServiceInterface):
    """Fremdes BLE Gerät mit zufälliger Adresse und ohne Namen (z.B. ein Handy in der Nachbarschaft)."""

    def __init__(self) -> None:
        super().__init__("org.bluez.Device1")

    @dbus_property(access=PropertyAccess.READ, name="Address")
    def address(self) -> "s":
        return "41:C6:91:5F:D2:37"

    @dbus_property(access=PropertyAccess.READ, name="Alias")
    def alias(self) -> "s":
        return "41-C6-91-5F-D2-37"

    @dbus_property(access=PropertyAccess.READ, name="Paired")
    def paired(self) -> "b":
        return False

    @dbus_property(access=PropertyAccess.READ, name="AddressType")
    def address_type(self) -> "s":
        return "random"

    @dbus_property(access=PropertyAccess.READ, name="RSSI")
    def rssi(self) -> "n":
        return -40


class UnnamedClassic(ServiceInterface):
    """Gerät mit fester Adresse, dessen Name noch nicht gelesen wurde: muss sichtbar bleiben."""

    def __init__(self) -> None:
        super().__init__("org.bluez.Device1")

    @dbus_property(access=PropertyAccess.READ, name="Address")
    def address(self) -> "s":
        return "AC:80:0A:12:34:56"

    @dbus_property(access=PropertyAccess.READ, name="AddressType")
    def address_type(self) -> "s":
        return "public"

    @dbus_property(access=PropertyAccess.READ, name="Paired")
    def paired(self) -> "b":
        return False

    @dbus_property(access=PropertyAccess.READ, name="RSSI")
    def rssi(self) -> "n":
        return -70


class RecordingPublisher:
    def __init__(self) -> None:
        self.values: list[tuple[str, int, str]] = []

    def publish_discovery(self, device) -> None:
        pass

    def publish_scan_result(self, devices) -> None:
        self.scan = devices

    def publish_battery(self, device, level: int, source: str) -> None:
        self.values.append((device.name, level, source))


@pytest.fixture()
def private_bus(monkeypatch):
    process = subprocess.Popen(
        ["dbus-daemon", "--session", "--nofork", "--print-address=1"],
        stdout=subprocess.PIPE,
        text=True,
    )
    address = process.stdout.readline().strip()
    monkeypatch.setenv("DBUS_SYSTEM_BUS_ADDRESS", address)
    yield address
    process.terminate()
    process.wait()


def test_full_flow(private_bus) -> None:
    from bt_battery.app import BatteryService
    from bt_battery.bluez import BlueZ, HfpAgProfile, PairingAgent
    from bt_battery.config import AppConfig, DeviceConfig, MqttConfig

    async def scenario() -> None:
        fake_bus = await MessageBus(bus_type=BusType.SYSTEM, negotiate_unix_fd=True).connect()
        state = FakeBluez(fake_bus)
        fake_bus.export("/org/bluez", ProfileManager(state))
        fake_bus.export("/org/bluez", AgentManager())
        fake_bus.export("/org/bluez/hci0", Adapter())
        fake_bus.export(DEVICE_PATH, Device(state))
        ble_device = BleDevice(fake_bus)
        fake_bus.export(BLE_PATH, ble_device)
        await fake_bus.request_name("org.bluez")

        config = AppConfig(
            adapter="hci0",
            poll_interval_seconds=60,
            hold_seconds=5,
            disconnect_after_read=True,
            log_level="DEBUG",
            scan_on_start=True,
            scan_seconds=0,
            monitor_all_paired=False,
            mqtt=MqttConfig(host="unused"),
            devices=[DeviceConfig(mac=MAC, name="Bose QC SC"), DeviceConfig(mac=BLE_MAC, name="BLE Maus")],
        )
        publisher = RecordingPublisher()
        bluez = BlueZ("hci0")
        await bluez.connect()
        state.client_name = bluez.bus.unique_name
        service = BatteryService(config, bluez, publisher)
        await bluez.register_agent(PairingAgent())
        assert await bluez.register_hfp_profile(HfpAgProfile(service.on_new_connection, service.on_disconnect_request))
        await bluez.power_on()

        await service.poll_device(config.devices[0])
        # Trennen erfolgt kurz nach der Akkumeldung
        for _ in range(50):
            if not state.connected:
                break
            await asyncio.sleep(0.1)

        assert publisher.values == [("Bose QC SC", 80, "apple")]
        assert b"+BRSF:" in state.headphone_log[0]
        assert b"+XAPL=iPhone" in state.headphone_log[4]
        assert not state.connected
        assert service._connections == {}
        await asyncio.sleep(0.2)
        assert state.headphone_log[-1] == b""  # Socket wurde von uns geschlossen

        # BLE Gerät über org.bluez.Battery1, danach wieder getrennt
        await service.poll_device(config.devices[1])
        assert publisher.values[-1] == ("BLE Maus", 42, "bluez")
        assert ble_device.disconnect_calls == 1

    asyncio.run(scenario())


def test_scan_and_monitor_all_paired(private_bus) -> None:
    from bt_battery.app import BatteryService
    from bt_battery.bluez import BlueZ
    from bt_battery.config import AppConfig, MqttConfig

    async def scenario() -> None:
        fake_bus = await MessageBus(bus_type=BusType.SYSTEM, negotiate_unix_fd=True).connect()
        state = FakeBluez(fake_bus)
        adapter = Adapter()
        fake_bus.export("/org/bluez/hci0", adapter)
        fake_bus.export(DEVICE_PATH, Device(state))
        fake_bus.export(BLE_PATH, BleDevice(fake_bus))
        fake_bus.export("/org/bluez/hci0/dev_41_C6_91_5F_D2_37", UnnamedNeighbour())
        fake_bus.export("/org/bluez/hci0/dev_AC_80_0A_12_34_56", UnnamedClassic())
        await fake_bus.request_name("org.bluez")

        config = AppConfig(
            adapter="hci0", poll_interval_seconds=60, hold_seconds=5, disconnect_after_read=True,
            log_level="INFO", scan_on_start=True, scan_seconds=0, monitor_all_paired=True,
            mqtt=MqttConfig(host="unused"), devices=[],
        )
        publisher = RecordingPublisher()
        bluez = BlueZ("hci0")
        await bluez.connect()
        service = BatteryService(config, bluez, publisher)

        # Die Geräteliste muss gelesen werden, solange die Suche noch läuft (BlueZ löscht danach RSSI)
        read_while_discovering = []
        original_devices = bluez.devices

        async def recording_devices():
            read_while_discovering.append(adapter.discovering)
            return await original_devices()

        bluez.devices = recording_devices
        await service.scan_and_report()
        bluez.devices = original_devices
        assert read_while_discovering == [True]
        assert adapter.discovering is False
        macs = {entry["mac"] for entry in publisher.scan}
        assert "41:C6:91:5F:D2:37" not in macs
        assert "AC:80:0A:12:34:56" in macs
        by_mac = {entry["mac"]: entry for entry in publisher.scan}
        assert by_mac[MAC]["battery_method"] == "hfp" and by_mac[MAC]["type"] == "audio-headset"
        assert by_mac[BLE_MAC]["battery_method"] == "ble_battery" and by_mac[BLE_MAC]["name"] == "MX Master"
        # Stärkstes Signal zuerst, Geräte ohne RSSI (nur gekoppelt) am Ende
        assert publisher.scan[0]["mac"] == MAC

        await service.refresh_devices()
        assert sorted(service._devices) == [MAC, BLE_MAC]
        assert service._devices[BLE_MAC].name == "MX Master"

    asyncio.run(scenario())


class OccupiedProfileManager(ServiceInterface):
    """Simuliert einen Host, auf dem ein Audio Server die HFP Gateway Rolle schon belegt."""

    def __init__(self) -> None:
        super().__init__("org.bluez.ProfileManager1")

    @method(name="RegisterProfile")
    def register_profile(self, path: "o", uuid: "s", options: "a{sv}"):
        raise DBusError("org.bluez.Error.NotPermitted", "UUID already registered")


class ForeignHfpHeadset(ServiceInterface):
    """Kopfhörer, dessen HFP Verbindung ein fremder Dienst bedient und den Akku an BlueZ meldet."""

    def __init__(self, bus: MessageBus) -> None:
        super().__init__("org.bluez.Device1")
        self.bus = bus
        self.is_connected = False
        self.connected_profiles: list[str] = []

    @dbus_property(access=PropertyAccess.READ, name="Paired")
    def paired(self) -> "b":
        return True

    @dbus_property(access=PropertyAccess.READ, name="Connected")
    def connected(self) -> "b":
        return self.is_connected

    @dbus_property(access=PropertyAccess.READ, name="UUIDs")
    def uuids(self) -> "as":
        return ["0000111e-0000-1000-8000-00805f9b34fb"]

    @method(name="ConnectProfile")
    def connect_profile(self, uuid: "s"):
        self.connected_profiles.append(uuid)
        self.is_connected = True
        self.bus.export(DEVICE_PATH, Battery())

    @method(name="Disconnect")
    def disconnect(self):
        self.is_connected = False


def test_fallback_when_hfp_is_occupied(private_bus) -> None:
    from bt_battery.app import BatteryService
    from bt_battery.bluez import BlueZ, HfpAgProfile
    from bt_battery.config import AppConfig, DeviceConfig, MqttConfig

    async def scenario() -> None:
        fake_bus = await MessageBus(bus_type=BusType.SYSTEM, negotiate_unix_fd=True).connect()
        fake_bus.export("/org/bluez", OccupiedProfileManager())
        headset = ForeignHfpHeadset(fake_bus)
        fake_bus.export(DEVICE_PATH, headset)
        await fake_bus.request_name("org.bluez")

        config = AppConfig(
            adapter="hci0", poll_interval_seconds=60, hold_seconds=5, disconnect_after_read=True,
            log_level="INFO", scan_on_start=False, scan_seconds=0, monitor_all_paired=False,
            mqtt=MqttConfig(host="unused"), devices=[DeviceConfig(mac=MAC, name="Bose QC SC")],
        )
        publisher = RecordingPublisher()
        bluez = BlueZ("hci0")
        await bluez.connect()
        service = BatteryService(config, bluez, publisher)

        # Kein Absturz mehr, sondern Rückfall auf org.bluez.Battery1
        service.hfp_available = await bluez.register_hfp_profile(
            HfpAgProfile(service.on_new_connection, service.on_disconnect_request)
        )
        assert service.hfp_available is False
        assert "org.bluez" in await bluez.bus_names()

        await service.poll_device(config.devices[0])
        assert headset.connected_profiles == ["0000111e-0000-1000-8000-00805f9b34fb"]
        assert publisher.values == [("Bose QC SC", 42, "bluez")]
        assert headset.is_connected is False

    asyncio.run(scenario())
