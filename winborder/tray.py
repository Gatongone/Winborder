"""Notification area icon, so the host can be controlled without a console.

The icon owns a hidden window and a message loop on its own thread; clicks are
delivered to that window as window messages. Nothing here is required for the
bridge to work, so every failure is reported and then ignored: a host without a
tray icon still bridges the input.
"""

from __future__ import annotations

import ctypes
import logging
import threading
from ctypes import wintypes
from typing import Callable

from . import i18n, icon, theme

log = logging.getLogger("winborder.tray")

WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_COMMAND = 0x0111
WM_APP = 0x8000
WM_TRAY = WM_APP + 1
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205
WM_CONTEXTMENU = 0x007B

NIM_ADD = 0x00000000
NIM_MODIFY = 0x00000001
NIM_DELETE = 0x00000002
NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004

TPM_RETURNCMD = 0x0100
TPM_RIGHTBUTTON = 0x0002
MF_STRING = 0x00000000
MF_SEPARATOR = 0x0800
MF_CHECKED = 0x00000008

CW_USEDEFAULT = -2147483648
WS_OVERLAPPED = 0x00000000
COLOR_WINDOW = 5

IDI_APPLICATION = 32512

_u32 = ctypes.WinDLL("user32", use_last_error=True)
_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_g32 = ctypes.WinDLL("gdi32", use_last_error=True)
_shell32 = ctypes.WinDLL("shell32", use_last_error=True)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", ctypes.c_void_p),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR)]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT), ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON), ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD), ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256), ("uVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64), ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", ctypes.c_byte * 16), ("hBalloonIcon", wintypes.HICON),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


class ICONINFO(ctypes.Structure):
    _fields_ = [("fIcon", wintypes.BOOL), ("xHotspot", wintypes.DWORD),
                ("yHotspot", wintypes.DWORD), ("hbmMask", wintypes.HBITMAP),
                ("hbmColor", wintypes.HBITMAP)]


_u32.CreateWindowExW.restype = wintypes.HWND
_u32.DefWindowProcW.restype = ctypes.c_ssize_t
_u32.LoadIconW.restype = wintypes.HICON
_u32.CreatePopupMenu.restype = wintypes.HMENU
_u32.TrackPopupMenu.restype = wintypes.UINT
_g32.CreateDIBSection.restype = wintypes.HBITMAP
_u32.CreateIconIndirect.restype = wintypes.HICON
_k32.GetModuleHandleW.restype = wintypes.HMODULE

# Handles do not fit in the default int argument type, so every call that takes
# one has to be declared.
_u32.CreateWindowExW.argtypes = [
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND,
    wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p]
_u32.RegisterClassW.argtypes = [ctypes.c_void_p]
_u32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                wintypes.LPARAM]
_u32.DestroyWindow.argtypes = [wintypes.HWND]
_u32.PostQuitMessage.argtypes = [ctypes.c_int]
_u32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                              wintypes.LPARAM]
_u32.GetMessageW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT,
                             wintypes.UINT]
_u32.TranslateMessage.argtypes = [ctypes.c_void_p]
_u32.DispatchMessageW.argtypes = [ctypes.c_void_p]
_u32.GetCursorPos.argtypes = [ctypes.c_void_p]
_u32.SetForegroundWindow.argtypes = [wintypes.HWND]
_u32.LoadIconW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR]
_u32.CreatePopupMenu.argtypes = []
_u32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t,
                             wintypes.LPCWSTR]
_u32.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                ctypes.c_void_p]
_u32.DestroyMenu.argtypes = [wintypes.HMENU]
_u32.CreateIconIndirect.argtypes = [ctypes.c_void_p]
_g32.CreateCompatibleDC.argtypes = [wintypes.HDC]
_g32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.c_void_p, wintypes.UINT,
                                  ctypes.c_void_p, wintypes.HANDLE, wintypes.DWORD]
