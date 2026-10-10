# Bluetooth Battery

**English** | [Deutsch](DOCS.de.md)

Reads the battery level of Bluetooth devices directly on Home Assistant OS and
publishes it via MQTT. Each device gets a "Battery" sensor that keeps the last
known value (the `last_seen` attribute shows when it was measured).

## How it works

The add-on picks the right method for each device automatically:

* **Headphones and headsets** (devices with the hands-free profile HFP): the add-on
  acts as a "phone" for the control channel only, without audio. Headsets send
  their battery level over this channel, just like to a phone.
* **All other devices**, mainly BLE (mice, keyboards, controllers, trackers):
  the add-on connects briefly and BlueZ reads the standard Battery Service.

Afterwards the add-on disconnects so the device's connection slot stays free.
Devices that were already connected stay connected.

## Requirements

* Mosquitto broker add-on and MQTT integration
* The device must report its battery in a standard way: HFP (headsets with microphone) or the BLE Battery Service. Speakers without a microphone and devices that only show their battery in a vendor app usually report nothing.
* A device that is also connected to a phone or PC needs a free connection slot (multipoint for headphones). Many BLE mice and keyboards allow only one connection and can only be read while not in use.

## Recommended: a dedicated USB dongle

The add-on is most reliable with its own USB Bluetooth dongle:

1. Plug in the dongle, check its name under Settings > System > Hardware (usually `hci1`).
2. Under Settings > Devices & services > Bluetooth, **ignore** the new adapter so HA does not use it for BLE.
3. Set `adapter: hci1` in the add-on options.

Without a dongle `hci0` works too; the add-on and HA Bluetooth then share the adapter.

## Setup

1. Find the MAC addresses of your devices (vendor app, device label, or the add-on log while pairing).
2. Fill in the options:

   ```yaml
   adapter: hci1
   devices:
     - mac: "AA:BB:CC:DD:EE:01"
       name: My headphones
     - mac: "AA:BB:CC:DD:EE:02"
       name: My mouse
   ```

3. Put the devices into pairing mode and start the add-on. It discovers and pairs unpaired devices by itself.
4. The log shows e.g. `My headphones: 80 % (apple)`.

## Options

| Option | Meaning |
|:--|:--|
| `adapter` | Bluetooth adapter, e.g. `hci0` or `hci1` |
| `devices` | Devices with `mac` and `name` |
| `poll_interval_minutes` | Poll interval, default 15 |
| `hold_seconds` | How long to wait for a battery report per connection |
| `disconnect_after_read` | Disconnect after reading (recommended) |
| `log_level` | `debug` shows the full AT dialog, useful for troubleshooting |

## Known limitations

* If a device is off or all its connection slots are taken, the last value is kept.
* Some headphones announce "Connected" when connecting. Increase the interval in that case.
* If a device reports nothing: set `log_level: debug` and check the log.
