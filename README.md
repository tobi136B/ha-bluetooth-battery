# ha-bluetooth-battery

**English** | [Deutsch](README.de.md)

Home Assistant add-on that reads the battery level of Bluetooth devices directly
on Home Assistant OS and exposes it as a sensor via MQTT: headphones, headsets
and BLE devices such as mice, keyboards or controllers. No phone, no app, no
extra computer required. The last known value and its timestamp are kept for
every device.

## Installation

1. In Home Assistant: Settings > Add-ons > Add-on Store > ⋮ > Repositories
2. Add `https://github.com/tobi136B/ha-bluetooth-battery`
3. Install the "Bluetooth Battery" add-on, fill in the options, start it

Setup details: [bt_battery/DOCS.md](bt_battery/DOCS.md).

## Finding your devices

* The add-on scans on start. Every found headset, speaker or input device shows up in Home Assistant as its own device with a **"Monitor battery"** switch. Switch it on and the battery sensor appears. The selection survives restarts, and the **"Search devices"** button scans again at any time.
* With `monitor_all_paired: true` every paired device is monitored without entering a MAC.
* On Windows, [tools/find_bluetooth_devices.py](tools/find_bluetooth_devices.py) lists all paired devices with MAC address and battery level (standard library only, Python 3.12 or newer):

  ```powershell
  python tools\find_bluetooth_devices.py
  ```

## How it works

**BLE devices:** The add-on connects briefly, BlueZ reads the standard Battery
Service (GATT 0x180F) and exposes it as `org.bluez.Battery1`.

**Headphones and headsets:** The add-on registers an HFP Audio Gateway profile
with BlueZ via D-Bus (control channel only, no audio). When a headset connects,
the add-on answers the AT command dialog like a phone and evaluates the battery
reports:

| Source | AT command |
|:--|:--|
| HFP 1.7 HF indicator | `AT+BIEV=2,<0..100>` |
| Apple extension | `AT+IPHONEACCEV` (key 1) |
| Plantronics/Android | `AT+XEVENT=BATTERY` |

The `source` attribute shows where a value came from (`hfp`, `apple`, `xevent`, `bluez`).
Values are published via MQTT discovery (retained) to Home Assistant.

## Limitations

* The device must report its battery in a standard way (HFP or BLE Battery Service).
  Speakers without a microphone and devices that only show their battery in a vendor app usually report nothing.
* A device that is also connected to a phone or PC needs a free connection slot (multipoint for headphones).

## Dashboard example

```yaml
type: markdown
title: Bluetooth batteries
content: >
  | Device | Battery | Last seen |
  |:--|--:|:--|
  {% for s in states.sensor | selectattr('attributes.last_seen', 'defined')
       | selectattr('attributes.source', 'defined') | sort(attribute='entity_id') %}
  | {{ device_attr(s.entity_id, 'name') or s.name }} | {{ s.state }} % | {{ (as_datetime(s.attributes.last_seen) | as_local).strftime('%d.%m. %H:%M') }} |
  {% endfor %}
```

## Development

```bash
pip install dbus-fast paho-mqtt pytest
pytest tests
```

The integration test starts a private D-Bus with a simulated BlueZ, a simulated
headset and a simulated BLE device (requires `dbus-daemon`).

## License

MIT