_g32.CreateBitmap.argtypes = [ctypes.c_int, ctypes.c_int, wintypes.UINT,
                              wintypes.UINT, ctypes.c_void_p]
_g32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
_g32.DeleteDC.argtypes = [wintypes.HDC]
_k32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
_shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.c_void_p]

WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
                             wintypes.WPARAM, wintypes.LPARAM)

ACCENT = theme.BRAND


def _make_icon(size: int = 32, colour: str = ACCENT) -> int:
    """Build an icon handle from the application mark."""
    header = BITMAPINFOHEADER()
    header.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    header.biWidth = size
    header.biHeight = -size                     # top-down rows
    header.biPlanes = 1
    header.biBitCount = 32
    bits = ctypes.c_void_p()
    dc = _g32.CreateCompatibleDC(None)
    colour_bitmap = _g32.CreateDIBSection(dc, ctypes.byref(header), 0,
                                          ctypes.byref(bits), None, 0)
    mask = _g32.CreateBitmap(size, size, 1, 1, None)
    try:
        pixels = icon.rgba(size, colour, "#000000")
        ctypes.memmove(bits.value, pixels, len(pixels))
        info = ICONINFO(True, 0, 0, mask, colour_bitmap)
        return int(_u32.CreateIconIndirect(ctypes.byref(info)))
    finally:
        _g32.DeleteObject(colour_bitmap)
        _g32.DeleteObject(mask)
        _g32.DeleteDC(dc)


