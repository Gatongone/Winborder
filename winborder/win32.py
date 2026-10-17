"""Win32 declarations, screen geometry and cursor confinement.

Every API uses explicit restype/argtypes. Without them ctypes returns handles
as 32-bit ints and truncates 64-bit values, which makes SetWindowsHookExW fail
with WinError 126.
"""

from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes

log = logging.getLogger("winborder.win32")

WH_KEYBOARD_LL = 13
WH_MOUSE_LL = 14
HC_ACTION = 0

WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105

WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_MBUTTONDOWN = 0x0207
WM_MBUTTONUP = 0x0208
WM_MOUSEWHEEL = 0x020A
WM_XBUTTONDOWN = 0x020B
WM_XBUTTONUP = 0x020C
WM_MOUSEHWHEEL = 0x020E

WM_INPUT = 0x00FF
WM_QUIT = 0x0012

PM_REMOVE = 0x0001

XBUTTON1 = 0x0001
XBUTTON2 = 0x0002

BUTTON_LEFT = 0x01
BUTTON_RIGHT = 0x02
BUTTON_MIDDLE = 0x04
BUTTON_BACK = 0x08
BUTTON_FORWARD = 0x10

_LLKHF_EXTENDED = 0x01
_LLKHF_INJECTED = 0x10

RID_INPUT = 0x10000003
RIDEV_INPUTSINK = 0x00000100
RIM_TYPEMOUSE = 0
MOUSE_MOVE_ABSOLUTE = 0x01

HWND_MESSAGE = -3
#: ShowWindow command: un-minimise and show. A window hidden to the notification
#: area has to be restored before it can be the foreground window.
SW_RESTORE = 9
_DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)


# Callback prototypes. They must exist before the structures that embed them,
# otherwise the function pointer field degrades to an untyped void pointer and
# a wrong arity silently corrupts the stack at callback time.
HOOKPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
)
WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
)


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
        ("hIconSm", wintypes.HICON),
    ]


class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [
        ("usUsagePage", wintypes.USHORT),
        ("usUsage", wintypes.USHORT),
        ("dwFlags", wintypes.DWORD),
        ("hwndTarget", wintypes.HWND),
    ]


class RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [
        ("dwType", wintypes.DWORD),
        ("dwSize", wintypes.DWORD),
        ("hDevice", wintypes.HANDLE),
        ("wParam", wintypes.WPARAM),
    ]


class RAWMOUSE_BUTTONS(ctypes.Union):
    _fields_ = [
        ("ulButtons", wintypes.ULONG),
        ("usButtonFlags", wintypes.USHORT),
        ("usButtonData", wintypes.USHORT),
    ]


class RAWMOUSE(ctypes.Structure):
    """Mouse payload of RAWINPUT.

    No member is 8 bytes wide, so the structure only requires 4-byte alignment
    and needs no manual padding. Inserting padding shifts lLastX/lLastY and
    yields zero or garbage deltas.
    """

    _fields_ = [
        ("usFlags", wintypes.USHORT),
        ("_buttons", RAWMOUSE_BUTTONS),
        ("ulRawButtons", wintypes.ULONG),
        ("lLastX", wintypes.LONG),
        ("lLastY", wintypes.LONG),
        ("ulExtraInformation", wintypes.ULONG),
    ]


_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

_kernel32.GetModuleHandleW.restype = wintypes.HMODULE
_kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
_kernel32.GetCurrentThreadId.restype = wintypes.DWORD
_kernel32.GetCurrentThreadId.argtypes = []

_user32.SetWindowsHookExW.restype = wintypes.HHOOK
_user32.SetWindowsHookExW.argtypes = [
    ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD
]
_user32.CallNextHookEx.restype = ctypes.c_ssize_t
_user32.CallNextHookEx.argtypes = [
    wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
]
_user32.UnhookWindowsHookEx.restype = wintypes.BOOL
_user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]

