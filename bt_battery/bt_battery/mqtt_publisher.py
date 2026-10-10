"""Veröffentlichung per MQTT Discovery an Home Assistant."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

from .config import DeviceConfig, MqttConfig

LOG = logging.getLogger(__name__)

DISCOVERY_PREFIX = "homeassistant"
BASE_TOPIC = "bt_battery"


class MqttPublisher:
    def __init__(self, config: MqttConfig) -> None:
        self._config = config
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="bt_battery_addon")
        if config.username:
            self._client.username_pw_set(config.username, config.password)

    def connect(self) -> None:
        self._client.connect(self._config.host, self._config.port)
        self._client.loop_start()
        LOG.info("Mit MQTT Broker %s:%s verbunden", self._config.host, self._config.port)

    def close(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()

    @staticmethod
    def state_topic(device: DeviceConfig) -> str:
        return f"{BASE_TOPIC}/{device.object_id}/state"

    def publish_discovery(self, device: DeviceConfig) -> None:
        # Ohne availability: der zuletzt bekannte Wert bleibt sichtbar, wenn das Gerät aus ist
        payload = {
            "name": "Battery",
            "unique_id": device.object_id,
            "state_topic": self.state_topic(device),
            "value_template": "{{ value_json.level }}",
            "json_attributes_topic": self.state_topic(device),
            "unit_of_measurement": "%",
            "device_class": "battery",
            "state_class": "measurement",
            "device": {
                "identifiers": [device.object_id],
                "connections": [["bluetooth", device.mac]],
                "name": device.name,
            },
        }
        topic = f"{DISCOVERY_PREFIX}/sensor/{device.object_id}/config"
        self._client.publish(topic, json.dumps(payload), retain=True)

    def publish_scan_result(self, devices: list[dict]) -> None:
        """Sensor mit allen gefundenen Geräten, damit man MAC Adressen direkt in HA sieht."""
        topic = f"{BASE_TOPIC}/scan/state"
        payload = {
            "name": "Found devices",
            "unique_id": "bt_battery_scan",
            "state_topic": topic,
            "value_template": "{{ value_json.count }}",
            "json_attributes_topic": topic,
            "json_attributes_template": "{{ {'devices': value_json.devices, 'scanned': value_json.scanned} | tojson }}",
            "icon": "mdi:bluetooth-audio",
            "device": {"identifiers": ["bt_battery_addon"], "name": "Bluetooth Battery"},
        }
        self._client.publish(f"{DISCOVERY_PREFIX}/sensor/bt_battery_scan/config", json.dumps(payload), retain=True)
        state = {
            "count": len(devices),
            "devices": devices,
            "scanned": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        self._client.publish(topic, json.dumps(state), retain=True)

    def publish_battery(self, device: DeviceConfig, level: int, source: str) -> None:
        payload = {
            "level": level,
            "source": source,
            "last_seen": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        # retained: Home Assistant bekommt den letzten Wert auch nach einem Neustart
        self._client.publish(self.state_topic(device), json.dumps(payload), retain=True)
