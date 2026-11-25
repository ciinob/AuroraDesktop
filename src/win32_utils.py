import ctypes
from ctypes import wintypes
import time
from PySide6.QtCore import QObject, Signal, QTimer

user32 = ctypes.windll.user32
dwmapi = ctypes.windll.dwmapi
kernel32 = ctypes.windll.kernel32
oleacc = ctypes.windll.oleacc

# 64-bit safe types
LRESULT = ctypes.c_ssize_t
LONG_PTR = ctypes.c_ssize_t
ULONG_PTR = ctypes.c_size_t
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

# Constants
GWL_EXSTYLE = -20
GWLP_HWNDPARENT = -8

WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000

HWND_BOTTOM = wintypes.HWND(1)
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
SWP_NOCOPYBITS = 0x0100
SWP_NOSENDCHANGING = 0x0400

WM_WINDOWPOSCHANGING = 0x0046
WM_MOUSEACTIVATE = 0x0021
MA_NOACTIVATE = 3
WM_SYSCOMMAND = 0x0112
WM_COMMAND = 0x0111
WM_HOTKEY = 0x0312
SC_MINIMIZE = 0xF020
SHELL_TOGGLE_DESKTOP_ICONS_CMD = 0x7402

WS_EX_APPWINDOW = 0x00040000
WS_EX_TRANSPARENT = 0x00000020

DWMWA_CLOAKED = 14
DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWCP_ROUND = 2
DWMWA_TRANSITIONS_FORCEDISABLED = 3

WCA_ACCENT_POLICY = 19
ACCENT_ENABLE_BLURBEHIND = 3
ACCENT_ENABLE_ACRYLICBLURBEHIND = 4

WH_KEYBOARD_LL = 13
WH_MOUSE_LL = 14
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_LBUTTONDOWN = 0x0201
VK_CONTROL = 0x11
VK_LCONTROL = 0xA2
VK_RCONTROL = 0xA3
SM_CXDOUBLECLK = 36
SM_CYDOUBLECLK = 37
GA_ROOT = 2

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
VK_OEM_3 = 0xC0  # '~' / '`' key
VK_S = 0x53      # 'S' key

SPECIAL_VK_MAP: dict[str, int] = {
    "`": 0xC0,
    "~": 0xC0,
    "space": 0x20,
    "tab": 0x09,
    "enter": 0x0D,
    "return": 0x0D,
    "-": 0xBD,
    "=": 0xBB,
    "[": 0xDB,
    "]": 0xDD,
    "\\": 0xDC,
    ";": 0xBA,
    "'": 0xDE,
    ",": 0xBC,
    ".": 0xBE,
    "/": 0xBF,
    "up": 0x26,
    "down": 0x28,
    "left": 0x25,
    "right": 0x27,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21,
    "pagedown": 0x22,
    "insert": 0x2D,
    "delete": 0x2E,
}
for _i in range(1, 13):
    SPECIAL_VK_MAP[f"f{_i}"] = 0x70 + (_i - 1)


def parse_hotkey_spec(spec: str) -> tuple[int, int] | None:
    """Parse a hotkey string like 'Alt+S', 'Ctrl+Shift+Space', 'Alt+~' into (win32_mods, vk)."""
    if not spec or not spec.strip():
        return None
    parts = [p.strip() for p in spec.split("+") if p.strip()]
    if not parts:
        return None

    mods = 0
    key_token = ""
    for p in parts:
        low = p.lower()
        if low in ("ctrl", "control"):
            mods |= MOD_CONTROL
        elif low == "alt":
            mods |= MOD_ALT
        elif low == "shift":
            mods |= MOD_SHIFT
        elif low in ("win", "meta", "super"):
            mods |= MOD_WIN
        else:
            key_token = p

    if not key_token:
        return None

    low_k = key_token.lower()
    vk = 0
    if low_k in SPECIAL_VK_MAP:
        vk = SPECIAL_VK_MAP[low_k]
    elif len(key_token) == 1 and "a" <= low_k <= "z":
        vk = ord(low_k.upper())
    elif len(key_token) == 1 and "0" <= low_k <= "9":
        vk = ord(low_k)

    if vk == 0:
        return None
    # Require at least one modifier unless it's a function key F1..F12
    if mods == 0 and not (0x70 <= vk <= 0x7B):
        return None
    return mods, vk


