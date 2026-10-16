# Winborder

Share a PC keyboard and mouse with another device over Bluetooth LE HID.

Move the cursor to the screen edge and the same physical keyboard and mouse drive the target device. No software is installed on the target and no jailbreak or root is required: it sees a standard Bluetooth keyboard and mouse.

```
[keyboard/mouse] --USB--> [Windows host] --USB serial--> [ESP32] --BLE HID--> [target]
```

The host is Windows only. The target may be any device that accepts a Bluetooth LE HID peripheral.

## Requirements

| Item | Requirement |
| --- | --- |
| Host OS | Windows 10 1703 or newer (x64). Tested on Windows 11. |
| Python | 3.10 or newer. Tested on 3.14. |
| Arduino | `arduino-cli` 1.5 or the Arduino IDE 2.x |
| Target | A device that acts as a BLE central accepting HID peripherals. Verified: iPadOS 13.4 or newer. |

The host must run DPI aware. The program sets per-monitor v2 awareness itself at startup.

Any ESP32 variant with Bluetooth LE and native USB serial. Verified configuration:

| Board | FQBN | Notes |
| --- | --- | --- |
| ESP32-S3 Dev Module | `esp32:esp32:esp32s3` | Reference target. |
| ESP32-C3 Dev Module | `esp32:esp32:esp32c3` | Single USB port, no separate bridge. |
| ESP32-C6 Dev Module | `esp32:esp32:esp32c6` | As above. |
| ESP32 Dev Module | `esp32:esp32:esp32` | Classic ESP32, BLE only. |

Required board options for ESP32 (ESP32-S3 for example):

```
FlashSize=16M,PSRAM=disabled,CDCOnBoot=cdc,USBMode=hwcdc
```

`PSRAM=disabled` is deliberate on boards with octal PSRAM; enabling it causes boot loops on some modules.

## Dependencies

Host, installed with pip:

```
pip install pyserial
```

`pyserial` is the only runtime dependency. Everything else uses the Python standard library and `ctypes`.

Firmware, installed through the Arduino library manager:

| Library | Version |
| --- | --- |
| NimBLE-Arduino (by h2zero) | 2.5.1 or newer in the 2.x line |

Add the ESP32 board support URL in the Arduino board manager preferences:

```
https://espressif.github.io/arduino-esp32/package_esp32_index.json
```

## Firmware

Install the board support and the library, then apply the patch the firmware needs:

```
arduino-cli core install esp32:esp32
arduino-cli lib install NimBLE-Arduino
patch -p1 -d <libraries>/NimBLE-Arduino < firmware/patches/nimble-remove-service-changed.patch
```

> [!NOTE]
> The patch matters. NimBLE 2.5.1 registers the Service Changed characteristic unconditionally, while the Database Hash that BLE 5.1 pairs with it stays behind a build option this board does not enable. A central reads that attribute table as invalid and drops the HID service from service discovery without reporting anything, so the board pairs and then does nothing. The patch wraps that one characteristic in `#if 0`, and the file explains the reasoning, the symptom and what it costs.

Then build and flash:

```
arduino-cli compile --fqbn "esp32:esp32:esp32s3:FlashSize=16M,PSRAM=disabled,CDCOnBoot=cdc,USBMode=hwcdc" firmware/ble_bridge
arduino-cli upload  --fqbn "esp32:esp32:esp32s3:FlashSize=16M,PSRAM=disabled,CDCOnBoot=cdc,USBMode=hwcdc" --port COM9 firmware/ble_bridge
```

There is one firmware build. The board reports its state over the serial link, and the host shows those lines in its window.

A release carries the same firmware as one image, which needs no toolchain:

```
python -m esptool --chip esp32s3 write-flash --port COM9 0x0 Winborder-0.1.0-firmware-esp32s3.bin
```

The firmware has a version of its own, reported to the host on connect; it does not follow the host version.

## Usages

Open the Bluetooth settings on the target and select `Winborder`. The first connection creates the bond; later connections reuse it.

Then open `winborder.exe`, and setup COM port. Boards with a separate USB-UART bridge expose two ports. The firmware is flashed through the bridge port, and the runtime protocol runs on the native USB port, which enumerates second and has the higher COM number.

If it works, move your mouse to the bottom of the screen, and the cursor will pass through the screen onto your device.

### Gestures

| Gesture | Action |
| --- | --- |
| Move the cursor to the screen edge | Enter target mode |
| F1 | Release control immediately |
| F2 | Enable or disable edge crossing |
| Double Ctrl | Return to the PC |
| Ctrl + C | Quit |

### Settings file

Everything the host does without a command line flag comes from `winborder.json` in the working directory. Write one out and edit it:

```
python -m winborder --write-config
```

```json
{
  "port": "COM10",
  "side": "bottom",
  "language": "en",
  "pullback_distance": 300,
  "panic_keys": ["F1"],
  "toggle_edge_keys": ["F2"],
  "remap": {"CapsLock": "Escape"}
}
```

Every setting is optional and the rest keep their defaults. The names are the options below written with underscores, and `--write-config` writes the full set with the value each one defaults to. Keys are written by name (`F1`, `LeftCtrl`, `CapsLock`), and a number is accepted as a raw virtual key code. `language` is one of `en`, `ru`, `zh`, `ja`, `ko` and is `en` when it is not there at all.

The order of precedence is built in defaults, then the settings file, then the command line. `--config PATH` reads a different file; naming one that does not exist is an error rather than a silent fall back to the defaults.

`remap` changes what the target receives without changing the PC: `{"CapsLock": "Escape"}` makes CapsLock send Escape to the target. A remap can target a modifier, so `{"CapsLock": "LeftCtrl"}` works as well.

### CLI

| Option | Description |
| --- | --- |
| `--config PATH` | Settings file, default `winborder.json`. |
| `--write-config [PATH]` | Write every setting at its default value, then exit. |
| `--port PORT` | Serial port. Detected automatically when omitted. |
| `--baudrate N` | Serial baud rate, default 115200. |
| `--side left\|right\|top\|bottom` | Side of the PC the target device sits on, default `bottom`. The pointer enters at the target edge facing the PC. |
| `--sensitivity F` | Pointer gain, default 1.0. |
| `--accel F` | Speed-proportional gain, 0 to 1, default 0. |
| `--invert-wheel` / `--no-invert-wheel` | Vertical scroll direction, inverted by default. |
| `--pullback-distance N` | Motion towards the PC needed to return, default 300. |
| `--no-pullback-exit` | Disable returning by pulling towards the PC. |
| `--no-edge` | Disable edge crossing; arm it later with F2. |
| `--list-ports` | List serial ports and exit. |
| `--probe` | Print the port the bridge answers on and exit. |

## Releases

Publishing a release is the whole procedure. The workflow in `.github/workflows/release.yml` runs on `release: published`, and by the time it is done the release carries:

| Asset | What it is |
| --- | --- |
| `Winborder-<version>-Setup.exe` | The installer. |
| `Winborder.exe` | The same program as one file, for anyone who would rather not install it. |
| `Winborder-<version>-firmware-esp32s3.bin` | The firmware as one image, written at offset 0. |

## License

Winborder is released under the [MIT License](LICENSE). Copyright (c) 2026, Gatongone.
