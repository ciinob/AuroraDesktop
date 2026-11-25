import ctypes
import json
import os
import re
import subprocess
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QActionGroup
from PySide6.QtWidgets import QMenu

from widgets import MENU_QSS
from win32_utils import (
    ACCENT_ENABLE_ACRYLICBLURBEHIND,
    ACCENT_ENABLE_BLURBEHIND,
    ACCENT_POLICY,
    WCA_ACCENT_POLICY,
    WINDOWCOMPOSITIONATTRIBDATA,
    user32,
)

ACCENT_DISABLED = 0
ACCENT_ENABLE_GRADIENT = 1
ACCENT_ENABLE_TRANSPARENTGRADIENT = 2

TASKBAR_MODES = {
    "acrylic_clear": ("✨ 原生高透亚克力 (已同步您的配置)", "acrylic", "#00000000"),
    "clear": ("💎 完全全透明无底色 (Clear)", "clear", "#00000000"),
    "aurora_glass": ("🌌 极光深海染色毛玻璃 (与卡片同色)", "acrylic", "#0A0F1C87"),
    "blur": ("🌫️ 柔雾高斯模糊 (Blur)", "blur", "#00000000"),
    "normal": ("⬛ 恢复系统默认任务栏 (Normal)", "normal", "#00000000"),
}


def find_ttb_settings_path() -> Path | None:
    """Locate Microsoft Store or Classic TranslucentTB settings.json if installed."""
    local_pkgs = Path(os.environ.get("LOCALAPPDATA", "")) / "Packages"
    if local_pkgs.exists():
        for pkg in local_pkgs.glob("*TranslucentTB*"):
            candidate = pkg / "RoamingState" / "settings.json"
            if candidate.exists():
                return candidate
    appdata_ttb = Path(os.environ.get("APPDATA", "")) / "TranslucentTB" / "settings.json"
    if appdata_ttb.exists():
        return appdata_ttb
    return None


def find_ttb_executable() -> Path | None:
    cand = Path(os.environ.get("LOCALAPPDATA", "")) / r"Microsoft\WindowsApps\ttb.exe"
    if cand.exists():
        return cand
    return None


def import_existing_ttb_config() -> dict:
    """Import user's current TranslucentTB configuration on first run."""
    default_cfg = {
        "enabled": True,
        "mode": "acrylic_clear",
        "show_line": True,
        "max_win_acrylic": False,
        "hide_ttb_tray": True,
    }
    sp = find_ttb_settings_path()
    if not sp:
        return default_cfg

    try:
        raw = sp.read_text(encoding="utf-8")
        # Strip // line comments allowed by TranslucentTB JSONC parser
        cleaned = re.sub(r"^\s*//.*$", "", raw, flags=re.MULTILINE)
        data = json.loads(cleaned)
        desk = data.get("desktop_appearance", {})
        accent = desk.get("accent", "acrylic")
        color = desk.get("color", "#00000000").upper()
        if accent == "clear":
            default_cfg["mode"] = "clear"
        elif accent == "blur":
            default_cfg["mode"] = "blur"
        elif accent == "normal":
            default_cfg["mode"] = "normal"
        elif color not in ("#00000000", "#00000001"):
            default_cfg["mode"] = "aurora_glass"
        else:
            default_cfg["mode"] = "acrylic_clear"

        default_cfg["show_line"] = bool(desk.get("show_line", True))
        default_cfg["max_win_acrylic"] = bool(data.get("maximized_window_appearance", {}).get("enabled", False))
    except Exception:
        pass
    return default_cfg