def format_hotkey_label(spec: str) -> str:
    """Human-friendly display string, e.g. 'Alt+~' -> 'Alt + ~'."""
    if not spec or not spec.strip():
        return "未设置"
    parts = [p.strip() for p in spec.split("+") if p.strip()]
    pretty = []
    for p in parts:
        low = p.lower()
        if low in ("ctrl", "control"):
            pretty.append("Ctrl")
        elif low == "alt":
            pretty.append("Alt")
        elif low == "shift":
            pretty.append("Shift")
        elif low in ("win", "meta", "super"):
            pretty.append("Win")
        elif low in ("`", "~"):
            pretty.append("~")
        elif low == "space":
            pretty.append("Space")
        else:
            pretty.append(p.upper() if len(p) <= 3 else p.capitalize())
    return " + ".join(pretty)


class ACCENT_POLICY(ctypes.Structure):
    _fields_ = [
        ("AccentState", ctypes.c_int),
        ("AccentFlags", ctypes.c_int),
        ("GradientColor", ctypes.c_uint32),
        ("AnimationId", ctypes.c_int),
    ]


class WINDOWCOMPOSITIONATTRIBDATA(ctypes.Structure):
    _fields_ = [
        ("Attrib", ctypes.c_int),
        ("pvData", ctypes.c_void_p),
        ("cbData", ctypes.c_size_t),
    ]


class WINDOWPOS(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("hwndInsertAfter", wintypes.HWND),
        ("x", ctypes.c_int),
        ("y", ctypes.c_int),
        ("cx", ctypes.c_int),
        ("cy", ctypes.c_int),
        ("flags", wintypes.UINT),
    ]


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", wintypes.POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


# Configure ctypes signatures properly for 64-bit Windows
user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowW.restype = wintypes.HWND

user32.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowExW.restype = wintypes.HWND

user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int

user32.WindowFromPoint.argtypes = [wintypes.POINT]
user32.WindowFromPoint.restype = wintypes.HWND

user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype = wintypes.HWND

user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL

user32.SetWindowPos.argtypes = [
    wintypes.HWND, wintypes.HWND,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.UINT,
]
user32.SetWindowPos.restype = wintypes.BOOL

user32.BeginDeferWindowPos.argtypes = [ctypes.c_int]
user32.BeginDeferWindowPos.restype = wintypes.HANDLE

user32.DeferWindowPos.argtypes = [
    wintypes.HANDLE, wintypes.HWND, wintypes.HWND,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.UINT,
]
user32.DeferWindowPos.restype = wintypes.HANDLE

user32.EndDeferWindowPos.argtypes = [wintypes.HANDLE]
user32.EndDeferWindowPos.restype = wintypes.BOOL

user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongPtrW.restype = LONG_PTR

user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, LONG_PTR]
user32.SetWindowLongPtrW.restype = LONG_PTR

user32.SetWindowCompositionAttribute.argtypes = [wintypes.HWND, ctypes.POINTER(WINDOWCOMPOSITIONATTRIBDATA)]
user32.SetWindowCompositionAttribute.restype = wintypes.BOOL

dwmapi.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
dwmapi.DwmSetWindowAttribute.restype = ctypes.c_long

dwmapi.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long

user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.SendMessageW.restype = LRESULT

user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
user32.EnumWindows.restype = wintypes.BOOL

user32.IsZoomed.argtypes = [wintypes.HWND]
user32.IsZoomed.restype = wintypes.BOOL

