import ctypes
from ctypes import wintypes
import mmap
import shutil
import struct
import subprocess
import time
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QActionGroup
from PySide6.QtWidgets import QMenu

from paths import ASSETS_DIR, DATA_ROOT
from widgets import MENU_QSS
from win32_utils import (
    ACCENT_POLICY,
    WCA_ACCENT_POLICY,
    WINDOWCOMPOSITIONATTRIBDATA,
    has_maximized_app_window,
    user32,
)

ACCENT_DISABLED = 0
ACCENT_ENABLE_TRANSPARENTGRADIENT = 2
ACCENT_ENABLE_BLURBEHIND = 3
ACCENT_ENABLE_ACRYLICBLURBEHIND = 4


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_ubyte * 8),
    ]


# {D4E8A9B2-71F3-4C6D-9A2E-8B5F1C3D4E60}
CLSID_AURORA_TAP = GUID(
    0xD4E8A9B2,
    0x71F3,
    0x4C6D,
    (ctypes.c_ubyte * 8)(0x9A, 0x2E, 0x8B, 0x5F, 0x1C, 0x3D, 0x4E, 0x60),
)

# Mode IDs matching AuroraTaskbarTAP.cpp:
# 0 = Clear (0.0 opacity), 1 = Airy Glass (0.32), 2 = Deep Aurora Glass (0.68), 3 = System Default
TASKBAR_MODES: dict[str, tuple[str, int]] = {
    "clear": ("💎 全透明纯净无底色 (Clear · 默认)", 0),
    "acrylic_clear": ("✨ 轻透微雾毛玻璃 (Airy Glass)", 1),
    "aurora_glass": ("🌌 深邃极光暗夜底栏 (Deep Glass)", 2),
    "normal": ("⬛ 恢复系统默认任务栏 (System Default)", 3),
}

SHARED_MEM_NAME = "Local\\AuroraTaskbarSharedState_v1"
PERSISTENT_TAP_DLL = DATA_ROOT / "cache" / "AuroraTaskbarTAP.dll"


def _set_tray_accent(state: int, flags: int = 0, color: int = 0):
    accent = ACCENT_POLICY()
    accent.AccentState = state
    accent.AccentFlags = flags
    accent.GradientColor = color
    accent.AnimationId = 0

    data = WINDOWCOMPOSITIONATTRIBDATA()
    data.Attrib = WCA_ACCENT_POLICY
    data.pvData = ctypes.cast(ctypes.byref(accent), ctypes.c_void_p)
    data.cbData = ctypes.sizeof(accent)

    primary = user32.FindWindowW("Shell_TrayWnd", None)
    if primary:
        user32.SetWindowCompositionAttribute(primary, ctypes.byref(data))

    sec = None
    while True:
        sec = user32.FindWindowExW(None, sec, "Shell_SecondaryTrayWnd", None)
        if not sec:
            break
        user32.SetWindowCompositionAttribute(sec, ctypes.byref(data))


def apply_win32_taskbar_backdrop(mode_key: str, force_reset_blur: bool = False):
    """Set underlying Win32 Shell_TrayWnd & Shell_SecondaryTrayWnd backdrop.

    NOTE: Never use ACCENT_ENABLE_ACRYLICBLURBEHIND (4) on Shell_TrayWnd on Win11 24H2,
    as DWM latches the acrylic brush and refuses to return to transparent gradient!
    Instead, 'max_frosted' / 'normal' uses ACCENT_DISABLED (restoring Win11's native
    dark Mica/Acrylic XAML taskbar), and 'clear' uses ACCENT_ENABLE_TRANSPARENTGRADIENT.
    """
    if mode_key in ("normal", "max_frosted"):
        _set_tray_accent(ACCENT_DISABLED, 0, 0x00000000)
    else:
        if force_reset_blur:
            # Clear any previously latched DWM acrylic state before applying transparent gradient
            _set_tray_accent(ACCENT_DISABLED, 0, 0x00000000)
        _set_tray_accent(ACCENT_ENABLE_TRANSPARENTGRADIENT, 2, 0x00000000)


def import_existing_ttb_config() -> dict:
    return {
        "enabled": True,
        "mode": "clear",
        "show_line": False,
        "max_win_acrylic": True,
    }


