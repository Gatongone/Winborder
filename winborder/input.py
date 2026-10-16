"""Input capture: low level hooks plus Raw Input.

Hook callbacks run on the message loop thread and must return immediately.
Any delay makes the system silently remove the hook, which looks like the
keyboard randomly stopping. Callbacks therefore only enqueue events; all
processing happens on the service thread.

Mouse motion is read from Raw Input rather than from hook coordinates.
The hook reports absolute cursor positions, and in target mode the cursor is
confined to a one pixel edge, so Windows keeps applying position corrections.
Those corrections alternate with real motion and cancel it out, leaving only
noise. Raw Input reports the device's own relative motion and is unaffected
by confinement.
"""

from __future__ import annotations

import ctypes
import logging
import queue
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass

from . import keymap, win32
from .win32 import (
    BUTTON_BACK,
    BUTTON_FORWARD,
    BUTTON_LEFT,
    BUTTON_MIDDLE,
    BUTTON_RIGHT,
    HC_ACTION,
    HWND_MESSAGE,
    MOUSE_MOVE_ABSOLUTE,
    RID_INPUT,
    RIDEV_INPUTSINK,
    RIM_TYPEMOUSE,
    WH_KEYBOARD_LL,
    WH_MOUSE_LL,
    WM_INPUT,
    WM_KEYDOWN,
    WM_LBUTTONDOWN,
    WM_LBUTTONUP,
    WM_MBUTTONDOWN,
    WM_MBUTTONUP,
    WM_MOUSEHWHEEL,
    WM_MOUSEWHEEL,
    WM_QUIT,
    WM_RBUTTONDOWN,
    WM_RBUTTONUP,
    WM_SYSKEYDOWN,
    WM_XBUTTONDOWN,
    WM_XBUTTONUP,
    XBUTTON1,
)

log = logging.getLogger("winborder.input")

_user32 = win32._user32
_kernel32 = win32._kernel32

_LLKHF_EXTENDED = 0x01
_LLKHF_INJECTED = 0x10

PM_REMOVE = 0x0001
ERROR_CLASS_ALREADY_EXISTS = 1410


@dataclass(slots=True)
class KeyEvent:
    vk: int
    down: bool
    injected: bool = False


@dataclass(slots=True)
class MouseButtonEvent:
    mask: int
    down: bool


@dataclass(slots=True)
class MouseWheelEvent:
    delta: int
    horizontal: bool = False


