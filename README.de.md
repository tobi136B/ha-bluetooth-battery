# ha-bluetooth-battery

[English](README.md) | **Deutsch**

Home Assistant Add-on, das den Akkustand von Bluetooth Geräten direkt auf
Home Assistant OS ausliest und per MQTT als Sensor bereitstellt: Kopfhörer,
Headsets und BLE Geräte wie Mäuse, Tastaturen oder Controller. Kein Handy,
keine App, kein Zusatzrechner nötig. Pro Gerät bleibt der zuletzt bekannte
Wert samt Zeitstempel erhalten.

## Installation

1. In Home Assistant: Einstellungen > Add-ons > Add-on Store > ⋮ > Repositories
2. `https://github.com/tobi136B/ha-bluetooth-battery` hinzufügen
3. Add-on "Bluetooth Battery" installieren, Optionen ausfüllen, starten

Details zur Einrichtung stehen in [bt_battery/DOCS.de.md](bt_battery/DOCS.de.md).

## Geräte finden

* Das Add-on sucht beim Start und listet alle Geräte in der Nähe mit MAC Adresse im Protokoll und im Sensor "Found devices".
* Mit `monitor_all_paired: true` wird jedes gekoppelte Gerät ohne MAC Eingabe überwacht.
* Unter Windows listet [tools/find_bluetooth_devices.py](tools/find_bluetooth_devices.py) alle gekoppelten Geräte mit MAC Adresse und Akkustand (nur Standardbibliothek, Python 3.12 oder neuer):

  ```powershell
  python tools\find_bluetooth_devices.py
  ```

## Funktionsweise

**BLE Geräte:** Das Add-on verbindet kurz, BlueZ liest den Standard Akku Dienst
(GATT 0x180F) und stellt ihn als `org.bluez.Battery1` bereit.

**Kopfhörer und Headsets:** Das Add-on registriert über D-Bus bei BlueZ ein HFP Audio Gateway Profil (nur
Steuerkanal, ohne Audio). Verbindet sich ein Kopfhörer, beantwortet es den AT
Befehlsdialog wie ein Telefon und wertet die Akkumeldungen aus:

| Quelle | AT Befehl |
|:--|:--|
| HFP 1.7 HF Indikator | `AT+BIEV=2,<0..100>` |
| Apple Erweiterung | `AT+IPHONEACCEV` (Schlüssel 1) |
| Plantronics/Android | `AT+XEVENT=BATTERY` |

Das Attribut `source` zeigt, woher ein Wert stammt (`hfp`, `apple`, `xevent`, `bluez`).
Die Werte gehen per MQTT Discovery (retained) an Home Assistant.

## Dashboard Beispiel

```yaml
type: markdown
title: Bluetooth Akkus
content: >
  | Gerät | Akku | Stand von |
  |:--|--:|:--|
  {% for s in states.sensor | selectattr('attributes.last_seen', 'defined')
       | selectattr('attributes.source', 'defined') | sort(attribute='entity_id') %}
  | {{ device_attr(s.entity_id, 'name') or s.name }} | {{ s.state }} % | {{ (as_datetime(s.attributes.last_seen) | as_local).strftime('%d.%m. %H:%M') }} |
  {% endfor %}
```

## Entwicklung

```bash
pip install dbus-fast paho-mqtt pytest
pytest tests
```

Der Integrationstest startet einen privaten D-Bus mit simuliertem BlueZ und
simuliertem Kopfhörer (benötigt `dbus-daemon`).

## Lizenz

MIT