_user32.RegisterRawInputDevices.restype = wintypes.BOOL
_user32.RegisterRawInputDevices.argtypes = [
    ctypes.c_void_p, wintypes.UINT, wintypes.UINT
]
_user32.GetRawInputData.restype = wintypes.UINT
_user32.GetRawInputData.argtypes = [
    wintypes.HANDLE, wintypes.UINT, ctypes.c_void_p,
    ctypes.POINTER(wintypes.UINT), wintypes.UINT,
]
_user32.DefWindowProcW.restype = ctypes.c_ssize_t
_user32.DefWindowProcW.argtypes = [
    wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
]
_user32.RegisterClassExW.restype = wintypes.ATOM
_user32.RegisterClassExW.argtypes = [ctypes.c_void_p]
_user32.CreateWindowExW.restype = wintypes.HWND
_user32.CreateWindowExW.argtypes = [
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p,
]
_user32.DestroyWindow.restype = wintypes.BOOL
_user32.DestroyWindow.argtypes = [wintypes.HWND]

_user32.GetCursorPos.restype = wintypes.BOOL
_user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
_user32.SetCursorPos.restype = wintypes.BOOL
_user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
_user32.ClipCursor.restype = wintypes.BOOL
_user32.ClipCursor.argtypes = [ctypes.POINTER(RECT)]
_user32.GetClipCursor.restype = wintypes.BOOL
_user32.GetClipCursor.argtypes = [ctypes.POINTER(RECT)]
_user32.GetSystemMetrics.restype = ctypes.c_int
_user32.GetSystemMetrics.argtypes = [ctypes.c_int]
_user32.GetAsyncKeyState.restype = ctypes.c_short
_user32.GetAsyncKeyState.argtypes = [ctypes.c_int]

_user32.GetMessageW.restype = ctypes.c_int
_user32.GetMessageW.argtypes = [
    ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT
]
_user32.PeekMessageW.restype = wintypes.BOOL
_user32.PeekMessageW.argtypes = [
    ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT,
    wintypes.UINT,
]
_user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
_user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
_user32.PostThreadMessageW.restype = wintypes.BOOL
_user32.PostThreadMessageW.argtypes = [
    wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
]


def enable_dpi_awareness() -> str:
    """Make the process DPI aware so the hook and screen metrics agree.

    A DPI-unaware process receives physical coordinates from the low level
    mouse hook while GetSystemMetrics returns virtualised logical dimensions.
    Edge detection then triggers near the middle of the screen instead of at
    the border.

    Must run before any window is created.
    """
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    try:
        user32.SetProcessDpiAwarenessContext.restype = wintypes.BOOL
        user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        if user32.SetProcessDpiAwarenessContext(
            _DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
        ):
            return "per-monitor v2"
    except (AttributeError, OSError):
        pass
    try:
        shcore = ctypes.WinDLL("shcore", use_last_error=True)
        shcore.SetProcessDpiAwareness.argtypes = [ctypes.c_int]
        if shcore.SetProcessDpiAwareness(2) == 0:
            return "per-monitor"
    except (AttributeError, OSError):
        pass
    try:
        if user32.SetProcessDPIAware():
            return "system"
    except (AttributeError, OSError):
        pass
    return "unavailable"


BLUETOOTH_MAX_NAME_SIZE = 248


class _BluetoothFindRadioParams(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD)]


class _BluetoothRadioInfo(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("address", ctypes.c_ulonglong),
        ("szName", ctypes.c_wchar * BLUETOOTH_MAX_NAME_SIZE),
        ("ulClassofDevice", ctypes.c_ulong),
        ("lmpSubversion", ctypes.c_ushort),
        ("manufacturer", ctypes.c_ushort),
    ]


