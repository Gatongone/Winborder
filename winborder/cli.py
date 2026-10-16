"""Command line interface."""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading
import time
from pathlib import Path

from . import config as config_mod
from . import i18n, ipc, link as link_mod, logbuffer, model, trace, win32

log = logging.getLogger("winborder")

BANNER = "Winborder — share the PC keyboard and mouse with another device over BLE HID"

EXIT_KEYS = "F1"
TOGGLE_KEYS = "F2"

# The trace has to be fast enough to follow the pointer during a return, and the
# idle line only reports link health, so it can stay slow.
TRACE_INTERVAL_S = 0.2
STATUS_INTERVAL_S = 1.0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="winborder",
        description=BANNER,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "gestures:\n"
            f"  {EXIT_KEYS:<14}release control immediately\n"
            f"  {TOGGLE_KEYS:<14}toggle edge crossing\n"
            "  double Ctrl   return to the PC\n"
            "  Ctrl+C        quit\n"
        ),
    )
    parser.add_argument("--config", metavar="PATH",
                        default=config_mod.default_path(),
                        help="settings file, default " + config_mod.DEFAULT_FILENAME)
    parser.add_argument("--write-config", nargs="?", const=config_mod.default_path(),
                        metavar="PATH",
                        help="write every setting at its default value, then exit")
    parser.add_argument("--port", help="serial port of the bridge device")
    parser.add_argument("--baudrate", type=int,
                        help=f"serial baud rate, default {ipc.DEFAULT_BAUDRATE}")
    parser.add_argument("--side", choices=[s.value for s in model.Side],
                        help="which side of the PC the target device sits on")
    parser.add_argument("--sensitivity", type=float,
                        help="pointer gain; lower moves the target pointer slower")
    parser.add_argument("--accel", type=float,
                        help="extra gain proportional to speed, 0 to 1")
    parser.add_argument("--invert-wheel", action="store_true", default=None,
                        help="invert vertical scrolling")
    parser.add_argument("--no-invert-wheel", action="store_true",
                        help="keep the original vertical scroll direction")
    parser.add_argument("--pullback-distance", type=int,
                        help="pixels the pointer must be pulled towards the PC before "
                             "returning. Raise it if a return arrives while the target "
                             "pointer still looks inside its screen")
    parser.add_argument("--no-pullback-exit", action="store_true",
                        help="disable returning by pulling the pointer towards the PC")
    parser.add_argument("--no-edge", action="store_true",
                        help="disable edge crossing, use F2 to arm it later")
    parser.add_argument("--list-ports", action="store_true",
                        help="list serial ports and exit")
    parser.add_argument("--probe", action="store_true",
                        help="find the port the bridge answers on, then exit")
    return parser


def configure_logging() -> None:
    """Log everything: the window shows the same lines as the console."""
    logging.basicConfig(level=logging.DEBUG, format=logbuffer.FORMAT,
                        datefmt=logbuffer.DATE_FORMAT)


def resolve_port(requested: str | None) -> str | None:
    ports = link_mod.list_serial_ports()
    if requested:
        if requested not in ports:
            log.warning("port %s is not present; available: %s",
                        requested, ", ".join(ports) or "none")
        return requested
    guess = link_mod.suggest_port(ports)
    if guess:
        log.info("using detected port %s", guess)
    return guess


def find_working_port(baudrate: int) -> str | None:
    for port in sorted(link_mod.list_serial_ports(),
                       key=link_mod.port_index, reverse=True):
        if link_mod.probe_port(port, baudrate):
            return port
    return None


def load_settings(args: argparse.Namespace) -> dict[str, object]:
    """Read the settings file, which is optional."""
    if not Path(args.config).exists():
        if args.config != config_mod.default_path():
            raise config_mod.ConfigError(
                i18n.t("settings file not found: {path}").format(path=args.config))
        return {}
    settings = config_mod.read(args.config)
    log.info("settings from %s", args.config)
    return settings


