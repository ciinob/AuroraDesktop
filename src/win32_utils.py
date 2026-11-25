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
SWP_NOSENDCHANGING = 0x0400

WM_WINDOWPOSCHANGING = 0x0046
WM_MOUSEACTIVATE = 0x0021
MA_NOACTIVATE = 3
WM_SYSCOMMAND = 0x0112
WM_HOTKEY = 0x0312
SC_MINIMIZE = 0xF020

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
MOD_NOREPEAT = 0x4000
VK_OEM_3 = 0xC0  # '~' / '`' key
VK_S = 0x53      # 'S' key


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

user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongPtrW.restype = LONG_PTR

user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, LONG_PTR]
user32.SetWindowLongPtrW.restype = LONG_PTR

user32.SetWindowCompositionAttribute.argtypes = [wintypes.HWND, ctypes.POINTER(WINDOWCOMPOSITIONATTRIBDATA)]
user32.SetWindowCompositionAttribute.restype = wintypes.BOOL

dwmapi.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
dwmapi.DwmSetWindowAttribute.restype = ctypes.c_long

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
