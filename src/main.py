import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import webbrowser
import winreg
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QObject, QTimer, Qt, Signal
from PySide6.QtGui import QFontDatabase, QGuiApplication, QIcon
from PySide6.QtWidgets import QApplication, QInputDialog, QMenu, QMessageBox, QSystemTrayIcon, QWidget

sys.path.insert(0, str(Path(__file__).resolve().parent))

from clock_widget import AuroraClockWidget
from icon_extractor import ShortcutIconLoader, item_rel_key
from memo_card import AuroraMemoCard
from organize_shortcuts import scan_and_organize
from paths import APP_VERSION, CONFIG_PATH, DATA_ROOT, FONTS_DIR, GROUPS_DIR, ICON_ICO_PATH, ICON_PNG_PATH
from settings_dialog import AuroraSettingsWindow
from spotlight import AuroraSpotlightOverlay
from taskbar_engine import TaskbarTransparencyEngine, import_existing_ttb_config
from updater import UpdateChecker
from widgets import (
    AICapsuleBar,
    AURORA_THEMES,
    AuroraBaseWindow,
    CollapsibleAuroraCard,
    DIALOG_QSS,
    GLASS_OPACITY_LEVELS,
    MENU_QSS,
    NewCapsuleDialog,
    launch_item,
    list_valid_partition_items,
    make_apple_font,
    open_target_location,
    prompt_add_directory_to_folder,
    prompt_add_items_to_folder,
    safe_remove_shortcut,
    sort_group_items,
)
from win32_utils import (
    ASFW_ANY,
    DesktopDoubleClickWatcher,
    DoubleCtrlWatcher,
    HWND_BROADCAST,
    MOD_NOREPEAT,
    WM_AURORA_OPEN_PANEL,
    WM_AURORA_SHOW,
    WM_HOTKEY,
    batch_defer_window_rects,
    format_hotkey_label,
    get_current_desktop_name,
    parse_hotkey_spec,
    send_to_bottom,
    user32,
)

HOTKEY_ID_TOGGLE = 0xA001
HOTKEY_ID_SPOTLIGHT = 0xA002
HOTKEY_ID_SETTINGS = 0xA003
AUTORUN_REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
STARTUP_APPROVED_REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"
AUTORUN_KEY_NAME = "AuroraDesktop"
WM_TASKBAR_CREATED = user32.RegisterWindowMessageW("TaskbarCreated")

DEFAULT_HOTKEYS = {
    "double_ctrl_spotlight": True,
    "spotlight": "Alt+S",
    "toggle_cards": "Alt+~",
    "settings": "Alt+,",
}

DEFAULT_PARTITIONS = [
    {"key": "AI_CAPSULE", "title": "AI 悬浮胶囊栏", "folder": "01_AI_CAPSULE", "kind": "bar", "badge": "AI"},
    {"key": "RESEARCH_DEV", "title": "RESEARCH & DEV", "folder": "02_RESEARCH_DEV", "kind": "card"},
    {"key": "PLAY_SOCIAL", "title": "PLAY & SOCIAL", "folder": "03_PLAY_SOCIAL", "kind": "card"},
    {"key": "TOOLS_NET", "title": "TOOLS & NET", "folder": "04_TOOLS_NET", "kind": "card"},
]


class HotkeyReceiver(QWidget):
    """Hidden Win32 message receiver for configurable global hotkeys, single-instance wakeup, and Explorer restarts."""

    def __init__(self, on_toggle_vis, on_spotlight, on_open_settings, on_force_show, on_explorer_restarted):
        super().__init__()
        self._on_toggle_vis = on_toggle_vis
        self._on_spotlight = on_spotlight
        self._on_open_settings = on_open_settings
        self._on_force_show = on_force_show
        self._on_explorer_restarted = on_explorer_restarted
        self._registered_ids: set[int] = set()
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint)
        self.resize(1, 1)

    def apply_hotkeys(self, toggle_spec: str, spotlight_spec: str, settings_spec: str) -> dict[str, bool]:
        hwnd = int(self.winId())
        for hk_id in list(self._registered_ids):
            user32.UnregisterHotKey(hwnd, hk_id)
        self._registered_ids.clear()

        results: dict[str, bool] = {}
        for slot, hk_id, spec in [
            ("toggle_cards", HOTKEY_ID_TOGGLE, toggle_spec),
            ("spotlight", HOTKEY_ID_SPOTLIGHT, spotlight_spec),
            ("settings", HOTKEY_ID_SETTINGS, settings_spec),
        ]:
            if not spec or not spec.strip():
                results[slot] = True
                continue
            parsed = parse_hotkey_spec(spec)
            if not parsed:
                results[slot] = False
                continue
            mods, vk = parsed
            ok = bool(user32.RegisterHotKey(hwnd, hk_id, mods | MOD_NOREPEAT, vk))
            if ok:
                self._registered_ids.add(hk_id)
            results[slot] = ok
        return results

    def nativeEvent(self, eventType, message):
        if eventType == b"windows_generic_MSG" or eventType == "windows_generic_MSG":
            msg = ctypes.wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY:
                if msg.wParam == HOTKEY_ID_TOGGLE:
                    self._on_toggle_vis()
                    return True, 0
                if msg.wParam == HOTKEY_ID_SPOTLIGHT:
                    self._on_spotlight()
                    return True, 0
                if msg.wParam == HOTKEY_ID_SETTINGS:
                    self._on_open_settings()
                    return True, 0
            elif WM_AURORA_OPEN_PANEL and msg.message == WM_AURORA_OPEN_PANEL:
                self._on_open_settings()
                return True, 0
            elif WM_AURORA_SHOW and msg.message == WM_AURORA_SHOW:
                self._on_force_show()
                return True, 0
            elif WM_TASKBAR_CREATED and msg.message == WM_TASKBAR_CREATED:
                self._on_explorer_restarted()
                return True, 0
        return super().nativeEvent(eventType, message)

    def cleanup(self):
        hwnd = int(self.winId())
        for hk_id in list(self._registered_ids):
            user32.UnregisterHotKey(hwnd, hk_id)
        self._registered_ids.clear()