class TaskbarTransparencyEngine(QObject):
    """Unified Dual-Core Taskbar Controller:
    1. Syncs & hot-reloads Windows 11 24H2 XAML Taskbar driver (TranslucentTB settings.json + silent tray fusion)
    2. Enforces direct Win32 SetWindowCompositionAttribute on Primary & Secondary taskbars
    """
    configChanged = Signal()

    def __init__(self, tb_cfg: dict, parent=None):
        super().__init__(parent)
        self.cfg = tb_cfg
        self._ttb_settings_path = find_ttb_settings_path()
        self._ttb_exe = find_ttb_executable()

        # Apply immediately and periodically guard both Win32 taskbars & XAML backend
        self.apply_all()

        self._guard_timer = QTimer(self)
        self._guard_timer.setInterval(2500)
        self._guard_timer.timeout.connect(self._periodic_guard)
        self._guard_timer.start()

    def apply_all(self):
        if not self.cfg.get("enabled", True):
            return
        self._sync_xaml_backend()
        self._apply_win32_taskbar_accent()

    def _ensure_xaml_driver_running(self):
        if not self._ttb_exe or not self.cfg.get("enabled", True):
            return
        if self.cfg.get("mode") == "normal":
            return
        # Check lightweight process existence via tasklist/OpenProcess or spawn ttb.exe if needed
        try:
            out = subprocess.check_output(
                ["tasklist", "/FI", "IMAGENAME eq TranslucentTB.exe", "/NH"],
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=2,
            ).decode("gbk", errors="ignore")
            if "TranslucentTB.exe" not in out:
                subprocess.Popen([str(self._ttb_exe)], creationflags=subprocess.CREATE_NO_WINDOW)
        except Exception:
            pass

    def _sync_xaml_backend(self):
        if not self._ttb_settings_path:
            return
        mode_key = self.cfg.get("mode", "acrylic_clear")
        _, accent_str, color_hex = TASKBAR_MODES.get(mode_key, TASKBAR_MODES["acrylic_clear"])
        show_line = bool(self.cfg.get("show_line", True))
        max_enabled = bool(self.cfg.get("max_win_acrylic", False))
        hide_tray = bool(self.cfg.get("hide_ttb_tray", True))

        payload = {
            "$schema": "https://TranslucentTB.github.io/settings.schema.json",
            "hide_tray": hide_tray,
            "desktop_appearance": {
                "accent": accent_str,
                "color": color_hex,
                "show_peek": False,
                "show_line": show_line,
                "blur_radius": 9.0,
            },
            "visible_window_appearance": {
                "enabled": False,
                "accent": "clear",
                "color": "#00000000",
                "show_peek": True,
                "show_line": show_line,
                "blur_radius": 9.0,
                "rules": {"window_class": {}, "window_title": {}, "process_name": {}},
            },
            "maximized_window_appearance": {
                "enabled": max_enabled,
                "accent": "acrylic",
                "color": "#0A0F1CB0" if max_enabled else "#00000000",
                "show_peek": True,
                "show_line": True,
                "blur_radius": 9.0,
                "rules": {"window_class": {}, "window_title": {}, "process_name": {}},
            },
            "start_opened_appearance": {
                "enabled": False,
                "accent": "normal",
                "color": "#00000000",
                "show_peek": True,
                "show_line": True,
                "blur_radius": 9.0,
            },
            "search_opened_appearance": {
                "enabled": False,
                "accent": "normal",
                "color": "#00000000",
                "show_peek": True,
                "show_line": True,
                "blur_radius": 9.0,
            },
            "task_view_opened_appearance": {
                "enabled": True,
                "accent": "normal",
                "color": "#00000000",
                "show_peek": False,
                "show_line": True,
                "blur_radius": 9.0,
            },
            "battery_saver_appearance": {
                "enabled": False,
                "accent": "opaque",
                "color": "#00000000",
                "show_peek": True,
                "show_line": False,
                "blur_radius": 9.0,
            },
            "ignored_windows": {"window_class": [], "window_title": [], "process_name": []},
            "disable_saving": False,
            "verbosity": "warn",
        }
        try:
            self._ttb_settings_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception:
            pass
        self._ensure_xaml_driver_running()

    def _apply_win32_taskbar_accent(self):
        """Direct Win32 SetWindowCompositionAttribute on Primary & Secondary taskbars."""
        mode_key = self.cfg.get("mode", "acrylic_clear")
        if mode_key == "normal":
            state, grad_abgr = ACCENT_DISABLED, 0x00000000
        elif mode_key == "clear":
            state, grad_abgr = ACCENT_ENABLE_TRANSPARENTGRADIENT, 0x00000000
        elif mode_key == "blur":
            state, grad_abgr = ACCENT_ENABLE_BLURBEHIND, 0x00000000
        elif mode_key == "aurora_glass":
            state, grad_abgr = ACCENT_ENABLE_ACRYLICBLURBEHIND, 0x871C0F0A
        else:
            state, grad_abgr = ACCENT_ENABLE_ACRYLICBLURBEHIND, 0x01000000

        accent = ACCENT_POLICY()
        accent.AccentState = state
        accent.AccentFlags = 2
        accent.GradientColor = grad_abgr
        accent.AnimationId = 0

        data = WINDOWCOMPOSITIONATTRIBDATA()
        data.Attrib = WCA_ACCENT_POLICY
        data.pvData = ctypes.cast(ctypes.byref(accent), ctypes.c_void_p)
        data.cbData = ctypes.sizeof(accent)

        # Primary taskbar
        primary = user32.FindWindowW("Shell_TrayWnd", None)
        if primary:
            user32.SetWindowCompositionAttribute(primary, ctypes.byref(data))

        # All secondary monitor taskbars
        sec = None
        while True:
            sec = user32.FindWindowExW(None, sec, "Shell_SecondaryTrayWnd", None)
            if not sec:
                break
            user32.SetWindowCompositionAttribute(sec, ctypes.byref(data))

    def _periodic_guard(self):
        if self.cfg.get("enabled", True):
            self._apply_win32_taskbar_accent()

    def build_taskbar_menu(self, parent_menu: QMenu) -> QMenu:
        tb_menu = parent_menu.addMenu("🖥️ 任务栏透明引擎 (TranslucentTB 融合)")
        tb_menu.setStyleSheet(MENU_QSS)

        cur_mode = self.cfg.get("mode", "acrylic_clear")
        grp = QActionGroup(tb_menu)
        for m_key, (m_label, _, _) in TASKBAR_MODES.items():
            a = tb_menu.addAction(m_label)
            a.setCheckable(True)
            a.setChecked(m_key == cur_mode)
            grp.addAction(a)
            a.triggered.connect(lambda checked=False, k=m_key: self._set_mode(k))

        tb_menu.addSeparator()
        act_line = tb_menu.addAction("显示任务栏顶部 1px 微光分割线")
        act_line.setCheckable(True)
        act_line.setChecked(bool(self.cfg.get("show_line", True)))
        act_line.toggled.connect(self._set_show_line)

        act_max = tb_menu.addAction("窗口最大化时自动加深任务栏底色")
        act_max.setCheckable(True)
        act_max.setChecked(bool(self.cfg.get("max_win_acrylic", False)))
        act_max.toggled.connect(self._set_max_win)

        act_hide_ttb = tb_menu.addAction("隐藏独立 TranslucentTB 托盘图标 (单托盘融合)")
        act_hide_ttb.setCheckable(True)
        act_hide_ttb.setChecked(bool(self.cfg.get("hide_ttb_tray", True)))
        act_hide_ttb.toggled.connect(self._set_hide_tray)

        return tb_menu

    def _set_mode(self, mode_key: str):
        self.cfg["mode"] = mode_key
        self.apply_all()
        self.configChanged.emit()

    def _set_show_line(self, val: bool):
        self.cfg["show_line"] = val
        self._sync_xaml_backend()
        self.configChanged.emit()

    def _set_max_win(self, val: bool):
        self.cfg["max_win_acrylic"] = val
        self._sync_xaml_backend()
        self.configChanged.emit()

    def _set_hide_tray(self, val: bool):
        self.cfg["hide_ttb_tray"] = val
        self._sync_xaml_backend()
        self.configChanged.emit()