user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsIconic.restype = wintypes.BOOL

user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowRect.restype = wintypes.BOOL

user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
user32.SetWindowsHookExW.restype = wintypes.HHOOK

user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.CallNextHookEx.restype = LRESULT

user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
user32.UnhookWindowsHookEx.restype = wintypes.BOOL

user32.GetDoubleClickTime.argtypes = []
user32.GetDoubleClickTime.restype = wintypes.UINT

user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int

user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.RegisterHotKey.restype = wintypes.BOOL

user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.UnregisterHotKey.restype = wintypes.BOOL

user32.RegisterWindowMessageW.argtypes = [wintypes.LPCWSTR]
user32.RegisterWindowMessageW.restype = wintypes.UINT

user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostMessageW.restype = wintypes.BOOL

user32.AllowSetForegroundWindow.argtypes = [wintypes.DWORD]
user32.AllowSetForegroundWindow.restype = wintypes.BOOL

user32.GetThreadDesktop.argtypes = [wintypes.DWORD]
user32.GetThreadDesktop.restype = wintypes.HANDLE

user32.GetUserObjectInformationW.argtypes = [
    wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)
]
user32.GetUserObjectInformationW.restype = wintypes.BOOL

kernel32.GetCurrentThreadId.argtypes = []
kernel32.GetCurrentThreadId.restype = wintypes.DWORD

kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE

HWND_BROADCAST = wintypes.HWND(0xFFFF)
ASFW_ANY = 0xFFFFFFFF
UOI_NAME = 2
WM_AURORA_SHOW = user32.RegisterWindowMessageW("AuroraDesktop_ShowAllCards_v1")
WM_AURORA_OPEN_PANEL = user32.RegisterWindowMessageW("AuroraDesktop_OpenMainPanel_v1")


def get_current_desktop_name() -> str:
    tid = kernel32.GetCurrentThreadId()
    hdesk = user32.GetThreadDesktop(tid)
    if not hdesk:
        return "Default"
    buf = ctypes.create_unicode_buffer(128)
    needed = wintypes.DWORD(0)
    if user32.GetUserObjectInformationW(hdesk, UOI_NAME, buf, ctypes.sizeof(buf), ctypes.byref(needed)):
        return buf.value or "Default"
    return "Default"


def get_window_class(hwnd: int) -> str:
    if not hwnd:
        return ""
    buf = ctypes.create_unicode_buffer(256)
    length = user32.GetClassNameW(hwnd, buf, 256)
    return buf.value if length > 0 else ""


def find_desktop_shell_host() -> tuple[int, int, int]:
    """Return (host_hwnd, defview_hwnd, listview_hwnd) for Windows Desktop."""
    progman = user32.FindWindowW("Progman", None)
    defview = user32.FindWindowExW(progman, None, "SHELLDLL_DefView", None) if progman else 0
    host = progman

    if not defview:
        worker = None
        while True:
            worker = user32.FindWindowExW(None, worker, "WorkerW", None)
            if not worker:
                break
            dv = user32.FindWindowExW(worker, None, "SHELLDLL_DefView", None)
            if dv:
                defview = dv
                host = worker
                break

    listview = user32.FindWindowExW(defview, None, "SysListView32", None) if defview else 0
    return (host or 0, defview or 0, listview or 0)


def are_system_desktop_icons_visible() -> bool:
    """Return True if Windows native desktop icons (SysListView32) are currently shown."""
    _, _, listview = find_desktop_shell_host()
    if not listview:
        return True
    return bool(user32.IsWindowVisible(listview))


def set_system_desktop_icons_visible(visible: bool) -> bool:
    """Idempotently show or hide Windows native desktop icons without touching any files."""
    _, defview, listview = find_desktop_shell_host()
    if not defview or not listview:
        return False
    cur = bool(user32.IsWindowVisible(listview))
    if cur != bool(visible):
        user32.SendMessageW(defview, WM_COMMAND, SHELL_TOGGLE_DESKTOP_ICONS_CMD, 0)
    return bool(user32.IsWindowVisible(listview)) == bool(visible)