def bluetooth_name() -> str:
    """The name this PC's own Bluetooth radio advertises, or "" if unknown.

    This is the name a target shows in its list, and it is not the computer name:
    Windows keeps a separate Bluetooth name, so a PC that was renamed can go on
    advertising the old one, and a name set by hand has nothing to do with the
    hostname at all. Guessing it from the hostname is how the wrong name ends up
    in the instructions.

    There is no WinRT call for it; ``BluetoothGetRadioInfo`` is the one that
    reports it, and it needs no elevation.
    """
    try:
        bthprops = ctypes.WinDLL("bthprops.cpl")
        find = bthprops.BluetoothFindFirstRadio
        find.restype = wintypes.HANDLE
        find.argtypes = [ctypes.POINTER(_BluetoothFindRadioParams),
                         ctypes.POINTER(wintypes.HANDLE)]
        get_info = bthprops.BluetoothGetRadioInfo
        get_info.restype = wintypes.DWORD
        get_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(_BluetoothRadioInfo)]
        close = bthprops.BluetoothFindRadioClose
        close.restype = wintypes.BOOL
        close.argtypes = [wintypes.HANDLE]
    except (AttributeError, OSError):
        log.debug("no Bluetooth radio API on this system", exc_info=True)
        return ""

    params = _BluetoothFindRadioParams(
        dwSize=ctypes.sizeof(_BluetoothFindRadioParams))
    radio = wintypes.HANDLE()
    finder = find(ctypes.byref(params), ctypes.byref(radio))
    if not finder:
        log.debug("no Bluetooth radio to ask for a name")
        return ""
    try:
        info = _BluetoothRadioInfo()
        info.dwSize = ctypes.sizeof(_BluetoothRadioInfo)
        if get_info(radio, ctypes.byref(info)) != 0:
            log.debug("BluetoothGetRadioInfo refused the request")
            return ""
        return info.szName
    finally:
        close(finder)


def focus_window(title: str) -> bool:
    """Bring a window of this session to the front, restoring it if it is hidden.

    The windows are enumerated rather than looked up by title: the title is read
    for each one, so a second copy of the host finds the first by what it says
    rather than by guessing at a class name. A window hidden to the notification
    area still exists and is found this way, which is the case that matters --
    starting the program again is how a user with no visible window asks for it.

    Returns False when no window carries the title.
    """
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.EnumWindows.argtypes = [ctypes.c_void_p, wintypes.LPARAM]
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]

    found: list[int] = []

    def visit(handle, _param) -> bool:
        length = user32.GetWindowTextLengthW(handle)
        if length:
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(handle, buffer, length + 1)
            if buffer.value == title:
                found.append(handle)
                return False               # the first one will do
        return True

    callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)(visit)
    user32.EnumWindows(ctypes.cast(callback, ctypes.c_void_p), 0)
    if not found:
        log.debug("no window titled %r to bring forward", title)
        return False
    user32.ShowWindow(found[0], SW_RESTORE)
    user32.SetForegroundWindow(found[0])
    return True


def get_cursor_pos() -> tuple[int, int]:
    point = POINT()
    _user32.GetCursorPos(ctypes.byref(point))
    return point.x, point.y


def set_cursor_pos(x: int, y: int) -> None:
    _user32.SetCursorPos(int(x), int(y))


# Keyboard input, used only to hand back a key whose release was swallowed
# while the target had control. The flag marks the event as injected so it is
# not mistaken for real hardware.
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


def send_key_up(vk: int) -> bool:
    """Synthesize a key release for one virtual key."""
    inp = _INPUT()
    inp.type = 1                                          # INPUT_KEYBOARD
    inp.u.ki = KEYBDINPUT(int(vk), 0, KEYEVENTF_KEYUP, 0, None)
    return bool(_user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT)))


def primary_screen_rect() -> tuple[int, int, int, int]:
    """Return (left, top, right, bottom) of the virtual desktop."""
    left = _user32.GetSystemMetrics(76)
    top = _user32.GetSystemMetrics(77)
    width = _user32.GetSystemMetrics(0)
    height = _user32.GetSystemMetrics(1)
    return left, top, left + width, top + height


def release_clip_global() -> None:
    """Release the session-wide ClipCursor confinement."""
    _user32.ClipCursor(None)


class ClipGuard:
    """Reference-counted ownership of the cursor confinement."""

    _instance: "ClipGuard | None" = None

    def __init__(self) -> None:
        self.depth = 0

    @classmethod
    def instance(cls) -> "ClipGuard":
        if cls._instance is None:
            cls._instance = ClipGuard()
        return cls._instance

    def acquire(self) -> None:
        """Take a share of the confinement; the last release lifts it."""
        self.depth += 1

    def release(self) -> None:
        if self.depth > 0:
            self.depth -= 1
        if self.depth == 0:
            release_clip_global()

    def force_release(self) -> None:
        self.depth = 0
        release_clip_global()

    @classmethod
    def install_atexit(cls) -> None:
        import atexit

        atexit.register(cls.instance().force_release)


