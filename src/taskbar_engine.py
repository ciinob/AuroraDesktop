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
    ACCENT_POLICY,
    WCA_ACCENT_POLICY,
    WINDOWCOMPOSITIONATTRIBDATA,
    user32,
)
import ctypes

ACCENT_DISABLED = 0

TASKBAR_MODES = {
    "clear": ("💎 全透明纯净无底色 (Clear · 推荐)", "clear", "#00000000"),
    "acrylic_clear": ("✨ 原生高透毛玻璃 (Acrylic)", "acrylic", "#00000000"),
    "aurora_glass": ("🌌 极光深海毛玻璃 (与左侧卡片同色)", "acrylic", "#0A0F1C78"),
    "blur": ("🌫️ 柔雾高斯模糊 (Blur)", "blur", "#00000000"),
    "normal": ("⬛ 恢复系统默认任务栏 (Normal)", "normal", "#00000000"),
}


def find_ttb_settings_path() -> Path | None:
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


def clear_legacy_win32_taskbar_black_state():
    """Clear any legacy Win32 SetWindowCompositionAttribute state on Shell_TrayWnd
    that causes Windows 11 24H2 XAML taskbars to render solid black!
    """
    accent = ACCENT_POLICY()
    accent.AccentState = ACCENT_DISABLED
    accent.AccentFlags = 0
    accent.GradientColor = 0
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


def import_existing_ttb_config() -> dict:
    default_cfg = {
        "enabled": True,
        "mode": "clear",
        "show_line": False,
        "max_win_acrylic": False,
    }
    sp = find_ttb_settings_path()
    if not sp:
        return default_cfg

    try:
        raw = sp.read_text(encoding="utf-8")
        cleaned = re.sub(r"^\s*//.*$", "", raw, flags=re.MULTILINE)
        data = json.loads(cleaned)
        desk = data.get("desktop_appearance", {})
        accent = desk.get("accent", "clear")
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

        default_cfg["show_line"] = bool(desk.get("show_line", False))
        default_cfg["max_win_acrylic"] = bool(data.get("maximized_window_appearance", {}).get("enabled", False))
    except Exception:
        pass
    return default_cfg


class TaskbarTransparencyEngine(QObject):
    """Windows 11 24H2 Safe Taskbar Controller:
    Drives TranslucentTB's signed XAML Visual Tree engine via strict schema-valid settings.json
    WITHOUT calling conflicting Win32 SetWindowCompositionAttribute on Shell_TrayWnd!
    """
    configChanged = Signal()

    def __init__(self, tb_cfg: dict, parent=None):
        super().__init__(parent)
        self.cfg = tb_cfg
        self._ttb_settings_path = find_ttb_settings_path()
        self._ttb_exe = find_ttb_executable()

        # Immediately clear any broken Win32 accent state that turned Win11 24H2 taskbar black
        clear_legacy_win32_taskbar_black_state()
        self.apply_all()

        # Lightweight health check every 8s to ensure XAML driver stays alive
        self._guard_timer = QTimer(self)
        self._guard_timer.setInterval(8000)
        self._guard_timer.timeout.connect(self._ensure_xaml_driver_running)
        self._guard_timer.start()

    def apply_all(self):
        if not self.cfg.get("enabled", True):
            return
        self._sync_xaml_backend()

    def _ensure_xaml_driver_running(self):
        if not self._ttb_exe or not self.cfg.get("enabled", True):
            return
        if self.cfg.get("mode") == "normal":
            return
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
        mode_key = self.cfg.get("mode", "clear")
        _, accent_str, color_hex = TASKBAR_MODES.get(mode_key, TASKBAR_MODES["clear"])
        show_line = bool(self.cfg.get("show_line", False))
        max_enabled = bool(self.cfg.get("max_win_acrylic", False))

        # Strictly conform to official TranslucentTB schema (no unknown keys!)
        payload = {
            "$schema": "https://TranslucentTB.github.io/settings.schema.json",
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

    def build_taskbar_menu(self, parent_menu: QMenu) -> QMenu:
        tb_menu = parent_menu.addMenu("🖥️ 任务栏透明样式")
        tb_menu.setStyleSheet(MENU_QSS)

        cur_mode = self.cfg.get("mode", "clear")
        grp = QActionGroup(tb_menu)
        for m_key, (m_label, _, _) in TASKBAR_MODES.items():
            a = tb_menu.addAction(m_label)
            a.setCheckable(True)
            a.setChecked(m_key == cur_mode)
            grp.addAction(a)
            a.triggered.connect(lambda checked=False, k=m_key: self._set_mode(k))

        tb_menu.addSeparator()
        act_line = tb_menu.addAction("显示任务栏顶部 1px 分割线")
        act_line.setCheckable(True)
        act_line.setChecked(bool(self.cfg.get("show_line", False)))
        act_line.toggled.connect(self._set_show_line)

        act_max = tb_menu.addAction("窗口最大化时自动变深色毛玻璃")
        act_max.setCheckable(True)
        act_max.setChecked(bool(self.cfg.get("max_win_acrylic", False)))
        act_max.toggled.connect(self._set_max_win)

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
