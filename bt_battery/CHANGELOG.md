# Changelog

## 0.2.2

* Device scan hides unnamed devices (usually phones, watches or trackers nearby with rotating addresses), they appear only with `log_level: debug`
* Gerätesuche blendet Geräte ohne Namen aus (meist fremde Handys, Uhren oder Tracker mit wechselnder Adresse), sichtbar nur mit `log_level: debug`

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