_IGNORED_MAX_CLASSES = {
    "Progman",
    "WorkerW",
    "SHELLDLL_DefView",
    "SysListView32",
    "Shell_TrayWnd",
    "Shell_SecondaryTrayWnd",
    "Windows.UI.Core.CoreWindow",
    "XamlExplorerHostIslandWindow",
}


def has_maximized_app_window(own_hwnds: set[int] | None = None) -> bool:
    """Return True if any real, visible, uncloaked application window is currently maximized."""
    skip = own_hwnds or set()
    found = False

    def _enum_cb(hwnd, _lparam):
        nonlocal found
        if not hwnd or hwnd in skip:
            return True
        if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd) or not user32.IsZoomed(hwnd):
            return True

        ex = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        if (ex & WS_EX_TOOLWINDOW) and not (ex & WS_EX_APPWINDOW):
            return True
        if (ex & WS_EX_TRANSPARENT) and (ex & WS_EX_NOACTIVATE):
            return True

        cls = get_window_class(hwnd)
        if not cls or cls in _IGNORED_MAX_CLASSES:
            return True

        cloaked = ctypes.c_int(0)
        hr = dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
        if hr == 0 and cloaked.value != 0:
            return True

        rc = wintypes.RECT()
        if user32.GetWindowRect(hwnd, ctypes.byref(rc)):
            if (rc.right - rc.left) < 500 or (rc.bottom - rc.top) < 350:
                return True

        found = True
        return False  # Stop enumeration immediately on first match

    cb = WNDENUMPROC(_enum_cb)
    user32.EnumWindows(cb, 0)
    return found


def apply_dark_title_bar(hwnd: int):
    """Apply Windows 11 native immersive dark title bar and rounded corners to standard dialogs/windows."""
    if not hwnd:
        return
    dark = ctypes.c_int(1)
    dwmapi.DwmSetWindowAttribute(
        hwnd,
        DWMWA_USE_IMMERSIVE_DARK_MODE,
        ctypes.byref(dark),
        ctypes.sizeof(dark),
    )
    corner_pref = ctypes.c_int(DWMWCP_ROUND)
    dwmapi.DwmSetWindowAttribute(
        hwnd,
        DWMWA_WINDOW_CORNER_PREFERENCE,
        ctypes.byref(corner_pref),
        ctypes.sizeof(corner_pref),
    )


def apply_acrylic_and_rounded_corners(hwnd: int):
    """Enable Windows 11 rounded composition surface + Acrylic Gaussian blur."""
    if not hwnd:
        return

    # 1. Native Windows 11 hardware-anti-aliased rounded corners (prevents square acrylic bleed)
    corner_pref = ctypes.c_int(DWMWCP_ROUND)
    dwmapi.DwmSetWindowAttribute(
        hwnd,
        DWMWA_WINDOW_CORNER_PREFERENCE,
        ctypes.byref(corner_pref),
        ctypes.sizeof(corner_pref),
    )

    # 2. Windows 11 Acrylic blur behind window (persists even when unfocused on desktop)
    # GradientColor is AABBGGRR: tiny non-zero alpha (0x02) activates full blur while Qt controls exact RGBA tint
    accent = ACCENT_POLICY()
    accent.AccentState = ACCENT_ENABLE_ACRYLICBLURBEHIND
    accent.AccentFlags = 0
    accent.GradientColor = 0x021C0F0A
    accent.AnimationId = 0

    data = WINDOWCOMPOSITIONATTRIBDATA()
    data.Attrib = WCA_ACCENT_POLICY
    data.pvData = ctypes.cast(ctypes.byref(accent), ctypes.c_void_p)
    data.cbData = ctypes.sizeof(accent)

    ok = user32.SetWindowCompositionAttribute(hwnd, ctypes.byref(data))
    if not ok:
        accent.AccentState = ACCENT_ENABLE_BLURBEHIND
        user32.SetWindowCompositionAttribute(hwnd, ctypes.byref(data))


