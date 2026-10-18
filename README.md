# Winborder

Share a PC keyboard and mouse with another device over Bluetooth LE HID.

Move the cursor to the screen edge and the same physical keyboard and mouse drive the target device. No software is installed on the target and no jailbreak or root is required: it sees a standard Bluetooth keyboard and mouse.

```
[keyboard/mouse] --USB--> [Windows host] --BLE-HID--> [target]
```

The host is Windows only. The target may be any device that accepts a Bluetooth LE HID peripheral.

## Features

1. Allowing you to control up to target devices (iPad, iPhone, Android etc.) from a single mouse and keyboard.
2. Send clipboard content to target devices (english only).
3. Convenient visual UI tools.
4. Remap key to target devices.

## Install

Get executable file or installer from [Releases Page](https://github.com/Gatongone/Winborder/releases).

## Requirements

| Item | Requirement |
| --- | --- |
| Host OS | Windows 10 1703 or newer (x64). Tested on Windows 11. |
| Bluetooth | An adapter that supports the Bluetooth LE peripheral role.|
| Target | A device that acts as a BLE central accepting HID peripherals.|

Everything except the Bluetooth bindings uses the Python standard library and `ctypes`:

```
pip install winrt-runtime winrt-Windows.Devices.Bluetooth \
            winrt-Windows.Devices.Bluetooth.Advertisement \
            winrt-Windows.Devices.Bluetooth.GenericAttributeProfile \
            winrt-Windows.Storage.Streams winrt-Windows.Foundation
```

## Usage

Open the Bluetooth settings on the target and select your host Bluetooth adapter name. Each run advertises under a new random address, so a bond made before a restart no longer matches: forget the device on the target and pair it again.

Then run from the source tree with `python -m winborder`, or use a release build `winborder.exe`. The cursor stops crossing until the target has connected, so pair it first.

If it works, move your mouse to the bottom of the screen, and the cursor will pass through the screen onto your device.

### Settings

Everything the host does without a command line flag comes from `winborder.json` beside the executable, or in the working directory when run from the source tree. Write one out and edit it:

```
python -m winborder --write-config
```

### CLI

| Option | Description |
| --- | --- |
| `--config <path>` | Settings file, default `winborder.json`. |
| `--write-config <path>` | Write every setting at its default value, then exit. |
| `--side <left\|right\|top\|bottom>` | Side of the PC the target device sits on, default `bottom`. The pointer enters at the target edge facing the PC. |
| `--sensitivity <F>` | Pointer gain, default 1.0. |
| `--accel <F>` | Speed-proportional gain, 0 to 1, default 0. |
| `--invert-wheel` / `--no-invert-wheel` | Vertical scroll direction, inverted by default. |
| `--pullback-distance <N>` | Motion towards the PC needed to return, default 300. |
| `--no-pullback-exit` | Disable returning by pulling towards the PC. |
| `--no-edge` | Disable edge crossing; arm it later with F2. |

## Build

The two scripts in `.github/tools` are what the release workflow runs. They need the runtime packages above plus PyInstaller:

```
pip install pyinstaller
python .github/tools/build_exe.py
python .github/tools/build_installer.py
```

## License

Winborder is released under the [MIT License](LICENSE). Copyright (c) 2026, Gatongone.
