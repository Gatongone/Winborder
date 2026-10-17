"""Measure the pointer fraction at which a pull-back exit actually fires.

Run with the target paired. The script drives a
programmatic mouse (relative input, which is what the hooks consume) to the
configured screen edge, pushes inward to arm the exit latch, then pulls back
until the mode changes. The host log reports the pointer fraction at exit, which
separates a threshold problem from the target placing its own cursor elsewhere.
"""

from __future__ import annotations

import ctypes
import os
import re
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from winborder import model, win32

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                      # noqa: BLE001
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_u = ctypes.WinDLL("user32", use_last_error=True)


class MI(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class UN(ctypes.Union):
    _fields_ = [("mi", MI)]


class INP(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", UN)]


def send_rel(dx: int, dy: int) -> None:
    """Relative mouse input; the Raw Input capture path consumes exactly this."""
    inp = INP()
    inp.type = 0
    inp.u.mi = MI(dx, dy, 0, 0x0001, 0, None)   # MOUSEEVENTF_MOVE
    _u.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INP))


def send_abs(x: int, y: int) -> None:
    left, top, right, bottom = win32.primary_screen_rect()
    sw, sh = max(1, right - left), max(1, bottom - top)
    inp = INP()
    inp.type = 0
    inp.u.mi = MI(int(x * 65535 / max(sw - 1, 1)), int(y * 65535 / max(sh - 1, 1)),
                  0, 0x0001 | 0x8000, 0, None)
    _u.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INP))


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--side", choices=[s.value for s in model.Side],
                    default=model.Side.BOTTOM.value,
                    help="must match the side the host is running with")
    ap.add_argument("--inward", type=int, default=600,
                    help="pixels to push inward before pulling back")
    ap.add_argument("--step", type=int, default=8)
    ap.add_argument("--start-offset", type=int, default=200,
                    help="pixels from the edge the cursor starts at")
    args = ap.parse_args()

    side = model.Side(args.side)
    # Unit steps along the axis that leaves the PC edge and returns to it.
    into = {
        model.Side.RIGHT: (1, 0), model.Side.LEFT: (-1, 0),
        model.Side.TOP: (0, -1), model.Side.BOTTOM: (0, 1),
    }[side]
    back = (-into[0], -into[1])

    win32.enable_dpi_awareness()
    win32.release_clip_global()

    print("=" * 72)
    print("Ensure the target is paired and connected. The script will:")
    print(f"  1. drive the cursor to the {side.value} screen edge to enter target mode")
    print("  2. push inward to arm the exit latch")
    print("  3. pull back until the mode changes")
    print("=" * 72)
    input("Press Enter to start ... ")

    log = os.path.join(tempfile.mkdtemp(prefix="winborder_exit_"), "host.log")
    with open(log, "wb") as handle:
        host = subprocess.Popen(
            [sys.executable, "-u", "-m", "winborder",
             "--side", side.value],
            stdout=handle, stderr=subprocess.STDOUT, cwd=ROOT)
        time.sleep(5.0)

        left, top, right, bottom = win32.primary_screen_rect()
        mid_x, mid_y = (left + right) // 2, (top + bottom) // 2
        # Approach the edge along the inward axis, then land exactly on it.
        offset = args.start_offset * into[0], args.start_offset * into[1]
        send_abs(mid_x - offset[0], mid_y - offset[1])
        time.sleep(0.4)
        edge_x = {model.Side.RIGHT: right - 1, model.Side.LEFT: left}.get(side, mid_x)
        edge_y = {model.Side.TOP: top, model.Side.BOTTOM: bottom - 1}.get(side, mid_y)
        send_abs(edge_x, edge_y)
        time.sleep(1.0)
        print("  entered target mode (expected)", flush=True)

        print(f"  pushing inward {args.inward}px to arm the latch ...", flush=True)
        moved = 0
        while moved < args.inward:
            send_rel(into[0] * args.step, into[1] * args.step)
            moved += args.step
            time.sleep(0.02)
        time.sleep(0.5)

        print("  pulling back until the mode changes ...", flush=True)
        pulled = 0
        deadline = time.monotonic() + 12.0
        while time.monotonic() < deadline:
            send_rel(back[0] * args.step, back[1] * args.step)
            pulled += args.step
            time.sleep(0.02)
        time.sleep(0.5)

        host.terminate()
        try:
            host.wait(timeout=8)
        except subprocess.TimeoutExpired:
            host.kill()
            host.wait(timeout=5)

    text = open(log, encoding="utf-8", errors="replace").read()
    clean = re.sub(r"\x1b\[[0-9;]*m", "", text)

    print("\n" + "=" * 72)
    print("Host log")
    print("=" * 72)
    for line in clean.splitlines():
        if any(k in line for k in ("enter target", "leave target", "handoff",
                                   "link", "error", "Error")):
            print("  " + line.strip())

    exits = re.findall(
        r"leave target mode \((\w+)\) at pointer ([\d.]+)%, ([\d.]+)% "
        r"\(travel (-?[\d.]+)%\)", clean)
    entries = re.findall(r"enter target mode, pointer at ([\d.]+)%, ([\d.]+)%", clean)

    print("\n" + "=" * 72)
    print("Measurement")
    print("=" * 72)
    print(f"  entries observed: {len(entries)}")
    for e in entries:
        print(f"    entered at pointer {e[0]}%, {e[1]}%")
    print(f"  exits observed: {len(exits)}")
    for reason, px, py, travel in exits:
        print(f"    exited ({reason}) at pointer {px}%, {py}% travel {travel}%")

    print()
    if not entries:
        print("  No entry recorded. The cursor may not have reached the edge, or")
        print("  the device is not answering. Check the log above.")
        return 1
    if not exits:
        print(f"  No exit recorded. Try a larger --inward than {args.inward}.")
        return 1

    travel = float(exits[0][3])
    print(f"  Exit at travel {travel}%, which is the count the return costs.")
    print("  The return ends with a burst towards the entry edge, so the visible")
    print("  cursor must be sitting on that edge as control comes back. If it is")
    print("  still inside the screen, the target moves its pointer very little per")
    print("  report; raise --pullback-distance so the pull does more of the trip.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
