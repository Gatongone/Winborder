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
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
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


def verify_coordinate_space() -> str:
    """Report whether screen metrics and the physical monitor agree."""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    logical_w = user32.GetSystemMetrics(0)
    logical_h = user32.GetSystemMetrics(1)

    class MonitorInfo(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", RECT),
            ("rcWork", RECT),
            ("dwFlags", wintypes.DWORD),
        ]

    monitor = user32.MonitorFromWindow(user32.GetDesktopWindow(), 2)
    info = MonitorInfo()
    info.cbSize = ctypes.sizeof(MonitorInfo)
    if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return f"logical {logical_w}x{logical_h} (monitor query failed)"
    phys_w = info.rcMonitor.right - info.rcMonitor.left
    phys_h = info.rcMonitor.bottom - info.rcMonitor.top
    if (logical_w, logical_h) == (phys_w, phys_h):
        return f"{phys_w}x{phys_h}"
    return f"mismatch: logical {logical_w}x{logical_h} vs physical {phys_w}x{phys_h}"


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


def get_clip_rect() -> tuple[int, int, int, int] | None:
    rect = RECT()
    if not _user32.GetClipCursor(ctypes.byref(rect)):
        return None
    return rect.left, rect.top, rect.right, rect.bottom


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

    def acquire(self, side: str = "right") -> None:
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


def install_clip_guard() -> bool:
    """Place the process in a job object that kills on close.

    Windows offers no way to run code when a process is force-terminated.
    A job object is the only kernel-level guarantee: when the last handle
    closes, the kernel terminates the process and the session clip state is
    released with it.

    Returning False means the guard is unavailable (for example when the
    process already belongs to a non-nestable job). Callers must surface this
    because a force-kill would otherwise leave the cursor confined.
    """
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD
        ]
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = [
            wintypes.HANDLE, wintypes.HANDLE
        ]
        kernel32.IsProcessInJob.restype = wintypes.BOOL
        kernel32.IsProcessInJob.argtypes = [
            wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)
        ]

        in_job = wintypes.BOOL()
        already = bool(
            kernel32.IsProcessInJob(
                kernel32.GetCurrentProcess(), None, ctypes.byref(in_job)
            )
            and in_job.value
        )

        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            log.debug("CreateJobObjectW failed, err=%d", ctypes.get_last_error())
            return False

        class IoCounters(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_ulonglong),
                ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong),
                ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong),
                ("OtherTransferCount", ctypes.c_ulonglong),
            ]

        class BasicLimitInformation(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class ExtendedLimitInformation(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BasicLimitInformation),
                ("IoInfo", IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        info = ExtendedLimitInformation()
        info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(
            job, 9, ctypes.byref(info), ctypes.sizeof(info)
        ):
            log.debug("SetInformationJobObject failed, err=%d",
                      ctypes.get_last_error())
            return False
        if not kernel32.AssignProcessToJobObject(job, kernel32.GetCurrentProcess()):
            log.debug("AssignProcessToJobObject failed, already_in_job=%s, err=%d",
                      already, ctypes.get_last_error())
            return False
        return True
    except Exception:
        log.debug("job object guard unavailable", exc_info=True)
        return False
