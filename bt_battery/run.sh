#!/usr/bin/with-contenv bashio
# MQTT Zugangsdaten vom Supervisor (Mosquitto Add-on) übernehmen
export MQTT_HOST="$(bashio::services mqtt 'host')"
export MQTT_PORT="$(bashio::services mqtt 'port')"
export MQTT_USER="$(bashio::services mqtt 'username')"
export MQTT_PASSWORD="$(bashio::services mqtt 'password')"

bashio::log.info "Starte Bluetooth Akku"
exec python3 -m bt_battery