def pin_window_to_desktop_bottom(hwnd: int):
    """Pin window above wallpaper, below normal windows, hidden from Alt+Tab, surviving Win+D."""
    if not hwnd:
        return

    ex_style = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
    new_ex_style = ex_style | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
    if new_ex_style != ex_style:
        user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, new_ex_style)

    # Set Owner to Desktop host (Progman/WorkerW) so Win+D keeps cards visible above desktop!
    host_hwnd, _, _ = find_desktop_shell_host()
    if host_hwnd:
        user32.SetWindowLongPtrW(hwnd, GWLP_HWNDPARENT, LONG_PTR(host_hwnd))

    send_to_bottom(hwnd)


def send_to_bottom(hwnd: int):
    if not hwnd:
        return
    # Note: omit SWP_NOSENDCHANGING so Win32 enforces owner Z-order above Progman/WorkerW during Win+D!
    user32.SetWindowPos(
        hwnd,
        HWND_BOTTOM,
        0, 0, 0, 0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
    )


def batch_defer_window_rects(rect_updates: list[tuple[int, int, int, int, int]]):
    """Atomically move multiple HWNDs in one single 240Hz DWM composition transaction!"""
    if not rect_updates:
        return
    hdwp = user32.BeginDeferWindowPos(len(rect_updates))
    if not hdwp:
        return
    flags = SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_NOCOPYBITS
    for hwnd, x, y, w, h in rect_updates:
        hdwp = user32.DeferWindowPos(hdwp, hwnd, None, x, y, 0, 0, flags)
        if not hdwp:
            return
    user32.EndDeferWindowPos(hdwp)