def _get_explorer_taskbar_pid() -> int:
    tray = user32.FindWindowW("Shell_TrayWnd", None)
    if not tray:
        return 0
    pid = wintypes.DWORD(0)
    user32.GetWindowThreadProcessId(tray, ctypes.byref(pid))
    return int(pid.value)


class TaskbarTransparencyEngine(QObject):
    """100% Self-Contained Native Windows 11 Taskbar XAML Transparency Engine!
    Uses our bundled AuroraTaskbarTAP.dll via Windows.UI.Xaml!InitializeXamlDiagnosticsEx.
    Zero external dependency on TranslucentTB or Rainmeter!
    """
    configChanged = Signal()

    def __init__(self, tb_cfg: dict, parent=None, own_hwnds_provider=None):
        super().__init__(parent)
        self.cfg = tb_cfg
        if self.cfg.get("mode") not in TASKBAR_MODES:
            self.cfg["mode"] = "clear"
        self.cfg.setdefault("max_win_acrylic", True)
        self._own_hwnds_provider = own_hwnds_provider or (lambda: set())

        self._version = (int(time.time() * 1000) & 0x7FFFFFFF) or 1
        self._shm: mmap.mmap | None = None
        self._injected_pid = 0
        self._maximized_active = False

        self._ensure_persistent_tap_dll()
        self._init_shared_memory()
        self._maximized_active = self._detect_maximized_state()
        self.apply_all(force_reset_blur=True)

        # Maintain Win32 backdrop + re-attach TAP DLL if Explorer restarts
        self._guard_timer = QTimer(self)
        self._guard_timer.setInterval(1500)
        self._guard_timer.timeout.connect(self._check_explorer_alive)
        self._guard_timer.start()

        # Fast 260ms watcher for window maximize / restore transitions (~0.08ms per poll)
        self._max_timer = QTimer(self)
        self._max_timer.setInterval(260)
        self._max_timer.timeout.connect(self._poll_maximized_window)
        self._max_timer.start()

    def _detect_maximized_state(self) -> bool:
        if not self.cfg.get("enabled", True) or not self.cfg.get("max_win_acrylic", False):
            return False
        if self.cfg.get("mode") == "normal":
            return False
        return has_maximized_app_window(self._own_hwnds_provider())

    def _effective_mode_key(self) -> str:
        if not self.cfg.get("enabled", True):
            return "normal"
        base = self.cfg.get("mode", "clear")
        if base != "normal" and self.cfg.get("max_win_acrylic", False) and self._maximized_active:
            return "max_frosted"
        return base

    def _poll_maximized_window(self):
        now_max = self._detect_maximized_state()
        if now_max != self._maximized_active:
            self._maximized_active = now_max
            apply_win32_taskbar_backdrop(self._effective_mode_key(), force_reset_blur=(not now_max))
            self._write_shared_state()

    def _ensure_persistent_tap_dll(self):
        bundled = ASSETS_DIR / "AuroraTaskbarTAP.dll"
        if bundled.exists():
            try:
                PERSISTENT_TAP_DLL.parent.mkdir(parents=True, exist_ok=True)
                if not PERSISTENT_TAP_DLL.exists() or bundled.stat().st_size != PERSISTENT_TAP_DLL.stat().st_size:
                    shutil.copy2(str(bundled), str(PERSISTENT_TAP_DLL))
                    subprocess.run(
                        ["icacls", str(PERSISTENT_TAP_DLL.parent), "/grant", "*S-1-15-2-1:(OI)(CI)(RX)", "/grant", "*S-1-1-0:(OI)(CI)(RX)"],
                        creationflags=subprocess.CREATE_NO_WINDOW,
                        check=False,
                    )
                    subprocess.run(
                        ["icacls", str(PERSISTENT_TAP_DLL), "/grant", "*S-1-15-2-1:(RX)", "/grant", "*S-1-1-0:(RX)"],
                        creationflags=subprocess.CREATE_NO_WINDOW,
                        check=False,
                    )
            except OSError:
                # Already loaded in explorer.exe — existing DLL on disk is active and valid!
                pass

    def _init_shared_memory(self):
        try:
            self._shm = mmap.mmap(-1, 16, tagname=SHARED_MEM_NAME, access=mmap.ACCESS_WRITE)
        except Exception:
            self._shm = None

    def _write_shared_state(self):
        if not self._shm:
            self._init_shared_memory()
        if not self._shm:
            return
        self._version += 1
        enabled = bool(self.cfg.get("enabled", True))
        mode_key = self.cfg.get("mode", "clear")
        _, mode_int = TASKBAR_MODES.get(mode_key, TASKBAR_MODES["clear"])
        if not enabled:
            mode_int = 3  # System default
        elif mode_key != "normal" and self.cfg.get("max_win_acrylic", False) and self._maximized_active:
            mode_int = 3  # Restore native Win11 dark frosted Mica/Acrylic taskbar when window is maximized
        show_line = 1 if self.cfg.get("show_line", False) else 0

        self._shm.seek(0)
        self._shm.write(struct.pack("<IIII", self._version, mode_int, show_line, 0))
        self._shm.flush()

    def _inject_tap_into_explorer(self) -> bool:
        if not PERSISTENT_TAP_DLL.exists():
            return False
        pid = _get_explorer_taskbar_pid()
        if pid <= 0:
            return False
        if pid == self._injected_pid:
            return True

        try:
            wux = ctypes.WinDLL("Windows.UI.Xaml.dll")
            init_fn = wux.InitializeXamlDiagnosticsEx
            init_fn.argtypes = [
                wintypes.LPCWSTR,
                wintypes.DWORD,
                wintypes.LPCWSTR,
                wintypes.LPCWSTR,
                GUID,
                wintypes.LPCWSTR,
            ]
            init_fn.restype = ctypes.c_long

            dll_str = str(PERSISTENT_TAP_DLL)
            for idx in range(1, 12):
                conn = f"VisualDiagConnection{idx}"
                hr = init_fn(conn, pid, None, dll_str, CLSID_AURORA_TAP, None)
                if hr == 0:
                    self._injected_pid = pid
                    return True
        except Exception:
            pass
        return False

    def _check_explorer_alive(self):
        if not self.cfg.get("enabled", True):
            return
        apply_win32_taskbar_backdrop(self._effective_mode_key())
        pid = _get_explorer_taskbar_pid()
        if pid > 0 and pid != self._injected_pid:
            self._write_shared_state()
            self._inject_tap_into_explorer()

    def apply_all(self, force_reset_blur: bool = True):
        self._maximized_active = self._detect_maximized_state()
        apply_win32_taskbar_backdrop(self._effective_mode_key(), force_reset_blur=force_reset_blur)
        self._write_shared_state()
        if self.cfg.get("enabled", True):
            self._inject_tap_into_explorer()

    def shutdown_restore(self):
        """Optionally keep or restore taskbar on exit."""
        pass

    def build_taskbar_menu(self, parent_menu: QMenu) -> QMenu:
        tb_menu = parent_menu.addMenu("🖥️ 自研任务栏透明引擎 (无需 TranslucentTB)")
        tb_menu.setStyleSheet(MENU_QSS)

        cur_mode = self.cfg.get("mode", "clear")
        grp = QActionGroup(tb_menu)
        for m_key, (m_label, _) in TASKBAR_MODES.items():
            a = tb_menu.addAction(m_label)
            a.setCheckable(True)
            a.setChecked(m_key == cur_mode)
            grp.addAction(a)
            a.triggered.connect(lambda checked=False, k=m_key: self._set_mode(k))

        tb_menu.addSeparator()
        act_max = tb_menu.addAction("窗口最大化时自动切换深色毛玻璃")
        act_max.setCheckable(True)
        act_max.setChecked(bool(self.cfg.get("max_win_acrylic", False)))
        act_max.toggled.connect(self._set_max_win_acrylic)

        act_line = tb_menu.addAction("保留任务栏顶部 1px 分割细线")
        act_line.setCheckable(True)
        act_line.setChecked(bool(self.cfg.get("show_line", False)))
        act_line.toggled.connect(self._set_show_line)

        return tb_menu

    def _set_mode(self, mode_key: str):
        self.cfg["mode"] = mode_key
        self.apply_all()
        self.configChanged.emit()

    def _set_max_win_acrylic(self, val: bool):
        self.cfg["max_win_acrylic"] = bool(val)
        self.apply_all()
        self.configChanged.emit()

    def _set_show_line(self, val: bool):
        self.cfg["show_line"] = val
        self._write_shared_state()
        self.configChanged.emit()
