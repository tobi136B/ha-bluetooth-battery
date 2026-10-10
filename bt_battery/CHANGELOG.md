# Changelog

## 0.4.0

* New per device: "Last update" (when the battery level was last measured) and "Reachable" (whether the last query could connect). The "Battery" sensor keeps the last known value
* Neu pro Gerät: "Last update" (wann der Akkustand zuletzt gemessen wurde) und "Reachable" (ob die letzte Abfrage verbinden konnte). Der Sensor "Battery" behält den zuletzt bekannten Wert

## 0.3.1

* Fix: a battery level of 0 % from BlueZ is treated as a placeholder and ignored, the add-on keeps waiting for the real value (seen with Razer headsets)
* Option `devices` is marked optional, devices are normally chosen in Home Assistant
* Fix: 0 % von BlueZ gilt als Platzhalter und wird ignoriert, das Add-on wartet weiter auf den echten Wert (beobachtet bei Razer Headsets)
* Option `devices` als optional gekennzeichnet, Geräte werden normalerweise in Home Assistant ausgewählt

## 0.3.0

* Choose devices directly in Home Assistant: every found headset, speaker or input device gets its own device with a "Monitor battery" switch. Switch it on and the "Battery" sensor appears, no MAC or YAML needed
* Found devices and the selection are stored in `/data/devices.json` and stay after a restart
* New button "Search devices" starts a scan from Home Assistant, no add-on restart needed
* Devices in the `devices` option are still monitored as before
* Geräte direkt in Home Assistant auswählen: Jeder gefundene Kopfhörer, Lautsprecher oder jedes Eingabegerät erscheint als eigenes Gerät mit dem Schalter "Monitor battery". Einschalten, dann erscheint der Sensor "Battery", ohne MAC oder YAML
* Gefundene Geräte und die Auswahl werden in `/data/devices.json` gespeichert und bleiben nach einem Neustart erhalten
* Neuer Knopf "Search devices" startet die Suche aus Home Assistant, ohne Neustart des Add-ons
* Geräte aus der Option `devices` werden weiterhin überwacht

## 0.2.3

* Fix: the device scan read the device list after stopping discovery, when BlueZ had already cleared the signal strength, so found devices could disappear from the result
* Fix: Die Gerätesuche las die Liste erst nach dem Ende der Suche, wenn BlueZ die Signalstärke schon gelöscht hatte. Gefundene Geräte konnten dadurch fehlen

## 0.2.2

* Device scan hides unnamed devices with random addresses (usually phones, watches or trackers nearby), they appear only with `log_level: debug`. Devices with a fixed address stay visible even without a name
* Gerätesuche blendet namenlose Geräte mit Zufallsadresse aus (meist fremde Handys, Uhren oder Tracker), sichtbar nur mit `log_level: debug`. Geräte mit fester Adresse bleiben auch ohne Namen sichtbar

## 0.2.1

* No crash loop when another service on the host already holds the HFP gateway role ("UUID already registered"): headsets fall back to the battery level BlueZ reports (`org.bluez.Battery1`), the log lists the D-Bus services for diagnosis
* Fatal errors wait 60 s before restarting
* Kein Absturz mehr, wenn ein anderer Dienst auf dem Host die HFP Gateway Rolle belegt ("UUID already registered"): Kopfhörer werden dann über den Akkustand von BlueZ (`org.bluez.Battery1`) abgefragt, das Protokoll listet die D-Bus Dienste zur Fehlersuche
* Bei schweren Fehlern 60 s Pause vor dem Neustart

## 0.2.0

* Device scan on start, results in the log and in the "Found devices" sensor
* Option `monitor_all_paired` to monitor every paired device without entering a MAC
* Windows script `tools/find_bluetooth_devices.py` to list paired devices with MAC and battery
* Add-on icon and logo, sensor name now "Battery"
* Gerätesuche beim Start, Ergebnis im Protokoll und im Sensor "Found devices"
* Option `monitor_all_paired`, überwacht alle gekoppelten Geräte ohne MAC Eingabe
* Windows Skript `tools/find_bluetooth_devices.py` listet gekoppelte Geräte mit MAC und Akku
* Icon und Logo, Sensorname jetzt "Battery"

## 0.1.0

* First release: HFP control channel (BIEV, Apple IPHONEACCEV, XEVENT), BLE Battery Service via org.bluez.Battery1, pairing, MQTT discovery
* Erste Version: HFP Steuerkanal (BIEV, Apple IPHONEACCEV, XEVENT), BLE Akku Dienst über org.bluez.Battery1, Kopplung, MQTT Discovery