def is_click_on_blank_desktop(x: int, y: int, own_hwnds: set[int]) -> bool:
    """Return True if (x, y) is on empty Windows desktop wallpaper rather than an app or desktop icon."""
    pt = wintypes.POINT(x, y)
    hwnd = user32.WindowFromPoint(pt)
    if not hwnd:
        return False

    root = user32.GetAncestor(hwnd, GA_ROOT)
    if hwnd in own_hwnds or root in own_hwnds:
        return False

    cls = get_window_class(hwnd)
    root_cls = get_window_class(root)

    # Ignore Rainmeter widgets (like top-right clock)
    if "Rainmeter" in cls or "Rainmeter" in root_cls:
        return False

    desktop_classes = {"Progman", "WorkerW", "SHELLDLL_DefView", "SysListView32"}
    if cls not in desktop_classes and root_cls not in {"Progman", "WorkerW"}:
        return False

    # If SysListView32 is visible (desktop icons still enabled), check if user double-clicked an actual icon
    if cls == "SysListView32" and user32.IsWindowVisible(hwnd):
        try:
            pacc = ctypes.c_void_p()
            var_child = (ctypes.c_byte * 24)()  # VARIANT struct (24 bytes on x64)
            hr = oleacc.AccessibleObjectFromPoint(pt, ctypes.byref(pacc), ctypes.byref(var_child))
            if hr == 0 and pacc.value:
                # In VARIANT: offset 0 is vt (USHORT, VT_I4=3), offset 8 is lVal (LONG)
                vt = ctypes.c_ushort.from_buffer(var_child, 0).value
                lval = ctypes.c_long.from_buffer(var_child, 8).value
                # Release COM pointer IUnknown::Release (vtable index 2)
                vtable = ctypes.cast(ctypes.cast(pacc, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
                release_fn = ctypes.WINFUNCTYPE(wintypes.ULONG, ctypes.c_void_p)(vtable[2])
                release_fn(pacc)
                # lval > 0 means a specific desktop listview icon item was clicked!
                if vt == 3 and lval > 0:
                    return False
        except Exception:
            pass

    return True


class DesktopDoubleClickWatcher(QObject):
    """Lightweight WH_MOUSE_LL listener that detects double-clicks on blank desktop area."""
    desktopDoubleClicked = Signal()

    def __init__(self, own_hwnds_provider, parent=None):
        super().__init__(parent)
        self._own_hwnds_provider = own_hwnds_provider
        self._hook = None
        self._last_click_time = 0.0
        self._last_pt = (0, 0)
        self._hook_proc = HOOKPROC(self._mouse_callback)

    def start(self):
        if self._hook:
            return
        hmod = kernel32.GetModuleHandleW(None)
        self._hook = user32.SetWindowsHookExW(WH_MOUSE_LL, self._hook_proc, hmod, 0)

    def stop(self):
        if self._hook:
            user32.UnhookWindowsHookEx(self._hook)
            self._hook = None

    def _mouse_callback(self, nCode: int, wParam: int, lParam: int) -> int:
        if nCode >= 0 and wParam == WM_LBUTTONDOWN:
            info = ctypes.cast(lParam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
            x, y = info.pt.x, info.pt.y
            now = time.monotonic()
            dbl_ms = user32.GetDoubleClickTime() / 1000.0
            dx = max(user32.GetSystemMetrics(SM_CXDOUBLECLK), 6)
            dy = max(user32.GetSystemMetrics(SM_CYDOUBLECLK), 6)

            if (
                (now - self._last_click_time) <= dbl_ms
                and abs(x - self._last_pt[0]) <= dx
                and abs(y - self._last_pt[1]) <= dy
            ):
                self._last_click_time = 0.0
                QTimer.singleShot(0, lambda px=x, py=y: self._verify_and_emit(px, py))
            else:
                self._last_click_time = now
                self._last_pt = (x, y)

        return user32.CallNextHookEx(self._hook, nCode, wParam, lParam)

    def _verify_and_emit(self, x: int, y: int):
        own_hwnds = self._own_hwnds_provider()
        if is_click_on_blank_desktop(x, y, own_hwnds):
            self.desktopDoubleClicked.emit()


class DoubleCtrlWatcher(QObject):
    """Lightweight WH_KEYBOARD_LL listener that detects quick Double-Tap Ctrl (like Raycast / Listary)."""
    doubleCtrlPressed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hook = None
        self._ctrl_down = False
        self._other_key_pressed = False
        self._last_ctrl_up_time = 0.0
        self._hook_proc = HOOKPROC(self._kbd_callback)

    def start(self):
        if self._hook:
            return
        hmod = kernel32.GetModuleHandleW(None)
        self._hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._hook_proc, hmod, 0)

    def stop(self):
        if self._hook:
            user32.UnhookWindowsHookEx(self._hook)
            self._hook = None

    def _kbd_callback(self, nCode: int, wParam: int, lParam: int) -> int:
        if nCode >= 0:
            info = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            vk = info.vkCode
            is_ctrl = vk in (VK_CONTROL, VK_LCONTROL, VK_RCONTROL)

            if wParam == WM_KEYDOWN:
                if is_ctrl:
                    self._ctrl_down = True
                else:
                    self._other_key_pressed = True
            elif wParam == WM_KEYUP:
                if is_ctrl:
                    now = time.monotonic()
                    if self._ctrl_down and not self._other_key_pressed:
                        if 0.04 <= (now - self._last_ctrl_up_time) <= 0.36:
                            self._last_ctrl_up_time = 0.0
                            QTimer.singleShot(0, self.doubleCtrlPressed.emit)
                        else:
                            self._last_ctrl_up_time = now
                    self._ctrl_down = False
                    self._other_key_pressed = False

        return user32.CallNextHookEx(self._hook, nCode, wParam, lParam)