class InputEngine:
    """Installs the hooks and Raw Input device, and exposes normalised events.

    Motion is exposed through :meth:`take_raw_delta` rather than as events,
    because the consumer needs the accumulated delta per step instead of one
    event per hardware report.
    """

    def __init__(self) -> None:
        self.events: queue.Queue[KeyEvent | MouseButtonEvent | MouseWheelEvent] = (
            queue.Queue(maxsize=8192)
        )
        self._suppress_keyboard = False
        self.suppress_mouse = False
        self.dropped_events = 0
        self.callback_errors = 0
        self.thread_error = False

        # Keys the OS has seen pressed, keys whose press was kept from the OS,
        # and keys the OS has pressed whose release was kept from it. Tracking
        # all three is what keeps the PC keyboard consistent across a handoff.
        self._pc_keys_down: set[int] = set()
        self._swallowed_down: set[int] = set()
        self._lost_releases: set[int] = set()

        self._running = threading.Event()
        self._ready = threading.Event()
        self._kbd_hook = None
        self._mouse_hook = None
        self._kbd_proc = win32.HOOKPROC(self._keyboard_cb)
        self._mouse_proc = win32.HOOKPROC(self._mouse_cb)
        self._thread_id: int | None = None
        self._clipped = False
        self._raw_window = None
        self._raw_wndproc = None
        self._raw_ready = False

        self.raw_dx = 0
        self.raw_dy = 0
        self.raw_messages = 0

    @property
    def suppress_keyboard(self) -> bool:
        """Whether the host is holding the keyboard for the target."""
        return self._suppress_keyboard

    @suppress_keyboard.setter
    def suppress_keyboard(self, value: bool) -> None:
        value = bool(value)
        if value == self._suppress_keyboard:
            return
        self._suppress_keyboard = value
        if not value:
            # The PC gets the keyboard back, so it must not inherit a key that
            # was still held when the target took over.
            self._release_lost_keys()

    # -- lifecycle --------------------------------------------------------

    def start(self) -> None:
        """Run the message loop on the calling thread. Blocks."""
        msg = wintypes.MSG()
        _user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE)

        self._thread_id = _kernel32.GetCurrentThreadId()
        module = _kernel32.GetModuleHandleW(None)
        self._kbd_hook = _user32.SetWindowsHookExW(
            WH_KEYBOARD_LL, self._kbd_proc, module, 0
        )
        if not self._kbd_hook:
            raise ctypes.WinError(ctypes.get_last_error())
        self._mouse_hook = _user32.SetWindowsHookExW(
            WH_MOUSE_LL, self._mouse_proc, module, 0
        )
        if not self._mouse_hook:
            _user32.UnhookWindowsHookEx(self._kbd_hook)
            self._kbd_hook = None
            raise ctypes.WinError(ctypes.get_last_error())

        self._install_raw_input()
        self._running.set()
        self._ready.set()
        log.info("hooks installed, raw_input=%s", self._raw_ready)

        try:
            while self._running.is_set():
                ret = _user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if ret in (0, -1):
                    break
                _user32.TranslateMessage(ctypes.byref(msg))
                _user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            self._uninstall()

    def start_background(self) -> threading.Thread:
        def runner() -> None:
            try:
                self.start()
            except Exception:
                log.exception("input thread terminated, hooks are gone")
                self.thread_error = True
                self._ready.set()

        thread = threading.Thread(target=runner, name="winborder-input", daemon=True)
        thread.start()
        if not self._ready.wait(5.0):
            raise RuntimeError("input hook installation timed out")
        if self.thread_error:
            raise OSError("input hook installation failed")
        return thread

    def stop(self) -> None:
        self._running.clear()
        if self._thread_id:
            _user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)

    def _uninstall(self) -> None:
        if self._kbd_hook:
            _user32.UnhookWindowsHookEx(self._kbd_hook)
            self._kbd_hook = None
        if self._mouse_hook:
            _user32.UnhookWindowsHookEx(self._mouse_hook)
            self._mouse_hook = None
        if self._raw_window:
            _user32.DestroyWindow(self._raw_window)
            self._raw_window = None
        log.info("hooks removed, dropped=%d", self.dropped_events)

    def __enter__(self) -> "InputEngine":
        self.start_background()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()

    # -- event queue ------------------------------------------------------

    def drain(self, limit: int = 512) -> list[KeyEvent | MouseButtonEvent | MouseWheelEvent]:
        out: list[KeyEvent | MouseButtonEvent | MouseWheelEvent] = []
        while len(out) < limit:
            try:
                out.append(self.events.get_nowait())
            except queue.Empty:
                break
        return out

    def _push(self, event: object) -> None:
        try:
            self.events.put_nowait(event)  # type: ignore[arg-type]
        except queue.Full:
            self.dropped_events += 1

    def take_raw_delta(self) -> tuple[int, int]:
        dx, dy = self.raw_dx, self.raw_dy
        self.raw_dx = 0
        self.raw_dy = 0
        return dx, dy

    # -- hook callbacks ---------------------------------------------------

    def _keyboard_cb(self, n_code: int, w_param: int, l_param: int) -> int:
        try:
            if n_code == HC_ACTION:
                info = ctypes.cast(
                    l_param, ctypes.POINTER(win32.KBDLLHOOKSTRUCT)
                ).contents
                down = w_param in (WM_KEYDOWN, WM_SYSKEYDOWN)
                vk = int(info.vkCode)
                swallowed = self._track_key(vk, down)
                self._push(KeyEvent(
                    vk=vk,
                    down=down,
                    injected=bool(info.flags & _LLKHF_INJECTED),
                ))
                if swallowed:
                    return 1
        except Exception:
            self.callback_errors += 1
            if self.callback_errors <= 3:
                log.exception("keyboard hook callback failed")
        return _user32.CallNextHookEx(None, n_code, w_param, l_param)

    def _track_key(self, vk: int, down: bool) -> bool:
        """Decide whether a key event must be kept from the OS, and record it.

        Swallowing one half of a keystroke is what corrupts the PC keyboard. A
        release for a key the OS never saw pressed must not be delivered, and a
        key the OS did see pressed must not be left down when control comes
        back, so its release is replayed later as a synthetic one. Either way
        the PC ends up with the same key state it would have had.
        """
        if down:
            if self.suppress_keyboard:
                self._swallowed_down.add(vk)
                return True
            self._pc_keys_down.add(vk)
            return False
        if vk in self._swallowed_down:
            self._swallowed_down.discard(vk)
            return True
        if self.suppress_keyboard:
            if self._pc_keys_down.discard(vk) is None:
                self._lost_releases.add(vk)
            return True
        self._pc_keys_down.discard(vk)
        return False

    def _release_lost_keys(self) -> None:
        """Hand back the keys whose release the target swallowed."""
        if not self._lost_releases:
            return
        released = sorted(self._lost_releases)
        for vk in released:
            win32.send_key_up(vk)
        log.debug("handed %d key(s) back to the PC: %s", len(released),
                  ", ".join(keymap.describe_vk(vk) for vk in released))
        self._lost_releases.clear()

    def _mouse_cb(self, n_code: int, w_param: int, l_param: int) -> int:
        try:
            if n_code == HC_ACTION:
                info = ctypes.cast(
                    l_param, ctypes.POINTER(win32.MSLLHOOKSTRUCT)
                ).contents
                swallow = self.suppress_mouse
                if w_param == WM_LBUTTONDOWN or w_param == WM_LBUTTONUP:
                    self._push(MouseButtonEvent(
                        BUTTON_LEFT, w_param == WM_LBUTTONDOWN))
                elif w_param == WM_RBUTTONDOWN or w_param == WM_RBUTTONUP:
                    self._push(MouseButtonEvent(
                        BUTTON_RIGHT, w_param == WM_RBUTTONDOWN))
                elif w_param == WM_MBUTTONDOWN or w_param == WM_MBUTTONUP:
                    self._push(MouseButtonEvent(
                        BUTTON_MIDDLE, w_param == WM_MBUTTONDOWN))
                elif w_param == WM_XBUTTONDOWN or w_param == WM_XBUTTONUP:
                    which = (info.mouseData >> 16) & 0xFFFF
                    mask = BUTTON_BACK if which == XBUTTON1 else BUTTON_FORWARD
                    self._push(MouseButtonEvent(
                        mask, w_param == WM_XBUTTONDOWN))
                elif w_param == WM_MOUSEWHEEL:
                    delta = ctypes.c_short((info.mouseData >> 16) & 0xFFFF).value
                    self._push(MouseWheelEvent(delta, False))
                elif w_param == WM_MOUSEHWHEEL:
                    delta = ctypes.c_short((info.mouseData >> 16) & 0xFFFF).value
                    self._push(MouseWheelEvent(delta, True))
                if swallow:
                    return 1
        except Exception:
            self.callback_errors += 1
            if self.callback_errors <= 3:
                log.exception("mouse hook callback failed")
        return _user32.CallNextHookEx(None, n_code, w_param, l_param)

    # -- raw input --------------------------------------------------------

    def _install_raw_input(self) -> None:
        """Register the mouse for Raw Input.

        RIDEV_INPUTSINK requires a real window handle; passing NULL fails with
        WinError 87. Registering without the flag succeeds but delivers nothing,
        because input then only goes to the foreground thread's queue.

        The correct combination is RIDEV_INPUTSINK plus a message-only window,
        which is invisible and absent from the taskbar.
        """
        try:
            module = _kernel32.GetModuleHandleW(None)
            self._raw_wndproc = win32.WNDPROC(self._raw_wnd_proc)
            class_name = f"WinborderRawInput{_kernel32.GetCurrentThreadId()}"

            wc = win32.WNDCLASSEXW()
            wc.cbSize = ctypes.sizeof(win32.WNDCLASSEXW)
            wc.lpfnWndProc = self._raw_wndproc
            wc.hInstance = module
            wc.lpszClassName = class_name
            if not _user32.RegisterClassExW(ctypes.byref(wc)):
                err = ctypes.get_last_error()
                if err != ERROR_CLASS_ALREADY_EXISTS:
                    log.warning("RegisterClassExW failed: %s", ctypes.WinError(err))

            hwnd = _user32.CreateWindowExW(
                0, class_name, "WinborderRawInput", 0, 0, 0, 0, 0,
                wintypes.HWND(HWND_MESSAGE), None, module, None,
            )
            if not hwnd:
                log.warning("message-only window creation failed: %s",
                            ctypes.WinError(ctypes.get_last_error()))
                return
            self._raw_window = hwnd
        except Exception:
            log.exception("raw input window setup failed")
            return

        device = win32.RAWINPUTDEVICE()
        device.usUsagePage = 0x01
        device.usUsage = 0x02
        device.dwFlags = RIDEV_INPUTSINK
        device.hwndTarget = hwnd
        try:
            ok = _user32.RegisterRawInputDevices(
                ctypes.byref(device), 1, ctypes.sizeof(win32.RAWINPUTDEVICE)
            )
        except Exception:
            log.exception("RegisterRawInputDevices raised")
            return
        if ok:
            self._raw_ready = True
        else:
            log.warning(
                "RegisterRawInputDevices failed: %s; motion falls back to "
                "confinement-affected coordinates", 
                ctypes.WinError(ctypes.get_last_error()),
            )

    def _raw_wnd_proc(self, hwnd, msg, w_param, l_param):
        try:
            if msg == WM_INPUT:
                self._handle_raw_input(l_param)
                return 0
        except Exception:
            self.callback_errors += 1
            if self.callback_errors <= 3:
                log.exception("raw input window procedure failed")
        return _user32.DefWindowProcW(hwnd, msg, w_param, l_param)

    def _handle_raw_input(self, l_param: int) -> None:
        try:
            size = wintypes.UINT(0)
            header_size = ctypes.sizeof(win32.RAWINPUTHEADER)
            if _user32.GetRawInputData(
                wintypes.HANDLE(l_param), RID_INPUT, None,
                ctypes.byref(size), header_size,
            ) != 0:
                return
            if size.value == 0 or size.value > 256:
                return
            buffer = ctypes.create_string_buffer(size.value)
            got = _user32.GetRawInputData(
                wintypes.HANDLE(l_param), RID_INPUT, buffer,
                ctypes.byref(size), header_size,
            )
            if got == 0 or got == wintypes.UINT(-1).value:
                return
            header = ctypes.cast(buffer, ctypes.POINTER(win32.RAWINPUTHEADER)).contents
            if header.dwType != RIM_TYPEMOUSE:
                return
            mouse = ctypes.cast(
                ctypes.byref(buffer, header_size), ctypes.POINTER(win32.RAWMOUSE)
            ).contents
            if mouse.usFlags & MOUSE_MOVE_ABSOLUTE:
                return
            self.raw_messages += 1
            self.raw_dx += mouse.lLastX
            self.raw_dy += mouse.lLastY
        except Exception:
            self.callback_errors += 1
            if self.callback_errors <= 3:
                log.exception("raw input decoding failed")

    # -- cursor confinement ----------------------------------------------

    def clip_to_edge(self, side: str, x: int | None = None,
                     y: int | None = None) -> None:
        """Confine the cursor to a one pixel band along the given edge."""
        left, top, right, bottom = win32.primary_screen_rect()
        if side == "left":
            rect = win32.RECT(left, top, left + 1, bottom)
        elif side == "right":
            rect = win32.RECT(right - 1, top, right, bottom)
        elif side == "top":
            rect = win32.RECT(left, top, right, top + 1)
        elif side == "bottom":
            rect = win32.RECT(left, bottom - 1, right, bottom)
        else:
            raise ValueError(f"unknown side: {side}")
        if not _user32.ClipCursor(ctypes.byref(rect)):
            log.warning("ClipCursor failed: %s",
                        ctypes.WinError(ctypes.get_last_error()))
            return
        self._clipped = True
        win32.ClipGuard.instance().acquire(side=side)
        if x is None or y is None:
            x, y = win32.get_cursor_pos()
        win32.set_cursor_pos(
            min(max(x, left), right - 1),
            min(max(y, top), bottom - 1),
        )

    def release_clip(self) -> None:
        if self._clipped:
            win32.ClipGuard.instance().release()
            self._clipped = False

    @property
    def clipped(self) -> bool:
        return self._clipped