class TrayIcon:
    """A notification area icon with a context menu.

    ``on_open`` runs when the icon is clicked, ``on_quit`` when Quit is chosen.
    Both are called from the tray thread.
    """

    MENU_OPEN = 1
    MENU_RELOAD = 2
    MENU_CONFIG = 3
    MENU_QUIT = 4
    MENU_PAUSE = 5

    def __init__(self, tooltip: str, on_open: Callable[[], None],
                 on_quit: Callable[[], None],
                 on_reload: Callable[[], None] | None = None,
                 on_open_config: Callable[[], None] | None = None,
                 on_pause: Callable[[], None] | None = None,
                 paused: Callable[[], bool] | None = None) -> None:
        self._tooltip = tooltip[:127]
        self._on_open = on_open
        self._on_quit = on_quit
        self._on_reload = on_reload
        self._on_open_config = on_open_config
        self._on_pause = on_pause
        self._paused = paused
        self._hwnd: int | None = None
        self._icon = 0
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._failed = False
        self._wndproc = WNDPROC(self._handle)

    # -- lifecycle --------------------------------------------------------

    def start(self) -> bool:
        """Add the icon, in the background. False when it could not be added."""
        self._thread = threading.Thread(target=self._run, name="winborder-tray",
                                        daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5.0)
        return not self._failed

    def stop(self) -> None:
        if self._hwnd:
            _u32.PostMessageW(self._hwnd, WM_CLOSE, 0, 0)

    # -- tray thread ------------------------------------------------------

    def _run(self) -> None:
        try:
            self._create_window()
            self._add_icon()
        except Exception:  # noqa: BLE001 - a tray icon is optional
            log.debug("tray icon unavailable", exc_info=True)
            self._failed = True
            self._ready.set()
            return
        self._ready.set()
        message = wintypes.MSG()
        while _u32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            _u32.TranslateMessage(ctypes.byref(message))
            _u32.DispatchMessageW(ctypes.byref(message))
        self._remove_icon()

    def _create_window(self) -> None:
        instance = _k32.GetModuleHandleW(None)
        window_class = WNDCLASSW()
        window_class.lpfnWndProc = ctypes.cast(self._wndproc, ctypes.c_void_p)
        window_class.hInstance = instance
        window_class.lpszClassName = "WinborderTray"
        if not _u32.RegisterClassW(ctypes.byref(window_class)):
            error = ctypes.get_last_error()
            if error not in (0, 1410):           # 1410: class already registered
                raise ctypes.WinError(error)
        handle = _u32.CreateWindowExW(0, "WinborderTray", "Winborder", WS_OVERLAPPED,
                                      0, 0, 0, 0, None, None, instance, None)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        self._hwnd = int(handle)

    def _add_icon(self) -> None:
        self._icon = _make_icon() or int(_u32.LoadIconW(None, IDI_APPLICATION))
        data = self._icon_data(NIF_MESSAGE | NIF_ICON | NIF_TIP)
        if not _shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(data)):
            raise ctypes.WinError(ctypes.get_last_error())

    def _remove_icon(self) -> None:
        if self._hwnd is None:
            return
        data = self._icon_data(NIF_MESSAGE)
        _shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(data))

    def _icon_data(self, flags: int) -> NOTIFYICONDATAW:
        data = NOTIFYICONDATAW()
        data.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        data.hWnd = self._hwnd
        data.uID = 1
        data.uFlags = flags
        data.uCallbackMessage = WM_TRAY
        data.hIcon = self._icon
        data.szTip = self._tooltip
        return data

    # -- messages ---------------------------------------------------------

    def _handle(self, hwnd, message, wparam, lparam) -> int:
        try:
            if message == WM_TRAY:
                self._on_tray_message(int(lparam))
            elif message == WM_CLOSE:
                _u32.DestroyWindow(hwnd)
            elif message == WM_DESTROY:
                _u32.PostQuitMessage(0)
        except Exception:  # noqa: BLE001 - never take the host down from here
            log.debug("tray message failed", exc_info=True)
        return _u32.DefWindowProcW(hwnd, message, wparam, lparam)

    def _on_tray_message(self, event: int) -> None:
        if event == WM_LBUTTONUP:
            self._on_open()
        elif event in (WM_RBUTTONUP, WM_CONTEXTMENU):
            self._show_menu()

    def _show_menu(self) -> None:
        menu = _u32.CreatePopupMenu()
        if not menu:
            return
        try:
            # Built when it is shown, so it carries the language in use.
            if self._on_pause is not None:
                paused = bool(self._paused is not None and self._paused())
                _u32.AppendMenuW(menu, MF_STRING | (MF_CHECKED if paused else 0),
                                 self.MENU_PAUSE,
                                 i18n.t("Resume") if paused else i18n.t("Pause"))
                _u32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
            _u32.AppendMenuW(menu, MF_STRING, self.MENU_OPEN,
                             i18n.t("Open settings"))
            if self._on_reload is not None:
                _u32.AppendMenuW(menu, MF_STRING, self.MENU_RELOAD,
                                 i18n.t("Reload settings"))
            if self._on_open_config is not None:
                _u32.AppendMenuW(menu, MF_STRING, self.MENU_CONFIG,
                                 i18n.t("Open settings file"))
            _u32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
            _u32.AppendMenuW(menu, MF_STRING, self.MENU_QUIT, i18n.t("Quit"))
            point = wintypes.POINT()
            _u32.GetCursorPos(ctypes.byref(point))
            _u32.SetForegroundWindow(self._hwnd)
            choice = _u32.TrackPopupMenu(
                menu, TPM_RETURNCMD | TPM_RIGHTBUTTON, point.x, point.y,
                0, self._hwnd, None)
            # The menu stays up until the owner pumps another message.
            _u32.PostMessageW(self._hwnd, 0, 0, 0)
            if choice:
                self._run_choice(int(choice))
        finally:
            _u32.DestroyMenu(menu)

    def _run_choice(self, choice: int) -> None:
        if choice == self.MENU_PAUSE and self._on_pause is not None:
            self._on_pause()
        elif choice == self.MENU_OPEN:
            self._on_open()
        elif choice == self.MENU_RELOAD and self._on_reload is not None:
            self._on_reload()
        elif choice == self.MENU_CONFIG and self._on_open_config is not None:
            self._on_open_config()
        elif choice == self.MENU_QUIT:
            self._on_quit()
