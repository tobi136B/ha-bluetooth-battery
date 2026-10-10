"""Einstiegspunkt: python -m bt_battery"""

from __future__ import annotations

import asyncio
import logging
import sys
import time

from . import __version__
from .app import BatteryService
from .bluez import BlueZ, HfpAgProfile, PairingAgent
from .config import load_config
from .mqtt_publisher import MqttPublisher

LOG = logging.getLogger("bt_battery")
RESTART_DELAY_SECONDS = 60


async def main_async() -> None:
    config = load_config()
    logging.getLogger().setLevel(config.log_level)
    LOG.info("Bluetooth Akku %s startet, Adapter %s, %d Geräte", __version__, config.adapter, len(config.devices))

    publisher = MqttPublisher(config.mqtt)
    publisher.connect()

    bluez = BlueZ(config.adapter)
    await bluez.connect()
    service = BatteryService(config, bluez, publisher)
    await bluez.register_agent(PairingAgent())
    service.hfp_available = await bluez.register_hfp_profile(
        HfpAgProfile(service.on_new_connection, service.on_disconnect_request)
    )
    if not service.hfp_available:
        LOG.warning(
            "Kopfhörer werden ersatzweise über den Akkustand von BlueZ abgefragt (org.bluez.Battery1). "
            "Dienste auf dem System D-Bus: %s",
            ", ".join(await bluez.bus_names()),
        )
    await bluez.power_on()
    try:
        await service.run()
    finally:
        publisher.close()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        pass
    except Exception:  # noqa: BLE001 - Supervisor startet das Add-on bei Fehlern neu
        LOG.exception("Unerwarteter Fehler, Neustart in %d s", RESTART_DELAY_SECONDS)
        # Verhindert eine schnelle Neustartschleife, die das Protokoll flutet
        time.sleep(RESTART_DELAY_SECONDS)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