class AuroraController(QObject):
    """Flagship Controller: Settings Center, Custom Icons, Configurable Hotkeys, Spotlight, Clock & Taskbar."""

    stateChanged = Signal()

    LEFT_MARGIN = 24
    TOP_MARGIN = 24
    CARD_GAP = 10
    COL_GAP = 14
    CARD_W = 368

    def __init__(self, app: QApplication, open_panel_on_start: bool = True):
        super().__init__()
        self.app = app
        self._open_panel_on_start = open_panel_on_start
        self.config = self._load_config()
        self.visible_state = True
        self.lock_positions = bool(self.config.get("lock_positions", False))
        self.double_click_hide = bool(self.config.get("double_click_hide", True))
        self.theme_key = self.config.get("theme", "aurora")
        if self.theme_key not in AURORA_THEMES:
            self.theme_key = "aurora"
        self.opacity_key = self.config.get("glass_opacity", "standard")
        if self.opacity_key not in GLASS_OPACITY_LEVELS:
            self.opacity_key = "standard"

        self.show_memo = bool(self.config.get("show_memo", False))
        self.memo_pinned = bool(self.config.get("memo_pinned", True))
        self.item_orders: dict[str, list[str]] = dict(self.config.get("item_orders", {}))
        self.custom_icons: dict[str, str] = {
            k.lower(): v for k, v in dict(self.config.get("custom_icons", {})).items()
        }
        self.dragged_keys: set[str] = set(self.config.get("dragged_keys", []))
        self.hotkeys_cfg: dict = {**DEFAULT_HOTKEYS, **dict(self.config.get("hotkeys", {}))}
        self.hotkey_status: dict[str, bool] = {"spotlight": True, "toggle_cards": True, "settings": True}
        self.settings_win: AuroraSettingsWindow | None = None

        GROUPS_DIR.mkdir(parents=True, exist_ok=True)
        if not any(GROUPS_DIR.rglob("*.lnk")):
            scan_and_organize()

        self.partitions: list[dict] = self._init_partitions()
        self.all_groups_meta: dict[str, tuple[str, Path]] = {}
        self._rebuild_groups_meta()

        if FONTS_DIR.exists():
            for fp in sorted(list(FONTS_DIR.glob("*.ttf")) + list(FONTS_DIR.glob("*.otf"))):
                QFontDatabase.addApplicationFont(str(fp))
        self.header_font_family = "Inter"
        self.icon_loader = ShortcutIconLoader(self.custom_icons)

        # 1. Native Desktop Clock
        default_clock_cfg = {
            "enabled": True,
            "style": "nordic_modern",
            "use_24h": True,
            "show_seconds": False,
            "scale": 1.0,
            "locked": False,
            "click_through": False,
            "x": None,
            "y": None,
        }
        self.clock_cfg: dict = {**default_clock_cfg, **self.config.get("clock", {})}
        self.clock_widget = AuroraClockWidget(
            clock_cfg=self.clock_cfg,
            theme_provider=self.get_current_theme_colors,
        )
        self.clock_widget.configChanged.connect(self._on_subcomponent_changed)
        self.clock_widget.openSettingsRequested.connect(lambda: self.open_settings("appearance"))

        # 2. Native Dual-Core Taskbar Transparency Engine
        if "taskbar" in self.config and isinstance(self.config["taskbar"], dict):
            self.taskbar_cfg = self.config["taskbar"]
        else:
            self.taskbar_cfg = import_existing_ttb_config()
        self.taskbar_engine = TaskbarTransparencyEngine(self.taskbar_cfg, self)
        self.taskbar_engine.configChanged.connect(self._on_subcomponent_changed)

        self.windows: list[AuroraBaseWindow] = []
        self.memo_card: AuroraMemoCard | None = None
        self._build_all_windows()
        self._sync_memo_card(initial=True)
        self._apply_initial_positions()

        # Global Aurora Spotlight Search Overlay
        self.spotlight = AuroraSpotlightOverlay(
            icon_loader=self.icon_loader,
            partitions_provider=lambda: list(self.all_groups_meta.values()),
            launch_callback=launch_item,
            open_loc_callback=lambda p: open_target_location(p, self.icon_loader),
            font_maker=make_apple_font,
            theme_provider=self.get_current_theme_colors,
            settings_callback=lambda: self.open_settings("general"),
        )

        # Watch mapping folders for live updates
        self.fs_watcher = QFileSystemWatcher(self)
        self._sync_watcher_paths()
        self._reload_debounce = QTimer(self)
        self._reload_debounce.setSingleShot(True)
        self._reload_debounce.setInterval(300)
        self._reload_debounce.timeout.connect(self._on_fs_changed)
        self.fs_watcher.directoryChanged.connect(lambda _: self._reload_debounce.start())

        # Desktop blank double-click stealth watcher
        self.dbl_watcher = DesktopDoubleClickWatcher(self.get_all_hwnds, self)
        self.dbl_watcher.desktopDoubleClicked.connect(self.toggle_all_visibility)
        if self.double_click_hide:
            self.dbl_watcher.start()

        # Double-Tap Ctrl Spotlight trigger watcher
        self.ctrl_watcher = DoubleCtrlWatcher(self)
        self.ctrl_watcher.doubleCtrlPressed.connect(self.spotlight.toggle_spotlight)
        if self.hotkeys_cfg.get("double_ctrl_spotlight", True):
            self.ctrl_watcher.start()

        # Configurable global hotkeys + Explorer restart recovery
        self.hotkey_receiver = HotkeyReceiver(
            self.toggle_all_visibility,
            self.spotlight.toggle_spotlight,
            lambda: self.open_settings("general"),
            self.force_show_and_showcase,
            self._on_explorer_restarted,
        )
        self.hotkey_status = self.hotkey_receiver.apply_hotkeys(
            self.hotkeys_cfg.get("toggle_cards", ""),
            self.hotkeys_cfg.get("spotlight", ""),
            self.hotkeys_cfg.get("settings", ""),
        )

        # Periodic light z-order guard + cold-boot shell readiness re-pin
        self.z_guard_timer = QTimer(self)
        self.z_guard_timer.setInterval(4000)
        self.z_guard_timer.timeout.connect(self._enforce_all_bottom)
        self.z_guard_timer.start()
        QTimer.singleShot(2000, self._on_explorer_restarted)

        self._setup_tray()

        for w in self.windows:
            w.show()
        if self.memo_card and self.show_memo:
            self.memo_card.show()
        if self.clock_cfg.get("enabled", True):
            self.clock_widget.show()

        # Ensure existing autorun entry uses --autostart so Windows boot stays silent
        if self.is_autorun_enabled():
            self._write_autorun_registry(True)

        self._save_config()
        QTimer.singleShot(3500, self._initial_auto_collapse)
        if self._open_panel_on_start:
            QTimer.singleShot(120, lambda: self.open_settings("general"))

    def _on_subcomponent_changed(self):
        self._save_config()
        self.stateChanged.emit()

    @property
    def ai_bar(self):
        return self.windows[0] if self.windows else None

    @property
    def cards(self) -> list[CollapsibleAuroraCard]:
        return [w for w in self.windows if isinstance(w, CollapsibleAuroraCard)]

    def get_current_theme_colors(self):
        return AURORA_THEMES[self.theme_key][:3]

    def get_current_glass_opacity(self) -> int:
        return GLASS_OPACITY_LEVELS[self.opacity_key][0]

    def get_custom_order(self, group_key: str) -> list[str]:
        return self.item_orders.get(group_key, [])

    def _on_order_changed(self, group_key: str, new_names: list[str]):
        self.item_orders[group_key] = new_names
        self._save_config()

    def _init_partitions(self) -> list[dict]:
        saved = self.config.get("partitions")
        parts = [dict(p) for p in (saved if isinstance(saved, list) and saved else DEFAULT_PARTITIONS)]

        known_folders = {p["folder"].lower() for p in parts}
        for p in parts:
            (GROUPS_DIR / p["folder"]).mkdir(parents=True, exist_ok=True)

        for sub in sorted(GROUPS_DIR.iterdir(), key=lambda x: x.name.lower()):
            if sub.is_dir() and sub.name.lower() not in known_folders:
                clean_title = re.sub(r"^\d+[_-\s]*", "", sub.name).strip() or sub.name
                parts.append({
                    "key": f"CUSTOM_{sub.name.upper()}",
                    "title": clean_title,
                    "folder": sub.name,
                    "kind": "card",
                })
                known_folders.add(sub.name.lower())
        return parts

    def _rebuild_groups_meta(self):
        self.all_groups_meta.clear()
        for p in self.partitions:
            self.all_groups_meta[p["key"]] = (p["title"], GROUPS_DIR / p["folder"])

    def _sync_watcher_paths(self):
        existing = self.fs_watcher.directories()
        if existing:
            self.fs_watcher.removePaths(existing)
        paths = [str(GROUPS_DIR)] + [str(GROUPS_DIR / p["folder"]) for p in self.partitions if (GROUPS_DIR / p["folder"]).exists()]
        self.fs_watcher.addPaths(paths)

    def _create_window_for_partition(self, p: dict, is_first_bar: bool = False) -> AuroraBaseWindow:
        g_key = p["key"]
        title = p["title"]
        folder = GROUPS_DIR / p["folder"]
        folder.mkdir(parents=True, exist_ok=True)
        pinned_map = self.config.get("pinned", {})

        if p.get("kind") == "bar":
            badge = p.get("badge") or title[:2].upper()
            win = AICapsuleBar(
                folder_path=folder,
                icon_loader=self.icon_loader,
                header_font_family=self.header_font_family,
                all_groups=self.all_groups_meta,
                allow_drag_provider=lambda: not self.lock_positions,
                theme_provider=self.get_current_theme_colors,
                opacity_provider=self.get_current_glass_opacity,
                custom_order_provider=self.get_custom_order,
                group_key=g_key,
                title=title,
                badge_text=badge,
                show_search_pill=is_first_bar,
            )
            win.orderChanged.connect(self._on_order_changed)
            win.spotlightRequested.connect(lambda: self.spotlight.toggle_spotlight())
        else:
            win = CollapsibleAuroraCard(
                group_key=g_key,
                title=title,
                folder_path=folder,
                icon_loader=self.icon_loader,
                header_font_family=self.header_font_family,
                all_groups=self.all_groups_meta,
                pinned=bool(pinned_map.get(g_key, False)),
                allow_drag_provider=lambda: not self.lock_positions,
                theme_provider=self.get_current_theme_colors,
                opacity_provider=self.get_current_glass_opacity,
                custom_order_provider=self.get_custom_order,
            )
            win.heightAnimated.connect(self.reflow_vertical_stack)
            win.pinToggled.connect(self._on_pin_toggled)
            win.orderChanged.connect(self._on_order_changed)
            win.spotlightRequested.connect(lambda: self.spotlight.toggle_spotlight())

        win.itemMoveRequested.connect(self.move_shortcut_between_groups)
        win.contextActionTriggered.connect(self.handle_context_action)
        win.renameCapsuleRequested.connect(self.rename_capsule_dialog)
        win.deleteCapsuleRequested.connect(self.delete_capsule_dialog)
        win.openSettingsRequested.connect(self.open_settings)
        win.positionChangedByUser.connect(lambda k=g_key: self._on_user_dragged(k))
        return win

    def _build_all_windows(self):
        # Snapshot current pin state so rebuilding windows preserves runtime toggles
        if self.windows:
            pinned_now = dict(self.config.get("pinned", {}))
            for w in self.windows:
                if isinstance(w, CollapsibleAuroraCard):
                    pinned_now[w.group_key] = w.pinned
            self.config["pinned"] = pinned_now

        for w in self.windows:
            w.close()
            w.deleteLater()
        self.windows.clear()
        first_bar_assigned = False
        for p in self.partitions:
            is_first = False
            if p.get("kind") == "bar" and not first_bar_assigned:
                is_first = True
                first_bar_assigned = True
            self.windows.append(self._create_window_for_partition(p, is_first_bar=is_first))

    def _sync_memo_card(self, initial: bool = False):
        if self.show_memo and self.memo_card is None:
            self.memo_card = AuroraMemoCard(
                pinned=self.memo_pinned,
                allow_drag_provider=lambda: not self.lock_positions,
                theme_provider=self.get_current_theme_colors,
                opacity_provider=self.get_current_glass_opacity,
            )
            self.memo_card.heightAnimated.connect(self.reflow_vertical_stack)
            self.memo_card.pinToggled.connect(self._on_memo_pin_toggled)
            self.memo_card.closeMemoRequested.connect(self.toggle_memo_card)
            self.memo_card.positionChangedByUser.connect(lambda: self._on_user_dragged("__AURORA_MEMO__"))
            if not initial and self.visible_state:
                self.reflow_vertical_stack()
                self.memo_card.show()
        elif not self.show_memo and self.memo_card is not None:
            self.memo_card.close()
            self.memo_card.deleteLater()
            self.memo_card = None
            self.reflow_vertical_stack()

    def set_show_memo(self, show: bool):
        show = bool(show)
        if self.show_memo == show:
            return
        self.show_memo = show
        self._sync_memo_card(initial=False)
        if hasattr(self, "act_memo_tray"):
            self.act_memo_tray.blockSignals(True)
            self.act_memo_tray.setChecked(self.show_memo)
            self.act_memo_tray.blockSignals(False)
        self._save_config()
        self.stateChanged.emit()

    def toggle_memo_card(self):
        self.set_show_memo(not self.show_memo)

    def _on_memo_pin_toggled(self, pinned: bool):
        self.memo_pinned = pinned
        self._save_config()

    def _load_config(self) -> dict:
        if CONFIG_PATH.exists():
            try:
                return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"pinned": {"RESEARCH_DEV": False, "PLAY_SOCIAL": False, "TOOLS_NET": False}}

    def _save_config(self):
        positions = {w.group_key: [w.x(), w.y()] for w in self.windows}
        if self.memo_card is not None:
            positions["__AURORA_MEMO__"] = [self.memo_card.x(), self.memo_card.y()]
        pinned = dict(self.config.get("pinned", {}))
        for w in self.windows:
            if isinstance(w, CollapsibleAuroraCard):
                pinned[w.group_key] = w.pinned
        self.config["pinned"] = pinned

        data = {
            "partitions": self.partitions,
            "pinned": pinned,
            "theme": self.theme_key,
            "glass_opacity": self.opacity_key,
            "show_memo": self.show_memo,
            "memo_pinned": self.memo_pinned,
            "double_click_hide": self.double_click_hide,
            "hotkeys": self.hotkeys_cfg,
            "custom_icons": self.custom_icons,
            "clock": self.clock_cfg,
            "taskbar": self.taskbar_cfg,
            "item_orders": self.item_orders,
            "lock_positions": self.lock_positions,
            "dragged_keys": sorted(self.dragged_keys),
            "positions": positions,
        }
        CONFIG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _all_stackable_windows(self) -> list[AuroraBaseWindow]:
        wins = list(self.windows)
        if self.memo_card is not None and self.show_memo:
            wins.append(self.memo_card)
        return wins

    def _apply_initial_positions(self):
        saved_pos = self.config.get("positions", {})
        self.reflow_vertical_stack()
        for w in self._all_stackable_windows():
            if w.group_key in self.dragged_keys and w.group_key in saved_pos:
                wx, wy = saved_pos[w.group_key]
                w.move(wx, wy)

    def reset_to_left_golden_layout(self, save: bool = True):
        self.dragged_keys.clear()
        self.reflow_vertical_stack()
        if save:
            self._save_config()

    def reflow_vertical_stack(self):
        screen = QGuiApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else None
        start_x = (avail.x() if avail else 0) + self.LEFT_MARGIN
        start_y = (avail.y() if avail else 0) + self.TOP_MARGIN
        max_bottom = (avail.bottom() - 12) if avail else 1380

        col_x = start_x
        curr_y = start_y
        updates: list[tuple[int, int, int, int, int]] = []

        for idx, w in enumerate(self._all_stackable_windows()):
            if w.group_key in self.dragged_keys:
                if hasattr(w, "desired_stack_height"):
                    dh = w.desired_stack_height()
                    if w.height() != dh:
                        updates.append((int(w.winId()), w.x(), w.y(), w.width(), dh))
                continue

            target_h = w.desired_stack_height() if hasattr(w, "desired_stack_height") else w.height()
            if curr_y > start_y and (curr_y + target_h > max_bottom):
                col_x += self.CARD_W + self.COL_GAP
                curr_y = start_y

            if w.x() != col_x or w.y() != curr_y:
                updates.append((int(w.winId()), col_x, curr_y, w.width(), w.height()))

            extra_gap = 2 if idx == 0 else 0
            curr_y += target_h + self.CARD_GAP + extra_gap

        if updates:
            batch_defer_window_rects(updates)

    def set_aurora_theme(self, theme_key: str):
        if theme_key not in AURORA_THEMES:
            return
        self.theme_key = theme_key
        for w in self._all_stackable_windows():
            w.update()
        self.clock_widget.refresh()
        self._save_config()
        self.stateChanged.emit()

    def set_glass_opacity(self, opacity_key: str):
        if opacity_key not in GLASS_OPACITY_LEVELS:
            return
        self.opacity_key = opacity_key
        for w in self._all_stackable_windows():
            w.update()
        self._save_config()
        self.stateChanged.emit()

    # =========================================================================
    # Settings Center & Partition / Icon / Hotkey Management APIs
    # =========================================================================
    def open_settings(self, page_key: str = "general", target: object = None):
        if self.spotlight.isVisible():
            self.spotlight.close()
        user32.AllowSetForegroundWindow(ASFW_ANY)
        if self.settings_win is None:
            self.settings_win = AuroraSettingsWindow(self)
        self.settings_win.navigate_to(page_key, target)
        if self.settings_win.isMinimized():
            self.settings_win.showNormal()
        else:
            self.settings_win.show()
        self.settings_win.raise_()
        self.settings_win.activateWindow()

    def get_partition_items(self, group_key: str) -> list[Path]:
        part = next((p for p in self.partitions if p["key"] == group_key), None)
        if not part:
            return []
        folder = GROUPS_DIR / part["folder"]
        return sort_group_items(group_key, list_valid_partition_items(folder), self.get_custom_order(group_key))

    def is_partition_pinned(self, group_key: str) -> bool:
        win = next((w for w in self.windows if w.group_key == group_key), None)
        if isinstance(win, CollapsibleAuroraCard):
            return bool(win.pinned)
        return bool(self.config.get("pinned", {}).get(group_key, False))

    def add_partition(self, title: str, kind: str, badge: str = "") -> dict:
        safe_slug = re.sub(r'[<>:"/\\|?*\s]+', "_", title).strip("_") or "Capsule"
        next_idx = len(self.partitions) + 1
        folder_name = f"{next_idx:02d}_{safe_slug}"
        while (GROUPS_DIR / folder_name).exists():
            next_idx += 1
            folder_name = f"{next_idx:02d}_{safe_slug}"

        key = f"CAP_{next_idx:02d}_{safe_slug.upper()}"
        part: dict = {
            "key": key,
            "title": title,
            "folder": folder_name,
            "kind": kind if kind in ("card", "bar") else "card",
        }
        if part["kind"] == "bar":
            part["badge"] = (badge or title[:2]).upper()

        (GROUPS_DIR / folder_name).mkdir(parents=True, exist_ok=True)
        self.partitions.append(part)
        self._rebuild_groups_meta()
        self._sync_watcher_paths()

        has_bar = any(isinstance(w, AICapsuleBar) and w.show_search_pill for w in self.windows)
        win = self._create_window_for_partition(part, is_first_bar=(part["kind"] == "bar" and not has_bar))
        if isinstance(win, CollapsibleAuroraCard):
            win.pinned = True
        self.windows.append(win)
        self.reload_all_groups()
        self.reflow_vertical_stack()
        if self.visible_state:
            win.show()
        self._save_config()
        self.stateChanged.emit()
        return part

    def create_new_capsule_dialog(self):
        dlg = NewCapsuleDialog()
        if dlg.exec() != NewCapsuleDialog.Accepted:
            return
        title, kind = dlg.get_result()
        self.add_partition(title, kind)

    def update_partition(
        self,
        group_key: str,
        *,
        title: str | None = None,
        kind: str | None = None,
        badge: str | None = None,
        pinned: bool | None = None,
    ):
        part = next((p for p in self.partitions if p["key"] == group_key), None)
        win = next((w for w in self.windows if w.group_key == group_key), None)
        if not part or not win:
            return

        old_kind = part.get("kind", "card")
        new_kind = kind if kind in ("card", "bar") else old_kind
        if title:
            part["title"] = title
        part["kind"] = new_kind
        if new_kind == "bar":
            part["badge"] = (badge or part.get("badge") or part["title"][:2]).upper()

        if pinned is not None:
            self.config.setdefault("pinned", {})[group_key] = bool(pinned)

        self._rebuild_groups_meta()

        if new_kind != old_kind:
            self._build_all_windows()
            self._apply_initial_positions()
            if self.visible_state:
                for w in self.windows:
                    w.show()
        else:
            win.title = part["title"]
            if isinstance(win, AICapsuleBar):
                win.badge_text = part.get("badge", part["title"][:2].upper())
            elif isinstance(win, CollapsibleAuroraCard) and pinned is not None:
                win.pinned = bool(pinned)
                if win.pinned:
                    win.expand_card()
                else:
                    win.collapse_card(force=True)
            win.update()
            self.reload_all_groups()

        self._save_config()
        self.stateChanged.emit()

    def move_partition(self, group_key: str, delta: int) -> bool:
        idx = next((i for i, p in enumerate(self.partitions) if p["key"] == group_key), -1)
        target_idx = idx + delta
        if idx < 0 or not (0 <= target_idx < len(self.partitions)):
            return False

        other_key = self.partitions[target_idx]["key"]
        self.partitions[idx], self.partitions[target_idx] = self.partitions[target_idx], self.partitions[idx]
        self.windows[idx], self.windows[target_idx] = self.windows[target_idx], self.windows[idx]
        self.dragged_keys.discard(group_key)
        self.dragged_keys.discard(other_key)

        # Ensure only the topmost horizontal bar shows the Spotlight pill
        first_bar_seen = False
        for w in self.windows:
            if isinstance(w, AICapsuleBar):
                want_pill = not first_bar_seen
                first_bar_seen = True
                if w.show_search_pill != want_pill:
                    w.show_search_pill = want_pill
                    w.reload_items()

        self._rebuild_groups_meta()
        self.reflow_vertical_stack()
        self._save_config()
        self.stateChanged.emit()
        return True

    def rename_capsule_dialog(self, group_key: str):
        part = next((p for p in self.partitions if p["key"] == group_key), None)
        if not part:
            return
        dlg = QInputDialog()
        dlg.setStyleSheet(DIALOG_QSS)
        dlg.setWindowTitle("重命名极光胶囊")
        dlg.setLabelText("请输入新的胶囊标题 / 徽标：")
        dlg.setTextValue(part.get("badge", part["title"]) if part.get("kind") == "bar" else part["title"])
        if dlg.exec() != QInputDialog.Accepted:
            return
        new_title = dlg.textValue().strip()
        if not new_title:
            return
        if part.get("kind") == "bar":
            self.update_partition(group_key, title=f"{new_title} 悬浮胶囊栏", badge=new_title[:3])
        else:
            self.update_partition(group_key, title=new_title)

    def delete_capsule_dialog(self, group_key: str, parent_widget: QWidget | None = None):
        if len(self.partitions) <= 1:
            return
        part = next((p for p in self.partitions if p["key"] == group_key), None)
        win = next((w for w in self.windows if w.group_key == group_key), None)
        if not part or not win:
            return

        box = QMessageBox(parent_widget)
        box.setStyleSheet(DIALOG_QSS)
        box.setWindowTitle("删除极光胶囊")
        box.setText(f"确定要移除胶囊「{part['title']}」吗？\n（内部快捷方式将安全移入 Removed_Backup 备份夹，绝不删除原程序）")
        btn_yes = box.addButton("确认移除", QMessageBox.AcceptRole)
        box.addButton("取消", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() != btn_yes:
            return

        folder = GROUPS_DIR / part["folder"]
        if folder.exists():
            for item in list(folder.iterdir()):
                if item.is_file() or item.is_dir():
                    safe_remove_shortcut(item)
            try:
                folder.rmdir()
            except OSError:
                pass

        self.partitions = [p for p in self.partitions if p["key"] != group_key]
        self.dragged_keys.discard(group_key)
        self.item_orders.pop(group_key, None)
        self.windows.remove(win)
        win.close()
        win.deleteLater()

        self._rebuild_groups_meta()
        self._sync_watcher_paths()
        self.reload_all_groups()
        self.reflow_vertical_stack()
        self._save_config()
        self.stateChanged.emit()

    def add_files_to_partition(self, parent_widget: QWidget, group_key: str) -> bool:
        part = next((p for p in self.partitions if p["key"] == group_key), None)
        if not part:
            return False
        if prompt_add_items_to_folder(parent_widget, GROUPS_DIR / part["folder"]):
            self.reload_all_groups()
            self.stateChanged.emit()
            return True
        return False

    def add_dir_to_partition(self, parent_widget: QWidget, group_key: str) -> bool:
        part = next((p for p in self.partitions if p["key"] == group_key), None)
        if not part:
            return False
        if prompt_add_directory_to_folder(parent_widget, GROUPS_DIR / part["folder"]):
            self.reload_all_groups()
            self.stateChanged.emit()
            return True
        return False

    def open_partition_folder(self, group_key: str):
        part = next((p for p in self.partitions if p["key"] == group_key), None)
        if part:
            folder = GROUPS_DIR / part["folder"]
            folder.mkdir(parents=True, exist_ok=True)
            subprocess.Popen(["explorer.exe", str(folder)])

    def open_data_root(self):
        subprocess.Popen(["explorer.exe", str(DATA_ROOT)])

    def set_item_custom_icon(self, item_path: Path, src_icon_file: Path) -> bool:
        out_name = self.icon_loader.import_custom_icon(src_icon_file)
        if not out_name:
            return False
        rel = item_rel_key(item_path)
        self.custom_icons[rel] = out_name
        self.icon_loader.set_custom_icons(self.custom_icons)
        self.reload_all_groups()
        self._save_config()
        self.stateChanged.emit()
        return True

    def clear_item_custom_icon(self, item_path: Path):
        rel = item_rel_key(item_path)
        if rel in self.custom_icons:
            self.custom_icons.pop(rel, None)
            self.icon_loader.set_custom_icons(self.custom_icons)
            self.reload_all_groups()
            self._save_config()
            self.stateChanged.emit()

    def rename_partition_item(self, item_path: Path, new_name: str) -> Path | None:
        if not item_path.exists():
            return None
        for ch in '<>:"/\\|?*':
            new_name = new_name.replace(ch, "")
        new_name = new_name.strip()
        if not new_name:
            return None
        suffix = item_path.suffix if item_path.is_file() else ""
        new_path = item_path.with_name(f"{new_name}{suffix}")
        if new_path == item_path:
            return item_path
        if new_path.exists():
            return None

        old_rel = item_rel_key(item_path)
        old_filename = item_path.name
        try:
            item_path.rename(new_path)
        except OSError:
            return None

        new_rel = item_rel_key(new_path)
        if old_rel in self.custom_icons:
            self.custom_icons[new_rel] = self.custom_icons.pop(old_rel)
            self.icon_loader.set_custom_icons(self.custom_icons)

        for grp_k, order_list in self.item_orders.items():
            self.item_orders[grp_k] = [new_path.name if n == old_filename else n for n in order_list]

        self.reload_all_groups()
        self._save_config()
        self.stateChanged.emit()
        return new_path

    def open_item_location(self, item_path: Path):
        open_target_location(item_path, self.icon_loader)

    def remove_partition_item(self, item_path: Path):
        rel = item_rel_key(item_path)
        self.custom_icons.pop(rel, None)
        self.icon_loader.set_custom_icons(self.custom_icons)
        safe_remove_shortcut(item_path)
        self.reload_all_groups()
        self._save_config()
        self.stateChanged.emit()

    def clear_icon_cache(self):
        self.icon_loader.invalidate(clear_disk_cache=True)
        self.reload_all_groups()

    def update_hotkeys(
        self,
        *,
        double_ctrl_spotlight: bool | None = None,
        spotlight: str | None = None,
        toggle_cards: str | None = None,
        settings: str | None = None,
    ) -> dict[str, bool]:
        if double_ctrl_spotlight is not None:
            self.hotkeys_cfg["double_ctrl_spotlight"] = bool(double_ctrl_spotlight)
            if double_ctrl_spotlight:
                self.ctrl_watcher.start()
            else:
                self.ctrl_watcher.stop()
        if spotlight is not None:
            self.hotkeys_cfg["spotlight"] = spotlight.strip()
        if toggle_cards is not None:
            self.hotkeys_cfg["toggle_cards"] = toggle_cards.strip()
        if settings is not None:
            self.hotkeys_cfg["settings"] = settings.strip()

        self.hotkey_status = self.hotkey_receiver.apply_hotkeys(
            self.hotkeys_cfg.get("toggle_cards", ""),
            self.hotkeys_cfg.get("spotlight", ""),
            self.hotkeys_cfg.get("settings", ""),
        )
        self._refresh_tray_labels()
        self._save_config()
        return self.hotkey_status

    def reset_default_hotkeys(self) -> dict[str, bool]:
        return self.update_hotkeys(
            double_ctrl_spotlight=DEFAULT_HOTKEYS["double_ctrl_spotlight"],
            spotlight=DEFAULT_HOTKEYS["spotlight"],
            toggle_cards=DEFAULT_HOTKEYS["toggle_cards"],
            settings=DEFAULT_HOTKEYS["settings"],
        )

    def set_double_click_hide(self, enabled: bool):
        self.double_click_hide = bool(enabled)
        if self.double_click_hide:
            self.dbl_watcher.start()
        else:
            self.dbl_watcher.stop()
        self._save_config()
        self.stateChanged.emit()

    def set_lock_positions(self, locked: bool):
        self.lock_positions = bool(locked)
        self._save_config()
        self.stateChanged.emit()

    def _on_fs_changed(self):
        known_folders = {p["folder"].lower() for p in self.partitions}
        added_new = False
        if GROUPS_DIR.exists():
            for sub in sorted(GROUPS_DIR.iterdir(), key=lambda x: x.name.lower()):
                if sub.is_dir() and sub.name.lower() not in known_folders:
                    clean_title = re.sub(r"^\d+[_-\s]*", "", sub.name).strip() or sub.name
                    part = {
                        "key": f"CUSTOM_{sub.name.upper()}",
                        "title": clean_title,
                        "folder": sub.name,
                        "kind": "card",
                    }
                    self.partitions.append(part)
                    known_folders.add(sub.name.lower())
                    self._rebuild_groups_meta()
                    win = self._create_window_for_partition(part)
                    self.windows.append(win)
                    if self.visible_state:
                        win.show()
                    added_new = True

        if added_new:
            self._sync_watcher_paths()
            self._save_config()

        self.reload_all_groups()
        self.stateChanged.emit()

    def _initial_auto_collapse(self):
        for c in self.cards:
            if not c.pinned and not c.underMouse():
                c.collapse_card()
        if self.memo_card and not self.memo_card.pinned and not self.memo_card.underMouse():
            self.memo_card.collapse_card()

    def _on_pin_toggled(self, group_key: str, pinned: bool):
        self._save_config()
        self.stateChanged.emit()

    def _on_user_dragged(self, group_key: str):
        self.dragged_keys.add(group_key)
        self._save_config()

    def get_all_hwnds(self) -> set[int]:
        hwnds = {int(w.winId()) for w in self._all_stackable_windows()}
        if self.clock_widget.isVisible():
            hwnds.add(int(self.clock_widget.winId()))
        if self.spotlight.isVisible():
            hwnds.add(int(self.spotlight.winId()))
        if self.settings_win is not None and self.settings_win.isVisible():
            hwnds.add(int(self.settings_win.winId()))
        return hwnds

    def _on_explorer_restarted(self):
        """Re-pin all desktop widgets, re-show tray, and re-apply taskbar transparency after cold boot or Explorer restart."""
        for w in self._all_stackable_windows():
            if w.isVisible():
                w.ensure_native_desktop_style()
        if self.clock_widget.isVisible():
            self.clock_widget.ensure_desktop_pinned()
        self.taskbar_engine.apply_all()
        if hasattr(self, "tray") and not self.tray.isVisible():
            self.tray.show()

    def _enforce_all_bottom(self):
        if self.clock_widget.isVisible():
            send_to_bottom(int(self.clock_widget.winId()))
        if not self.visible_state:
            return
        for w in self._all_stackable_windows():
            send_to_bottom(int(w.winId()))

    def force_show_and_showcase(self):
        if not self.visible_state:
            self.toggle_all_visibility()
        for c in self.cards:
            c.expand_card()
        QTimer.singleShot(4000, self._initial_auto_collapse)

    def toggle_all_visibility(self):
        self.visible_state = not self.visible_state
        for w in self._all_stackable_windows():
            if self.visible_state:
                w.fade_in()
            else:
                w.fade_out()
        self._refresh_tray_labels()
        self.stateChanged.emit()

    def move_shortcut_between_groups(self, src_path: Path, target_group_key: str) -> Path | None:
        if target_group_key not in self.all_groups_meta or not src_path.exists():
            return None
        dest_folder = self.all_groups_meta[target_group_key][1]
        dest_path = dest_folder / src_path.name
        if dest_path.resolve() == src_path.resolve():
            return src_path

        old_rel = item_rel_key(src_path)
        try:
            shutil.move(str(src_path), str(dest_path))
        except Exception:
            shutil.copy2(str(src_path), str(dest_path))

        new_rel = item_rel_key(dest_path)
        if old_rel in self.custom_icons:
            self.custom_icons[new_rel] = self.custom_icons.pop(old_rel)
            self.icon_loader.set_custom_icons(self.custom_icons)
            self._save_config()

        self.reload_all_groups()
        self.stateChanged.emit()
        return dest_path

    def reload_all_groups(self):
        for w in self.windows:
            w.all_groups = self.all_groups_meta
            w.reload_items()
        self.reflow_vertical_stack()

    def handle_context_action(self, action_name: str):
        if action_name == "create_capsule":
            self.create_new_capsule_dialog()
        elif action_name == "toggle_memo":
            self.toggle_memo_card()
        elif action_name == "reset_layout":
            self.reset_to_left_golden_layout()
        elif action_name == "toggle_visibility":
            self.toggle_all_visibility()
        elif action_name == "pin_all":
            for c in self.cards:
                c.pinned = True
                c.expand_card()
                c.update()
            self._save_config()
            self.stateChanged.emit()
        elif action_name == "unpin_all":
            for c in self.cards:
                c.pinned = False
                c.collapse_card(force=True)
                c.update()
            self._save_config()
            self.stateChanged.emit()

    def is_autorun_enabled(self) -> bool:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTORUN_REG_PATH, 0, winreg.KEY_READ) as key:
                val, _ = winreg.QueryValueEx(key, AUTORUN_KEY_NAME)
                if not val:
                    return False
        except OSError:
            return False

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_APPROVED_REG_PATH, 0, winreg.KEY_READ) as skey:
                bval, _ = winreg.QueryValueEx(skey, AUTORUN_KEY_NAME)
                if isinstance(bval, bytes) and len(bval) > 0 and (bval[0] & 1) == 1:
                    return False
        except OSError:
            pass
        return True

    def _write_autorun_registry(self, checked: bool):
        if getattr(sys, "frozen", False):
            exe_cmd = f'"{sys.executable}" --autostart'
        else:
            exe_cmd = f'"{sys.executable}" "{Path(__file__).resolve()}" --autostart'

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTORUN_REG_PATH, 0, winreg.KEY_SET_VALUE) as key:
                if checked:
                    winreg.SetValueEx(key, AUTORUN_KEY_NAME, 0, winreg.REG_SZ, exe_cmd)
                else:
                    try:
                        winreg.DeleteValue(key, AUTORUN_KEY_NAME)
                    except OSError:
                        pass
            if checked:
                with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, STARTUP_APPROVED_REG_PATH, 0, winreg.KEY_SET_VALUE) as skey:
                    winreg.SetValueEx(skey, AUTORUN_KEY_NAME, 0, winreg.REG_BINARY, b"\x02" + b"\x00" * 11)
        except OSError:
            pass

    def set_autorun(self, checked: bool):
        self._write_autorun_registry(checked)
        self.stateChanged.emit()

    # =========================================================================
    # Clean, Slim System Tray Menu (heavy settings live in AuroraSettingsWindow)
    # =========================================================================
    def _setup_tray(self):
        icon_file = ICON_ICO_PATH if ICON_ICO_PATH.exists() else ICON_PNG_PATH
        tray_icon = QIcon(str(icon_file)) if icon_file.exists() else self.app.style().standardIcon(self.app.style().StandardPixmap.SP_DesktopIcon)

        self.tray = QSystemTrayIcon(tray_icon, self)

        self.update_checker = UpdateChecker(APP_VERSION, self)
        self.update_checker.checkStarted.connect(self._on_update_check_started)
        self.update_checker.checkFinished.connect(self._on_update_check_finished)
        self.update_checker.updateFound.connect(self._on_update_found)
        self.update_checker.upToDate.connect(self._on_update_up_to_date)
        self.update_checker.checkFailed.connect(self._on_update_check_failed)

        menu = QMenu()
        menu.setStyleSheet(MENU_QSS)

        self.act_settings = menu.addAction("⚙️ 打开主控台...")
        self.act_settings.triggered.connect(lambda: self.open_settings("general"))

        self.act_spot = menu.addAction("🔍 极光全局搜索")
        self.act_spot.triggered.connect(self.spotlight.toggle_spotlight)

        menu.addSeparator()

        self.act_memo_tray = menu.addAction("📝 极光速记便签")
        self.act_memo_tray.setCheckable(True)
        self.act_memo_tray.setChecked(self.show_memo)
        self.act_memo_tray.triggered.connect(self.set_show_memo)

        self.act_vis = menu.addAction("🙈 隐藏全部桌面卡片")
        self.act_vis.triggered.connect(self.toggle_all_visibility)

        menu.addSeparator()

        self.act_update = menu.addAction("🔄 检查更新")
        self.act_update.triggered.connect(self.update_checker.check)

        act_quit = menu.addAction("🚪 退出 AuroraDesktop")
        act_quit.triggered.connect(self.quit_app)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self._refresh_tray_labels()
        self.tray.show()

    def _refresh_tray_labels(self):
        spot_hk = self.hotkeys_cfg.get("spotlight", "")
        dbl_ctrl = self.hotkeys_cfg.get("double_ctrl_spotlight", True)
        spot_hints = []
        if dbl_ctrl:
            spot_hints.append("双击 Ctrl")
        if spot_hk:
            spot_hints.append(format_hotkey_label(spot_hk))
        spot_suffix = f" ({' / '.join(spot_hints)})" if spot_hints else ""

        tog_hk = self.hotkeys_cfg.get("toggle_cards", "")
        tog_suffix = f" ({format_hotkey_label(tog_hk)})" if tog_hk else ""

        if hasattr(self, "act_spot"):
            self.act_spot.setText(f"🔍 极光全局搜索{spot_suffix}")
        if hasattr(self, "act_vis"):
            verb = "🙈 隐藏全部桌面卡片" if self.visible_state else "✨ 显示全部桌面卡片"
            self.act_vis.setText(f"{verb}{tog_suffix}")
        if hasattr(self, "tray"):
            self.tray.setToolTip(
                f"Aurora Desktop v{APP_VERSION} · 极光毛玻璃桌面套件\n"
                f"全局搜索{spot_suffix or '：托盘唤出'} | 右键打开设置中心"
            )

    def _on_update_check_started(self):
        if hasattr(self, "act_update"):
            self.act_update.setEnabled(False)
            self.act_update.setText("⏳ 正在检查更新...")

    def _on_update_check_finished(self):
        if hasattr(self, "act_update"):
            self.act_update.setEnabled(True)
            self.act_update.setText("🔄 检查更新")

    def _show_update_box(self, title: str, text: str, icon=QMessageBox.Information, ask_open: bool = False) -> bool:
        parent = self.settings_win if (self.settings_win and self.settings_win.isVisible()) else None
        box = QMessageBox(parent)
        box.setStyleSheet(DIALOG_QSS)
        box.setIcon(icon)
        box.setWindowTitle(title)
        box.setText(text)
        if ask_open:
            btn_yes = box.addButton("前往下载页", QMessageBox.AcceptRole)
            box.addButton("稍后再说", QMessageBox.RejectRole)
            box.exec()
            return box.clickedButton() == btn_yes
        box.addButton("知道了", QMessageBox.AcceptRole)
        box.exec()
        return False

    def _on_update_found(self, tag: str, url: str):
        if self._show_update_box(
            "Aurora Desktop 更新",
            f"发现新版本 {tag}（当前 v{APP_VERSION}），是否前往下载页？",
            icon=QMessageBox.Information,
            ask_open=True,
        ):
            webbrowser.open(url)

    def _on_update_up_to_date(self):
        self._show_update_box("Aurora Desktop", f"当前 v{APP_VERSION} 已是最新版本 ✨")

    def _on_update_check_failed(self, err: str):
        self._show_update_box("Aurora Desktop", f"检查更新失败：{err}", icon=QMessageBox.Warning)

    def rescan_desktop_shortcuts(self) -> int:
        summary = scan_and_organize()
        self.reload_all_groups()
        self.stateChanged.emit()
        return sum(len(v) for v in summary.values())

    def _on_tray_activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.open_settings("general")
        elif reason == QSystemTrayIcon.MiddleClick:
            self.toggle_all_visibility()

    def quit_app(self):
        self.dbl_watcher.stop()
        self.ctrl_watcher.stop()
        self.hotkey_receiver.cleanup()
        if self.settings_win is not None:
            self.settings_win.close()
        self.spotlight.close()
        self.clock_widget.close()
        self.tray.hide()
        self.app.quit()