def make_config(settings: dict[str, object],
                args: argparse.Namespace) -> model.Config:
    """Settings from the file, overridden by whatever the command line set."""
    overrides: dict[str, object] = {}
    if args.side is not None:
        overrides["side"] = args.side
    if args.sensitivity is not None:
        overrides["sensitivity"] = args.sensitivity
    if args.accel is not None:
        overrides["accel"] = args.accel
    if args.invert_wheel:
        overrides["invert_wheel_v"] = True
    if args.no_invert_wheel:
        overrides["invert_wheel_v"] = False
    if args.pullback_distance is not None:
        overrides["pullback_distance"] = args.pullback_distance
    if args.no_pullback_exit:
        overrides["pullback_exit"] = False
    if args.no_edge:
        overrides["edge_trigger_enabled"] = False
    return config_mod.build({**settings, **overrides})


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging()

    if args.write_config:
        try:
            written = config_mod.write_default(args.write_config)
        except OSError as exc:
            log.error("cannot write %s: %s", args.write_config, exc)
            return 2
        print(f"wrote {written}")
        return 0

    try:
        settings = load_settings(args)
        bridge_config = make_config(settings, args)
    except config_mod.ConfigError as exc:
        log.error("%s", exc)
        return 2
    link = config_mod.link_settings(settings)
    port_arg = args.port or str(link.get("port") or "") or None
    baudrate = args.baudrate or int(link.get("baudrate") or ipc.DEFAULT_BAUDRATE)

    if args.list_ports:
        ports = link_mod.list_serial_ports()
        print("\n".join(ports) if ports else "no serial ports found")
        return 0

    win32.enable_dpi_awareness()
    if not win32.install_clip_guard():
        log.warning("job object guard unavailable: a force kill may leave the "
                    "cursor confined until %s is pressed", EXIT_KEYS)
    win32.ClipGuard.install_atexit()
    win32.release_clip_global()

    if args.probe:
        port = find_working_port(baudrate)
        print(port if port else "no Winborder device found")
        return 0 if port else 1

    port = resolve_port(port_arg)
    if not port:
        log.error("no serial port available; connect the board or pass --port")
        return 2

    from .service import Service

    service = Service(port, config=bridge_config, baudrate=baudrate)
    # The window shows every setting, so it needs all of them, not just the
    # ones this file happened to contain.
    service_settings = config_mod.complete(settings)
    service_settings["port"] = port_arg or service_settings.get("port", "")
    service_settings["baudrate"] = baudrate

    def on_signal(signum, frame) -> None:  # noqa: ARG001
        service.request_stop()

    signal.signal(signal.SIGINT, on_signal)
    try:
        signal.signal(signal.SIGTERM, on_signal)
    except (AttributeError, ValueError):
        pass

    if _start_window(service, service_settings, args.config):
        return 0

    log.info("%s", BANNER)
    _start_status_printer(service)
    try:
        service.run()
    except KeyboardInterrupt:
        service.request_stop()
        service.shutdown()
    return 0


def _start_window(service: Service, settings: dict[str, object],
                  config_path: str) -> bool:
    """Run the settings window and the tray icon, if this Python has tkinter."""
    try:
        from .ui import SettingsWindow
    except ImportError as exc:
        log.warning("no settings window (%s); running in the console", exc)
        return False
    window = SettingsWindow(service, settings, config_path)
    window.run()
    return True


def _start_status_printer(service) -> None:
    """Print the link status line, and a pointer trace while the target is active.

    The trace carries the values the return rule decides on: the PC cursor, the
    tracked pointer and the travel since the target was entered. Those numbers are
    what a return has to be explained from, since the reports the host sends are
    relative and the target may place its own pointer anywhere.
    """

    def loop() -> None:
        formatter = trace.StatusFormatter()
        while True:
            target = service.router.mode is model.Mode.TARGET
            time.sleep(TRACE_INTERVAL_S if target else STATUS_INTERVAL_S)
            try:
                state = service.status()
            except Exception:  # noqa: BLE001 - diagnostics must never crash the run
                return
            line = formatter.line(state)
            if line is not None:
                print(line, file=sys.stderr, flush=True)

    thread = threading.Thread(target=loop, daemon=True, name="winborder-status")
    thread.start()


if __name__ == "__main__":
    raise SystemExit(main())
