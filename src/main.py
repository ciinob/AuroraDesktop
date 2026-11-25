import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import winreg
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QObject, QTimer, Qt
from PySide6.QtGui import QAction, QFontDatabase, QGuiApplication, QIcon
from PySide6.QtWidgets import QApplication, QInputDialog, QMenu, QMessageBox, QSystemTrayIcon, QWidget

# Allow importing organize_shortcuts from project root or src
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from icon_extractor import ShortcutIconLoader
from organize_shortcuts import scan_and_organize
from paths import CONFIG_PATH, DATA_ROOT, FONTS_DIR, GROUPS_DIR, ICON_ICO_PATH, ICON_PNG_PATH
from widgets import (
    AICapsuleBar,
    AuroraBaseWindow,
    CollapsibleAuroraCard,
    DIALOG_QSS,
    MENU_QSS,
    NewCapsuleDialog,
    safe_remove_shortcut,
)
from win32_utils import (
    DesktopDoubleClickWatcher,
    HWND_BROADCAST,
    MOD_ALT,
    MOD_NOREPEAT,
    VK_OEM_3,
    WM_AURORA_SHOW,
    WM_HOTKEY,
    get_current_desktop_name,
    send_to_bottom,
    user32,
)

HOTKEY_ID_TOGGLE = 0xA001
AUTORUN_REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
AUTORUN_KEY_NAME = "AuroraDesktop"

DEFAULT_PARTITIONS = [
    {"key": "AI_CAPSULE", "title": "AI 悬浮胶囊栏", "folder": "01_AI_CAPSULE", "kind": "bar", "badge": "AI"},
    {"key": "RESEARCH_DEV", "title": "RESEARCH & DEV", "folder": "02_RESEARCH_DEV", "kind": "card"},
    {"key": "PLAY_SOCIAL", "title": "PLAY & SOCIAL", "folder": "03_PLAY_SOCIAL", "kind": "card"},
    {"key": "TOOLS_NET", "title": "TOOLS & NET", "folder": "04_TOOLS_NET", "kind": "card"},
]


class HotkeyReceiver(QWidget):
    """Hidden Win32 message receiver for global toggle hotkey (Alt + ~) and re-launch activation."""

    def __init__(self, on_toggle, on_force_show):
        super().__init__()
        self._on_toggle = on_toggle
        self._on_force_show = on_force_show
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint)
        self.resize(1, 1)
        hwnd = int(self.winId())
        user32.RegisterHotKey(hwnd, HOTKEY_ID_TOGGLE, MOD_ALT | MOD_NOREPEAT, VK_OEM_3)

    def nativeEvent(self, eventType, message):
        if eventType == b"windows_generic_MSG" or eventType == "windows_generic_MSG":
            msg = ctypes.wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID_TOGGLE:
                self._on_toggle()
                return True, 0
            elif WM_AURORA_SHOW and msg.message == WM_AURORA_SHOW:
                self._on_force_show()
                return True, 0
        return super().nativeEvent(eventType, message)

    def cleanup(self):
        user32.UnregisterHotKey(int(self.winId()), HOTKEY_ID_TOGGLE)


