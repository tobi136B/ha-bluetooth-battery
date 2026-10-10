# Bluetooth Akku

[English](DOCS.md) | **Deutsch**

Liest den Akkustand von Bluetooth Geräten direkt auf Home Assistant OS aus und
meldet ihn per MQTT. Pro Gerät entsteht ein Sensor "Akku", der den zuletzt
bekannten Wert behält (Attribut `last_seen` zeigt, wann er gemessen wurde).

## Wie es funktioniert

Das Add-on erkennt pro Gerät automatisch den passenden Weg:

* **Kopfhörer und Headsets** (Geräte mit Freisprechprofil HFP): Das Add-on meldet
  sich als "Telefon" an, nur für den Steuerkanal, ohne Ton. Kopfhörer schicken
  darüber ihren Akkustand, genau wie an ein Handy.
* **Alle anderen Geräte**, vor allem BLE (Mäuse, Tastaturen, Controller, Tracker):
  Das Add-on verbindet kurz, und BlueZ liest den Standard Akku Dienst aus.

Danach trennt das Add-on wieder, damit der Verbindungsplatz am Gerät frei bleibt.
Geräte, die bereits verbunden waren, bleiben verbunden.

## Voraussetzungen

* Mosquitto Broker Add-on und MQTT Integration
* Das Gerät muss seinen Akku über einen Standardweg melden: HFP (Kopfhörer mit Mikrofon) oder den BLE Akku Dienst. Lautsprecher ohne Mikrofon und Geräte, die nur über eine Hersteller App ihren Akku zeigen, liefern meist nichts.
* Ist das Gerät zusätzlich mit Handy oder PC verbunden, braucht es einen freien Verbindungsplatz (bei Kopfhörern Multipoint). Viele BLE Mäuse und Tastaturen erlauben nur eine Verbindung und lassen sich daher nur abfragen, wenn sie gerade nicht benutzt werden.

## Empfehlung: eigener USB Dongle

Am stabilsten läuft das Add-on mit einem eigenen USB Bluetooth Dongle:

1. Dongle einstecken, unter Einstellungen > System > Hardware den Namen prüfen (meist `hci1`).
2. Unter Einstellungen > Geräte & Dienste > Bluetooth den neuen Adapter **ignorieren**, damit HA ihn nicht für BLE nutzt.
3. In den Add-on Optionen `adapter: hci1` eintragen.

Ohne Dongle geht auch `hci0`, dann teilen sich Add-on und HA Bluetooth den Adapter.

## Einrichtung

1. Geräte finden, dafür gibt es drei Wege:
   * **Automatische Suche:** Geräte einschalten (neue in den Kopplungsmodus) und das Add-on starten.
     Es sucht beim Start und listet alle Geräte in der Nähe mit MAC Adresse, Typ und Akku Methode
     im Protokoll und im Sensor **"Found devices"** (Attribut `devices`).
   * **Bereits gekoppelte Geräte:** `monitor_all_paired: true` setzen, dann wird jedes am Adapter gekoppelte Gerät ohne MAC Eingabe überwacht.
   * **Windows PC:** `python tools/find_bluetooth_devices.py` aus diesem Repository ausführen. Es listet alle mit Windows gekoppelten Geräte mit MAC Adresse und Akkustand und gibt einen fertigen Block für die Optionen aus.
2. Optionen ausfüllen:

   ```yaml
   adapter: hci1
   devices:
     - mac: "AA:BB:CC:DD:EE:01"
       name: Bose QuietComfort SC
     - mac: "AA:BB:CC:DD:EE:02"
       name: Razer BlackShark V3 Pro
   ```

3. Geräte in den Kopplungsmodus versetzen und das Add-on starten. Es sucht und koppelt nicht gekoppelte Geräte selbst.
4. Im Protokoll erscheint z.B. `Bose QuietComfort SC: 80 % (apple)`.

## Optionen

| Option | Bedeutung |
|:--|:--|
| `adapter` | Bluetooth Adapter, z.B. `hci0` oder `hci1` |
| `devices` | Geräte mit `mac` und `name` |
| `poll_interval_minutes` | Abfrageintervall, Standard 15 |
| `hold_seconds` | Wartezeit auf die Akkumeldung pro Verbindung |
| `disconnect_after_read` | Nach dem Lesen trennen (empfohlen) |
| `log_level` | `debug` zeigt den kompletten AT Dialog, hilfreich bei Problemen |
| `scan_on_start` | Beim Start nach Geräten suchen und auflisten (Standard an) |
| `scan_seconds` | Suchdauer, Standard 30 |
| `monitor_all_paired` | Alle gekoppelten Geräte automatisch überwachen |

## Bekannte Grenzen

* Ist das Gerät aus oder sind alle Verbindungsplätze belegt, bleibt der letzte Wert stehen.
* Manche Kopfhörer sagen beim Verbinden "Connected" an. Dann das Intervall erhöhen.
* Wenn ein Gerät keinen Wert liefert: `log_level: debug` setzen und das Protokoll ansehen.
