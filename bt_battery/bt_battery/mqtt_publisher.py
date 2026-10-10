"""Veröffentlichung per MQTT Discovery an Home Assistant."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

from .config import DeviceConfig, MqttConfig

LOG = logging.getLogger(__name__)

DISCOVERY_PREFIX = "homeassistant"
BASE_TOPIC = "bt_battery"
SCAN_COMMAND_TOPIC = f"{BASE_TOPIC}/scan/run"
MONITOR_COMMAND_TOPIC = f"{BASE_TOPIC}/+/monitor/set"
HUB_DEVICE = {"identifiers": ["bt_battery_addon"], "name": "Bluetooth Battery"}


class MqttPublisher:
    def __init__(self, config: MqttConfig, on_command: Callable[[str, str], None] | None = None) -> None:
        self._config = config
        # Wird im MQTT Thread aufgerufen, der Empfänger muss selbst in seine Ereignisschleife wechseln
        self._on_command = on_command
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="bt_battery_addon")
        if config.username:
            self._client.username_pw_set(config.username, config.password)
        self._client.on_connect = self._handle_connect
        self._client.on_message = self._handle_message

    def _handle_connect(self, client, userdata, flags, reason_code, properties) -> None:
        # Bei jeder (Wieder)Verbindung neu abonnieren
        client.subscribe([(SCAN_COMMAND_TOPIC, 0), (MONITOR_COMMAND_TOPIC, 0)])

    def _handle_message(self, client, userdata, message) -> None:
        if self._on_command is not None:
            self._on_command(message.topic, message.payload.decode("utf-8", errors="replace"))

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

    @staticmethod
    def monitor_topic(device: DeviceConfig) -> str:
        return f"{BASE_TOPIC}/{device.object_id}/monitor"

    @staticmethod
    def device_info(device: DeviceConfig) -> dict:
        return {
            "identifiers": [device.object_id],
            "connections": [["bluetooth", device.mac]],
            "name": device.name,
            "via_device": HUB_DEVICE["identifiers"][0],
        }

    def publish_controls(self) -> None:
        """Knopf "Search devices" am Gerät "Bluetooth Battery", startet eine neue Suche."""
        payload = {
            "name": "Search devices",
            "unique_id": "bt_battery_scan_button",
            "command_topic": SCAN_COMMAND_TOPIC,
            "icon": "mdi:bluetooth-settings",
            "device": HUB_DEVICE,
        }
        self._client.publish(f"{DISCOVERY_PREFIX}/button/bt_battery_scan/config", json.dumps(payload), retain=True)

    def publish_device(self, device: DeviceConfig, monitored: bool) -> None:
        """Ein Bluetooth Gerät in HA: Schalter "Monitor battery" und, falls überwacht, Sensor "Battery"."""
        topic = self.monitor_topic(device)
        payload = {
            "name": "Monitor battery",
            "unique_id": f"{device.object_id}_monitor",
            "command_topic": f"{topic}/set",
            "state_topic": topic,
            "icon": "mdi:battery-sync",
            "entity_category": "config",
            "device": self.device_info(device),
        }
        self._client.publish(f"{DISCOVERY_PREFIX}/switch/{device.object_id}/config", json.dumps(payload), retain=True)
        self._client.publish(topic, "ON" if monitored else "OFF", retain=True)
        if monitored:
            self.publish_discovery(device)
        else:
            # Leere retained Nachrichten entfernen die Sensoren wieder aus HA
            for topic in self._sensor_config_topics(device):
                self._client.publish(topic, "", retain=True)

    @staticmethod
    def reachable_topic(device: DeviceConfig) -> str:
        return f"{BASE_TOPIC}/{device.object_id}/reachable"

    @staticmethod
    def _sensor_config_topics(device: DeviceConfig) -> list[str]:
        return [
            f"{DISCOVERY_PREFIX}/sensor/{device.object_id}/config",
            f"{DISCOVERY_PREFIX}/sensor/{device.object_id}_last_update/config",
            f"{DISCOVERY_PREFIX}/binary_sensor/{device.object_id}_reachable/config",
        ]

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
            "device": self.device_info(device),
        }
        battery_topic, last_update_topic, reachable_topic = self._sensor_config_topics(device)
        self._client.publish(battery_topic, json.dumps(payload), retain=True)
        # Zeitpunkt des zuletzt gemessenen Akkustands
        last_update = {
            "name": "Last update",
            "unique_id": f"{device.object_id}_last_update",
            "state_topic": self.state_topic(device),
            "value_template": "{{ value_json.last_seen }}",
            "device_class": "timestamp",
            "entity_category": "diagnostic",
            "device": self.device_info(device),
        }
        self._client.publish(last_update_topic, json.dumps(last_update), retain=True)
        # Ergebnis der letzten Abfrage: konnte das Add-on das Gerät verbinden?
        reachable = {
            "name": "Reachable",
            "unique_id": f"{device.object_id}_reachable",
            "state_topic": self.reachable_topic(device),
            "device_class": "connectivity",
            "entity_category": "diagnostic",
            "device": self.device_info(device),
        }
        self._client.publish(reachable_topic, json.dumps(reachable), retain=True)

    def publish_reachable(self, device: DeviceConfig, reachable: bool) -> None:
        self._client.publish(self.reachable_topic(device), "ON" if reachable else "OFF", retain=True)

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
            "device": HUB_DEVICE,
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