class AuroraController(QObject):
    """Coordinates dynamic capsules, layout reflow, filesystem watching, tray menu, and stealth."""

    LEFT_MARGIN = 24
    TOP_MARGIN = 24
    CARD_GAP = 10
    COL_GAP = 14

    def __init__(self, app: QApplication):
        super().__init__()
        self.app = app
        self.config = self._load_config()
        self.visible_state = True
        self.lock_positions = bool(self.config.get("lock_positions", False))
        self.dragged_keys: set[str] = set(self.config.get("dragged_keys", []))
        if self.config.get("custom_positions", False) and not self.dragged_keys:
            self.dragged_keys = set(self.config.get("positions", {}).keys())

        GROUPS_DIR.mkdir(parents=True, exist_ok=True)
        # First-run populate if Groups has no shortcut files yet
        if not any(GROUPS_DIR.rglob("*.lnk")):
            scan_and_organize()

        self.partitions: list[dict] = self._init_partitions()
        self.all_groups_meta: dict[str, tuple[str, Path]] = {}
        self._rebuild_groups_meta()

        # Load bundled Inter (Apple SF Pro twin) fonts + Noto Sans SC
        if FONTS_DIR.exists():
            for font_name in ("Inter-Regular.ttf", "Inter-Medium.ttf", "Inter-SemiBold.ttf"):
                fp = FONTS_DIR / font_name
                if fp.exists():
                    QFontDatabase.addApplicationFont(str(fp))
        self.header_font_family = "Inter"
        self.icon_loader = ShortcutIconLoader()

        self.windows: list[AuroraBaseWindow] = []
        self._build_all_windows()
        self._apply_initial_positions()

        # Watch Groups root + every partition folder for live updates and manually created folders
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
        self.dbl_watcher.start()

        # Global hotkey (Alt + ~) + re-launch show signal
        self.hotkey_receiver = HotkeyReceiver(self.toggle_all_visibility, self.force_show_and_showcase)

        # Periodic light z-order guard
        self.z_guard_timer = QTimer(self)
        self.z_guard_timer.setInterval(4000)
        self.z_guard_timer.timeout.connect(self._enforce_all_bottom)
        self.z_guard_timer.start()

        self._setup_tray()

        for w in self.windows:
            w.show()

        QTimer.singleShot(3500, self._initial_auto_collapse)

    @property
    def ai_bar(self):
        return self.windows[0] if self.windows else None

    @property
    def cards(self) -> list[CollapsibleAuroraCard]:
        return [w for w in self.windows if isinstance(w, CollapsibleAuroraCard)]

    def _init_partitions(self) -> list[dict]:
        saved = self.config.get("partitions")
        parts = [dict(p) for p in (saved if isinstance(saved, list) and saved else DEFAULT_PARTITIONS)]

        known_folders = {p["folder"].lower() for p in parts}
        for p in parts:
            (GROUPS_DIR / p["folder"]).mkdir(parents=True, exist_ok=True)

        # Also auto-discover any extra folders user manually created in D:\AuroraDesktop\Groups
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

    def _create_window_for_partition(self, p: dict) -> AuroraBaseWindow:
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
                group_key=g_key,
                title=title,
                badge_text=badge,
            )
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
            )
            win.heightAnimated.connect(self.reflow_vertical_stack)
            win.pinToggled.connect(self._on_pin_toggled)

        win.itemMoveRequested.connect(self.move_shortcut_between_groups)
        win.contextActionTriggered.connect(self.handle_context_action)
        win.renameCapsuleRequested.connect(self.rename_capsule_dialog)
        win.deleteCapsuleRequested.connect(self.delete_capsule_dialog)
        win.positionChangedByUser.connect(lambda k=g_key: self._on_user_dragged(k))
        return win

    def _build_all_windows(self):
        for w in self.windows:
            w.close()
            w.deleteLater()
        self.windows.clear()
        for p in self.partitions:
            self.windows.append(self._create_window_for_partition(p))

    def _load_config(self) -> dict:
        if CONFIG_PATH.exists():
            try:
                return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"pinned": {"RESEARCH_DEV": False, "PLAY_SOCIAL": False, "TOOLS_NET": False}}

    def _save_config(self):
        positions = {w.group_key: [w.x(), w.y()] for w in self.windows}
        pinned = {w.group_key: w.pinned for w in self.windows if isinstance(w, CollapsibleAuroraCard)}

        data = {
            "partitions": self.partitions,
            "pinned": pinned,
            "lock_positions": self.lock_positions,
            "dragged_keys": sorted(self.dragged_keys),
            "positions": positions,
        }
        CONFIG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _apply_initial_positions(self):
        saved_pos = self.config.get("positions", {})
        self.reflow_vertical_stack()
        for w in self.windows:
            if w.group_key in self.dragged_keys and w.group_key in saved_pos:
                wx, wy = saved_pos[w.group_key]
                w.move(wx, wy)

    def reset_to_left_golden_layout(self, save: bool = True):
        self.dragged_keys.clear()
        self.reflow_vertical_stack()
        if save:
            self._save_config()

    def reflow_vertical_stack(self):
        """Stack non-dragged capsules cleanly on the left; wrap to adjacent column if exceeding screen height."""
        screen = QGuiApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else None
        start_x = (avail.x() if avail else 0) + self.LEFT_MARGIN
        start_y = (avail.y() if avail else 0) + self.TOP_MARGIN
        max_bottom = (avail.bottom() - 12) if avail else 1380

        col_x = start_x
        curr_y = start_y

        for idx, w in enumerate(self.windows):
            if w.group_key in self.dragged_keys:
                continue
            if curr_y > start_y and (curr_y + w.height() > max_bottom):
                col_x += 356 + self.COL_GAP
                curr_y = start_y

            if w.x() != col_x or w.y() != curr_y:
                w.move(col_x, curr_y)
            extra_gap = 2 if idx == 0 else 0
            curr_y += w.height() + self.CARD_GAP + extra_gap

    def create_new_capsule_dialog(self):
        dlg = NewCapsuleDialog()
        if dlg.exec() != NewCapsuleDialog.Accepted:
            return
        title, kind = dlg.get_result()
        safe_slug = re.sub(r'[<>:"/\\|?*\s]+', "_", title).strip("_") or "Capsule"
        next_idx = len(self.partitions) + 1
        folder_name = f"{next_idx:02d}_{safe_slug}"
        while (GROUPS_DIR / folder_name).exists():
            next_idx += 1
            folder_name = f"{next_idx:02d}_{safe_slug}"

        key = f"CAP_{next_idx:02d}_{safe_slug.upper()}"
        part = {
            "key": key,
            "title": title,
            "folder": folder_name,
            "kind": kind,
        }
        if kind == "bar":
            part["badge"] = title[:2].upper()

        (GROUPS_DIR / folder_name).mkdir(parents=True, exist_ok=True)
        self.partitions.append(part)
        self._rebuild_groups_meta()
        self._sync_watcher_paths()

        win = self._create_window_for_partition(part)
        if isinstance(win, CollapsibleAuroraCard):
            # Keep newly created empty capsule expanded & pinned initially so user can drag apps right into it!
            win.pinned = True
        self.windows.append(win)
        self.reload_all_groups()
        self.reflow_vertical_stack()
        if self.visible_state:
            win.show()
        self._save_config()

    def rename_capsule_dialog(self, group_key: str):
        part = next((p for p in self.partitions if p["key"] == group_key), None)
        win = next((w for w in self.windows if w.group_key == group_key), None)
        if not part or not win:
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
            part["badge"] = new_title[:3]
            part["title"] = f"{new_title} 悬浮胶囊栏"
            win.badge_text = part["badge"]
            win.title = part["title"]
        else:
            part["title"] = new_title
            win.title = new_title

        self._rebuild_groups_meta()
        win.update()
        self.reload_all_groups()
        self._save_config()

    def delete_capsule_dialog(self, group_key: str):
        if len(self.partitions) <= 1:
            return
        part = next((p for p in self.partitions if p["key"] == group_key), None)
        win = next((w for w in self.windows if w.group_key == group_key), None)
        if not part or not win:
            return

        box = QMessageBox()
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
                if item.is_file():
                    safe_remove_shortcut(item)
            try:
                folder.rmdir()
            except OSError:
                pass

        self.partitions = [p for p in self.partitions if p["key"] != group_key]
        self.dragged_keys.discard(group_key)
        self.windows.remove(win)
        win.close()
        win.deleteLater()

        self._rebuild_groups_meta()
        self._sync_watcher_paths()
        self.reload_all_groups()
        self.reflow_vertical_stack()
        self._save_config()

    def _on_fs_changed(self):
        # Auto-discover if user created a brand-new subfolder inside D:\AuroraDesktop\Groups
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

    def _initial_auto_collapse(self):
        for c in self.cards:
            if not c.pinned and not c.underMouse():
                c.collapse_card()

    def _on_pin_toggled(self, group_key: str, pinned: bool):
        self._save_config()

    def _on_user_dragged(self, group_key: str):
        self.dragged_keys.add(group_key)
        self._save_config()

    def get_all_hwnds(self) -> set[int]:
        return {int(w.winId()) for w in self.windows}

    def _enforce_all_bottom(self):
        if not self.visible_state:
            return
        for w in self.windows:
            send_to_bottom(int(w.winId()))

    def force_show_and_showcase(self):
        """Called when user launches AuroraDesktop.exe again while already running."""
        if not self.visible_state:
            self.toggle_all_visibility()
        for c in self.cards:
            c.expand_card()
        QTimer.singleShot(4000, self._initial_auto_collapse)

    def toggle_all_visibility(self):
        self.visible_state = not self.visible_state
        for w in self.windows:
            if self.visible_state:
                w.fade_in()
            else:
                w.fade_out()
        if hasattr(self, "act_vis"):
            self.act_vis.setText("隐藏全部极光卡片 (Alt+~)" if self.visible_state else "显示全部极光卡片 (Alt+~)")

    def move_shortcut_between_groups(self, src_path: Path, target_group_key: str):
        if target_group_key not in self.all_groups_meta or not src_path.exists():
            return
        dest_folder = self.all_groups_meta[target_group_key][1]
        dest_path = dest_folder / src_path.name
        try:
            shutil.move(str(src_path), str(dest_path))
        except Exception:
            shutil.copy2(str(src_path), str(dest_path))
        self.reload_all_groups()

    def reload_all_groups(self):
        for w in self.windows:
            w.all_groups = self.all_groups_meta
            w.reload_items()
        self.reflow_vertical_stack()

    def handle_context_action(self, action_name: str):
        if action_name == "create_capsule":
            self.create_new_capsule_dialog()
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
        elif action_name == "unpin_all":
            for c in self.cards:
                c.pinned = False
                c.collapse_card(force=True)
                c.update()
            self._save_config()

    def _is_autorun_enabled(self) -> bool:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTORUN_REG_PATH, 0, winreg.KEY_READ) as key:
                val, _ = winreg.QueryValueEx(key, AUTORUN_KEY_NAME)
                return bool(val)
        except OSError:
            return False

    def _toggle_autorun(self, checked: bool):
        exe_cmd = f'"{sys.executable}"' if getattr(sys, "frozen", False) else f'"{sys.executable}" "{Path(__file__).resolve()}"'
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTORUN_REG_PATH, 0, winreg.KEY_SET_VALUE) as key:
                if checked:
                    winreg.SetValueEx(key, AUTORUN_KEY_NAME, 0, winreg.REG_SZ, exe_cmd)
                else:
                    try:
                        winreg.DeleteValue(key, AUTORUN_KEY_NAME)
                    except OSError:
                        pass
        except OSError:
            pass

    def _setup_tray(self):
        icon_file = ICON_ICO_PATH if ICON_ICO_PATH.exists() else ICON_PNG_PATH
        tray_icon = QIcon(str(icon_file)) if icon_file.exists() else self.app.style().standardIcon(self.app.style().StandardPixmap.SP_DesktopIcon)

        self.tray = QSystemTrayIcon(tray_icon, self)
        self.tray.setToolTip("AuroraDesktop · 极光毛玻璃桌面收纳\n单击托盘或双击桌面空白处切换隐身")

        menu = QMenu()
        menu.setStyleSheet(MENU_QSS)

        act_new = menu.addAction("➕ 新建极光胶囊分区...")
        act_new.triggered.connect(self.create_new_capsule_dialog)

        self.act_vis = menu.addAction("隐藏全部极光卡片 (Alt+~)")
        self.act_vis.triggered.connect(self.toggle_all_visibility)

        menu.addSeparator()
        act_pin_all = menu.addAction("全部展开并常驻")
        act_pin_all.triggered.connect(lambda: self.handle_context_action("pin_all"))

        act_collapse_all = menu.addAction("全部开启 0.5s 自动卷起")
        act_collapse_all.triggered.connect(lambda: self.handle_context_action("unpin_all"))

        act_lock = menu.addAction("锁定卡片位置")
        act_lock.setCheckable(True)
        act_lock.setChecked(self.lock_positions)
        act_lock.toggled.connect(self._on_lock_toggled)

        act_reset = menu.addAction("重置左侧山体黄金布局")
        act_reset.triggered.connect(lambda: self.reset_to_left_golden_layout(True))

        menu.addSeparator()
        act_rescan = menu.addAction("重新扫描同步桌面快捷方式")
        act_rescan.triggered.connect(self._rescan_desktop)

        act_open_dir = menu.addAction("打开映射总目录 (Groups)")
        act_open_dir.triggered.connect(lambda: subprocess.Popen(["explorer.exe", str(GROUPS_DIR)]))

        act_autorun = menu.addAction("开机自动启动")
        act_autorun.setCheckable(True)
        act_autorun.setChecked(self._is_autorun_enabled())
        act_autorun.toggled.connect(self._toggle_autorun)

        menu.addSeparator()
        act_quit = menu.addAction("退出 AuroraDesktop")
        act_quit.triggered.connect(self.quit_app)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _on_lock_toggled(self, checked: bool):
        self.lock_positions = checked
        self._save_config()

    def _rescan_desktop(self):
        scan_and_organize()
        self.reload_all_groups()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self.toggle_all_visibility()

    def quit_app(self):
        self.dbl_watcher.stop()
        self.hotkey_receiver.cleanup()
        self.tray.hide()
        self.app.quit()


def acquire_single_instance_mutex() -> int:
    """Prevent duplicate instances on the same Win32 desktop; wake existing instance if re-launched."""
    desk_name = "".join(ch if ch.isalnum() else "_" for ch in get_current_desktop_name())
    mutex_name = f"Local\\AuroraDesktop_SingleInstance_{desk_name}_v2"
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.wintypes.BOOL, ctypes.wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = ctypes.wintypes.HANDLE
    mutex = kernel32.CreateMutexW(None, False, mutex_name)
    ERROR_ALREADY_EXISTS = 183
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        if WM_AURORA_SHOW:
            user32.PostMessageW(HWND_BROADCAST, WM_AURORA_SHOW, 0, 0)
        sys.exit(0)
    return mutex


def main():
    _mutex = acquire_single_instance_mutex()
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

    controller = AuroraController(app)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