def acquire_single_instance_mutex(silent_autostart: bool = False) -> int:
    desk_name = "".join(ch if ch.isalnum() else "_" for ch in get_current_desktop_name())
    mutex_name = f"Local\\AuroraDesktop_SingleInstance_{desk_name}_v2"
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.wintypes.BOOL, ctypes.wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = ctypes.wintypes.HANDLE
    mutex = kernel32.CreateMutexW(None, False, mutex_name)
    ERROR_ALREADY_EXISTS = 183
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        if not silent_autostart and WM_AURORA_OPEN_PANEL:
            user32.AllowSetForegroundWindow(ASFW_ANY)
            user32.PostMessageW(HWND_BROADCAST, WM_AURORA_OPEN_PANEL, 0, 0)
        elif WM_AURORA_SHOW:
            user32.PostMessageW(HWND_BROADCAST, WM_AURORA_SHOW, 0, 0)
        sys.exit(0)
    return mutex


def main():
    silent_autostart = ("--autostart" in sys.argv or "--minimized" in sys.argv)
    _mutex = acquire_single_instance_mutex(silent_autostart=silent_autostart)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("AuroraDesktop")
    app.setStyleSheet("""
        QToolTip {
            background-color: rgba(14, 20, 36, 242);
            color: rgba(255, 255, 255, 248);
            border: 1px solid rgba(45, 212, 191, 130);
            border-radius: 8px;
            padding: 5px 10px;
            font-family: "Inter", "Noto Sans SC", "Microsoft YaHei UI";
            font-size: 11px;
            font-weight: 500;
        }
    """)

    if ICON_ICO_PATH.exists():
        app.setWindowIcon(QIcon(str(ICON_ICO_PATH)))

    controller = AuroraController(app, open_panel_on_start=(not silent_autostart))
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
