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
pip install -r requirements.txt
```

## Usage

1. Run from the source tree with `python -m winborder`, or use a release build `winborder.exe`. The PC advertises as a Bluetooth LE HID device as soon as it starts, and keeps advertising until a target subscribes; the cursor does not cross until then.
2. Leave Winborder running, and read the Devices page: it says which name this PC is advertising as. That is the PC's Bluetooth name, not its computer name.
3. On the target, open its Bluetooth settings, find that name and select it.
4. Watch the Winborder log, if the connection was succeed, you might see following logs:
   * `the target is connected and reading the HID descriptor` means the target found the service.
   * `the target is connected and listening` means it has subscribed and the keyboard and mouse will cross.

Each time the app runs, it may use a new random address for broadcasting, in which case the pairing established before the restart will no longer match: Please forget the target device and then pair it again.

If everything setup, move your mouse to the bottom of the screen, and the cursor will pass through the screen onto your device.

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

```
python .github/tools/build.py
```

Writes `dist\Winborder.exe`; the first run sets `.venv` up by itself.

| Option | Description |
| --- | --- |
| `--console` | Keep a console window, for debugging. |
| `--onedir` | Write a folder instead of one file. |
| `--installer` | Also write the Setup.exe. Needs Inno Setup 6. |
| `--install-inno` | Install Inno Setup with winget first. |

## License

Winborder is released under the [MIT License](LICENSE). Copyright (c) 2026, Gatongone.
