import ctypes
from ctypes import wintypes
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QMimeData,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    QTimer,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QCursor,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QToolTip,
    QVBoxLayout,
    QWidget,
)
import win32com.client

from icon_extractor import ShortcutIconLoader, format_display_name
from paths import DATA_ROOT
from win32_utils import (
    ASFW_ANY,
    HWND_BOTTOM,
    MA_NOACTIVATE,
    SC_MINIMIZE,
    SWP_NOZORDER,
    WINDOWPOS,
    WM_MOUSEACTIVATE,
    WM_SYSCOMMAND,
    WM_WINDOWPOSCHANGING,
    apply_acrylic_and_rounded_corners,
    find_desktop_shell_host,
    pin_window_to_desktop_bottom,
    send_to_bottom,
    user32,
)

shell32 = ctypes.windll.shell32
shell32.ShellExecuteW.argtypes = [
    wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR,
    wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_int,
]
shell32.ShellExecuteW.restype = wintypes.HINSTANCE

# Priority ordering inside each group so user's core apps always appear first
PRIORITY_ORDER = {
    "AI_CAPSULE": ["gemini", "claude", "chatgpt", "deepseek", "grok"],
    "RESEARCH_DEV": [
        "matlab", "zotero", "visual studio code", "vscode", "antigravity",
        "数学知识图谱", "cc-switch", "workbuddy", "workdaddy",
        "word", "excel", "powerpoint", "wps", "腾讯会议",
    ],
    "PLAY_SOCIAL": [
        "steam", "rockstar", "plain craft launcher", "pcl", "暴雪战网", "wegame", "完美",
        "kook", "oopz", "qq", "微信", "telegram",
        "网易云音乐", "libretv", "短剧", "leagueakari", "pavise", "外星仔",
    ],
    "TOOLS_NET": [
        "clash verge", "proxyswitch", "cutecloud", "aria2", "夸克网盘", "edge",
        "剪映", "logitech", "inzone", "g-menu", "火绒", "图吧", "rainmeter", "translucenttb",
    ],
}

MENU_QSS = """
QMenu {
    background-color: rgba(16, 22, 38, 244);
    color: rgba(248, 250, 255, 242);
    border: 1px solid rgba(255, 255, 255, 38);
    border-radius: 11px;
    padding: 6px 5px;
    font-family: "Inter", "Noto Sans SC", "Microsoft YaHei UI";
    font-size: 12px;
    font-weight: 500;
}
QMenu::item {
    padding: 6px 22px 6px 14px;
    border-radius: 7px;
    margin: 1px 4px;
}
QMenu::item:selected {
    background-color: rgba(45, 212, 191, 56);
    color: #ffffff;
}
QMenu::separator {
    height: 1px;
    background: rgba(255, 255, 255, 22);
    margin: 5px 10px;
}
"""


DIALOG_QSS = """
QDialog, QMessageBox, QInputDialog {
    background-color: #101728;
    color: #f1f5f9;
    font-family: "Inter", "Noto Sans SC", "Microsoft YaHei UI";
    font-size: 13px;
}
QLabel {
    color: #e2e8f0;
    font-weight: 500;
}
QLineEdit, QComboBox {
    background-color: #1a243b;
    color: #ffffff;
    border: 1px solid rgba(45, 212, 191, 110);
    border-radius: 8px;
    padding: 7px 10px;
    font-family: "Inter", "Noto Sans SC", "Microsoft YaHei UI";
    font-size: 13px;
}
QComboBox::drop-down {
    border: none;
    width: 24px;
}
QComboBox QAbstractItemView {
    background-color: #162036;
    color: #f8fafc;
    selection-background-color: rgba(45, 212, 191, 70);
    border: 1px solid rgba(45, 212, 191, 100);
}
QPushButton {
    background-color: #1e293b;
    color: #e2e8f0;
    border: 1px solid rgba(255, 255, 255, 35);
    border-radius: 8px;
    padding: 6px 16px;
    font-weight: 500;
}
QPushButton:hover {
    background-color: #28354d;
}
QPushButton#primaryBtn {
    background-color: #14b8a6;
    color: #04131a;
    border: none;
    font-weight: 600;
}
QPushButton#primaryBtn:hover {
    background-color: #2dd4bf;
}
"""


class NewCapsuleDialog(QDialog):
    """Apple-dark styled modal dialog to create a new Aurora capsule card or compact bar."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("新建极光胶囊分区")
        self.setFixedSize(380, 210)
        self.setStyleSheet(DIALOG_QSS)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)

        lbl_name = QLabel("胶囊分区名称（支持中英文）：")
        self.edit_name = QLineEdit()
        self.edit_name.setPlaceholderText("例如：ACADEMIC / 文献阅读 / 常用设计")

        lbl_kind = QLabel("选择胶囊形态：")
        self.combo_kind = QComboBox()
        self.combo_kind.addItem("可折叠极光卡片（离开 0.5s 自动卷起为胶囊）", "card")
        self.combo_kind.addItem("横向单行悬浮胶囊栏（类似顶部 AI 栏，一触即达）", "bar")

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_cancel = QPushButton("取消")
        btn_ok = QPushButton("立即创建")
        btn_ok.setObjectName("primaryBtn")
        btn_ok.setDefault(True)
        btn_cancel.clicked.connect(self.reject)
        btn_ok.clicked.connect(self._on_accept)
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_ok)

        layout.addWidget(lbl_name)
        layout.addWidget(self.edit_name)
        layout.addWidget(lbl_kind)
        layout.addWidget(self.combo_kind)
        layout.addStretch(1)
        layout.addLayout(btn_row)

    def _on_accept(self):
        if not self.edit_name.text().strip():
            self.edit_name.setFocus()
            return
        self.accept()

    def get_result(self) -> tuple[str, str]:
        return self.edit_name.text().strip(), str(self.combo_kind.currentData())


def make_apple_font(pixel_size: int, weight: QFont.Weight = QFont.Medium, letter_spacing: float = 0.0) -> QFont:
    """Create Apple SF Pro + PingFang style font stack (Inter + Noto Sans SC)."""
    font = QFont()
    font.setFamilies(["Inter", "Noto Sans SC Medium", "Noto Sans SC", "Microsoft YaHei UI"])
    font.setPixelSize(pixel_size)
    font.setWeight(weight)
    font.setHintingPreference(QFont.PreferNoHinting)
    font.setStyleStrategy(QFont.PreferAntialias)
    if letter_spacing != 0.0:
        font.setLetterSpacing(QFont.AbsoluteSpacing, letter_spacing)
    return font


def sort_group_items(group_key: str, files: list[Path]) -> list[Path]:
    priorities = PRIORITY_ORDER.get(group_key, [])

    def rank(p: Path):
        stem = p.stem.lower()
        for idx, kw in enumerate(priorities):
            if kw in stem:
                return (0, idx, stem)
        return (1, 999, stem)

    return sorted(files, key=rank)


def _clean_pyinstaller_env() -> dict[str, str]:
    """Build clean environment without PyInstaller _MEIPASS overrides so launched apps never load wrong DLLs."""
    env = os.environ.copy()
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        meipass_norm = os.path.normcase(os.path.normpath(meipass))
        raw_path = env.get("PATH", "")
        cleaned_parts = [
            p for p in raw_path.split(os.pathsep)
            if p and not os.path.normcase(os.path.normpath(p)).startswith(meipass_norm)
        ]
        env["PATH"] = os.pathsep.join(cleaned_parts)

    for k in ("QT_PLUGIN_PATH", "QML2_IMPORT_PATH", "_MEIPASS2", "PYTHONPATH", "PYTHONHOME"):
        env.pop(k, None)
    return env


def launch_item(path: Path, run_as_admin: bool = False):
    """Launch shortcut or executable cleanly in foreground without PyInstaller DLL pollution."""
    if not path.exists():
        return

    user32.AllowSetForegroundWindow(ASFW_ANY)

    # Temporarily sanitize current process env around ShellExecuteW / startfile
    saved_env = {}
    meipass = getattr(sys, "_MEIPASS", None)
    keys_to_strip = ("QT_PLUGIN_PATH", "QML2_IMPORT_PATH", "_MEIPASS2", "PYTHONPATH", "PYTHONHOME")
    for k in keys_to_strip:
        if k in os.environ:
            saved_env[k] = os.environ.pop(k)

    orig_path = os.environ.get("PATH", "")
    if meipass:
        meipass_norm = os.path.normcase(os.path.normpath(meipass))
        os.environ["PATH"] = os.pathsep.join(
            p for p in orig_path.split(os.pathsep)
            if p and not os.path.normcase(os.path.normpath(p)).startswith(meipass_norm)
        )

    try:
        if run_as_admin:
            shell32.ShellExecuteW(None, "runas", str(path), None, str(path.parent), 1)
        else:
            # Passing None (NULL verb) invokes the true default shell verb on all .lnk / MSI / AppX shortcuts!
            res = shell32.ShellExecuteW(None, None, str(path), None, None, 1)
            if int(res) <= 32:
                os.startfile(str(path))
    except Exception:
        try:
            subprocess.Popen(["explorer.exe", str(path)], env=_clean_pyinstaller_env())
        except Exception:
            pass
    finally:
        os.environ["PATH"] = orig_path
        for k, v in saved_env.items():
            os.environ[k] = v


def open_target_location(path: Path, icon_loader: ShortcutIconLoader):
    target = icon_loader.resolve_target_path(path)
    if target and os.path.exists(target):
        subprocess.Popen(["explorer.exe", f"/select,{target}"])
    else:
        subprocess.Popen(["explorer.exe", f"/select,{path}"])


HIDDEN_SKIP_FILES = {"desktop.ini", "thumbs.db", ".ds_store"}


def list_valid_partition_items(folder_path: Path) -> list[Path]:
    """List all user items in a partition folder: shortcuts, apps, PDFs, images, docs, and folders!"""
    if not folder_path.exists():
        return []
    items = []
    for p in folder_path.iterdir():
        if p.name.lower() in HIDDEN_SKIP_FILES or p.name.startswith("."):
            continue
        items.append(p)
    return items


def import_item_into_group_folder(src_path: Path, dest_folder: Path):
    """Add any .lnk/.url (copy) or any PDF/image/doc/folder/exe (create lightweight .lnk shortcut) into dest_folder."""
    if not src_path.exists():
        return
    dest_folder.mkdir(parents=True, exist_ok=True)
    # Ignore if dragged from inside the exact same folder
    if src_path.parent.resolve() == dest_folder.resolve():
        return

    ext = src_path.suffix.lower()
    if ext in (".lnk", ".url"):
        shutil.copy2(str(src_path), str(dest_folder / src_path.name))
    else:
        # Keep non-exe extension in shortcut name (e.g. meng2016.pdf.lnk -> displays as meng2016.pdf!)
        base_label = src_path.stem if ext in (".exe", ".bat", ".cmd") else src_path.name
        lnk_path = dest_folder / f"{base_label}.lnk"
        shell = win32com.client.Dispatch("WScript.Shell")
        sc = shell.CreateShortcut(str(lnk_path))
        sc.TargetPath = str(src_path)
        sc.WorkingDirectory = str(src_path.parent if src_path.is_file() else src_path)
        sc.Save()


def safe_remove_shortcut(item_path: Path):
    """Safely remove item from card by moving it into D:\\AuroraDesktop\\Removed_Backup (never deletes user files)."""
    if not item_path.exists():
        return
    backup_dir = DATA_ROOT / "Removed_Backup"
    backup_dir.mkdir(parents=True, exist_ok=True)
    dest = backup_dir / item_path.name
    if dest.exists():
        if dest.is_dir():
            shutil.rmtree(str(dest), ignore_errors=True)
        else:
            dest.unlink()
    shutil.move(str(item_path), str(dest))


def prompt_add_items_to_folder(parent: QWidget, dest_folder: Path) -> bool:
    """Open native file picker supporting ALL files: images, PDFs, Office docs, apps, and shortcuts."""
    files, _ = QFileDialog.getOpenFileNames(
        parent,
        "选择要添加的文件（支持图片、PDF、文档、程序、快捷方式）",
        str(Path.home() / "Desktop"),
        "所有支持文件 (*.*);;图片与 PDF (*.png *.jpg *.jpeg *.webp *.gif *.bmp *.pdf);;办公文档 (*.pdf *.doc *.docx *.xls *.xlsx *.ppt *.pptx *.txt *.md);;程序与快捷方式 (*.lnk *.exe *.url *.bat)",
    )
    if not files:
        return False
    for f in files:
        import_item_into_group_folder(Path(f), dest_folder)
    return True


def prompt_add_directory_to_folder(parent: QWidget, dest_folder: Path) -> bool:
    """Open native folder picker to add a folder shortcut (e.g. 文献) into a partition."""
    chosen_dir = QFileDialog.getExistingDirectory(
        parent,
        "选择要添加到此极光分区的文件夹",
        str(Path.home() / "Desktop"),
    )
    if not chosen_dir:
        return False
    import_item_into_group_folder(Path(chosen_dir), dest_folder)
    return True


class AuroraIconTile(QWidget):
    """Individual minimalist icon tile with hover aurora glow, crisp typography, and context menu."""
    moveRequested = Signal(Path, str)
    hoverNameChanged = Signal(str)
    refreshRequested = Signal()

    def __init__(
        self,
        item_path: Path,
        icon_loader: ShortcutIconLoader,
        compact_capsule: bool = False,
        all_groups: dict[str, tuple[str, Path]] | None = None,
        current_group_key: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self.item_path = item_path
        self.icon_loader = icon_loader
        self.compact_capsule = compact_capsule
        self.all_groups = all_groups or {}
        self.current_group_key = current_group_key

        self.short_name, self.full_name = format_display_name(item_path)
        self.icon_size = 34 if compact_capsule else 36
        self.pixmap: QPixmap = icon_loader.get_icon_pixmap(item_path, self.icon_size * 2)

        if compact_capsule:
            self.setFixedSize(58, 52)
        else:
            self.setFixedSize(64, 68)

        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)

        self._hover_progress = 0.0
        self._press_scale = 1.0
        self._last_launch_ts = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._on_anim_val)

        # Crisp tooltip for full name
        self.setToolTip(self.full_name)

    def _on_anim_val(self, val):
        self._hover_progress = float(val)
        self.update()

    def enterEvent(self, event):
        self._anim.stop()
        self._anim.setStartValue(self._hover_progress)
        self._anim.setEndValue(1.0)
        self._anim.start()
        self.hoverNameChanged.emit(self.full_name)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._anim.stop()
        self._anim.setStartValue(self._hover_progress)
        self._anim.setEndValue(0.0)
        self._anim.start()
        self.hoverNameChanged.emit("")
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._press_scale = 0.92
            self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            was_pressed = self._press_scale < 1.0
            self._press_scale = 1.0
            self.update()
            if was_pressed and self.rect().contains(event.position().toPoint()):
                now = time.monotonic()
                # Debounce 600ms so both single-click and habitual double-click launch cleanly once
                if now - self._last_launch_ts > 0.6:
                    self._last_launch_ts = now
                    launch_item(self.item_path)
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event):
        parent_card = self.window()
        if hasattr(parent_card, "set_menu_open"):
            parent_card.set_menu_open(True)

        menu = QMenu(self)
        menu.setStyleSheet(MENU_QSS)

        act_open = menu.addAction(f"打开 {self.short_name}")
        act_admin = menu.addAction("以管理员身份运行")
        act_loc = menu.addAction("打开文件所在位置")
        menu.addSeparator()

        move_menu = menu.addMenu("移至其他极光分区")
        move_menu.setStyleSheet(MENU_QSS)
        move_actions: dict[QAction, str] = {}
        for g_key, (g_title, _) in self.all_groups.items():
            if g_key != self.current_group_key:
                a = move_menu.addAction(g_title)
                move_actions[a] = g_key

        act_rename = menu.addAction("重命名显示名称...")
        menu.addSeparator()
        act_remove = menu.addAction("从此分区移除图标")

        chosen = menu.exec(event.globalPos())
        if hasattr(parent_card, "set_menu_open"):
            parent_card.set_menu_open(False)

        if chosen == act_open:
            launch_item(self.item_path)
        elif chosen == act_admin:
            launch_item(self.item_path, run_as_admin=True)
        elif chosen == act_loc:
            open_target_location(self.item_path, self.icon_loader)
        elif chosen in move_actions:
            self.moveRequested.emit(self.item_path, move_actions[chosen])
        elif chosen == act_rename:
            new_name, ok = QInputDialog.getText(
                None, "重命名快捷方式", "请输入新的显示名称：", text=self.short_name
            )
            new_name = new_name.strip()
            if ok and new_name:
                invalid_chars = '<>:"/\\|?*'
                for ch in invalid_chars:
                    new_name = new_name.replace(ch, "")
                if new_name:
                    new_path = self.item_path.with_name(f"{new_name}{self.item_path.suffix}")
                    if new_path != self.item_path and not new_path.exists():
                        self.item_path.rename(new_path)
                        if hasattr(parent_card, "reload_items"):
                            parent_card.reload_items()
        elif chosen == act_remove:
            safe_remove_shortcut(self.item_path)
            if hasattr(parent_card, "reload_items"):
                parent_card.reload_items()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing)

        w, h = self.width(), self.height()
        p = self._hover_progress

        # Subtle hover aurora glass highlight pill
        if p > 0.01:
            bg_rect = QRectF(2.0, 2.0, w - 4.0, h - 4.0)
            grad = QLinearGradient(bg_rect.topLeft(), bg_rect.bottomRight())
            grad.setColorAt(0.0, QColor(45, 212, 191, int(38 * p)))
            grad.setColorAt(1.0, QColor(168, 85, 247, int(34 * p)))
            painter.setBrush(grad)
            pen = QPen(QColor(45, 212, 191, int(90 * p)), 1.0)
            painter.setPen(pen)
            painter.drawRoundedRect(bg_rect, 10.0, 10.0)

        # Draw crisp icon with gentle 2px hover lift
        lift = -2.0 * p
        isz = self.icon_size * self._press_scale
        ix = (w - isz) / 2.0
        iy = (4.0 if self.compact_capsule else 6.0) + lift + (self.icon_size - isz) / 2.0

        if not self.pixmap.isNull():
            painter.drawPixmap(QRectF(ix, iy, isz, isz), self.pixmap, QRectF(self.pixmap.rect()))

        # Draw Apple macOS/iOS style crisp caption below icon (Medium weight + subtle 1px drop shadow)
        font = make_apple_font(10 if self.compact_capsule else 11, QFont.Medium, -0.1)
        painter.setFont(font)

        fm = QFontMetrics(font)
        max_tw = w - 2
        elided = fm.elidedText(self.short_name, Qt.ElideRight, max_tw)
        ty = h - (15 if self.compact_capsule else 19)
        text_rect = QRectF(1.0, ty, w - 2.0, 16.0)
        shadow_rect = QRectF(1.0, ty + 1.0, w - 2.0, 16.0)

        # Subtle dark shadow for high contrast over bright/aurora wallpapers
        painter.setPen(QColor(0, 0, 0, 135))
        painter.drawText(shadow_rect, Qt.AlignHCenter | Qt.AlignVCenter, elided)

        text_alpha = int(222 + 33 * p) if self.compact_capsule else int(232 + 23 * p)
        painter.setPen(QColor(255, 255, 255, text_alpha))
        painter.drawText(text_rect, Qt.AlignHCenter | Qt.AlignVCenter, elided)


class AuroraBaseWindow(QWidget):
    """Frameless desktop-pinned Windows 11 Acrylic card with 1px Northern Lights gradient border."""
    positionChangedByUser = Signal()

    RADIUS = 14.0
    GLASS_BG = QColor(10, 15, 28, 135)  # Exact user spec: rgba(10, 15, 28, 135)
    EMERALD = QColor("#2dd4bf")         # Exact user spec: #2dd4bf
    CYAN_MID = QColor("#38bdf8")
    PURPLE = QColor("#a855f7")          # Exact user spec: #a855f7

    def __init__(self, allow_drag_provider=None, parent=None):
        super().__init__(parent)
        self._allow_drag_provider = allow_drag_provider or (lambda: True)
        self._acrylic_initialized = False
        self._menu_open = False
        self._dragging = False
        self._drag_offset = QPoint()

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMouseTracking(True)

        # Hover border luminance animation (silent low brightness -> glowing aurora hover)
        self._border_glow = 0.0
        self._glow_anim = QVariantAnimation(self)
        self._glow_anim.setDuration(240)
        self._glow_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._glow_anim.valueChanged.connect(self._on_glow_changed)

        # Window opacity animation for 1-click fade hide/show
        self._fade_anim = QVariantAnimation(self)
        self._fade_anim.setDuration(240)
        self._fade_anim.setEasingCurve(QEasingCurve.InOutCubic)
        self._fade_anim.valueChanged.connect(self._on_fade_val)
        self._fade_anim.finished.connect(self._on_fade_finished)
        self._hiding_after_fade = False

    def _on_glow_changed(self, val):
        self._border_glow = float(val)
        self.update()

    def _on_fade_val(self, val):
        self.setWindowOpacity(float(val))

    def _on_fade_finished(self):
        if self._hiding_after_fade:
            self.hide()
            self._hiding_after_fade = False
        else:
            send_to_bottom(int(self.winId()))

    def fade_out(self):
        if not self.isVisible():
            return
        self._hiding_after_fade = True
        self._fade_anim.stop()
        self._fade_anim.setStartValue(self.windowOpacity())
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.start()

    def fade_in(self):
        self._hiding_after_fade = False
        if not self.isVisible():
            self.setWindowOpacity(0.0)
            self.show()
            self.ensure_native_desktop_style()
        self._fade_anim.stop()
        self._fade_anim.setStartValue(self.windowOpacity())
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.start()

    def ensure_native_desktop_style(self):
        hwnd = int(self.winId())
        apply_acrylic_and_rounded_corners(hwnd)
        pin_window_to_desktop_bottom(hwnd)
        self._acrylic_initialized = True

    def showEvent(self, event):
        super().showEvent(event)
        if not self._acrylic_initialized:
            QTimer.singleShot(10, self.ensure_native_desktop_style)
        else:
            send_to_bottom(int(self.winId()))

    def enterEvent(self, event):
        self._glow_anim.stop()
        self._glow_anim.setStartValue(self._border_glow)
        self._glow_anim.setEndValue(1.0)
        self._glow_anim.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        if not self._menu_open:
            self._glow_anim.stop()
            self._glow_anim.setStartValue(self._border_glow)
            self._glow_anim.setEndValue(0.0)
            self._glow_anim.start()
        super().leaveEvent(event)

    def set_menu_open(self, is_open: bool):
        self._menu_open = is_open
        if not is_open and not self.underMouse():
            self._glow_anim.stop()
            self._glow_anim.setStartValue(self._border_glow)
            self._glow_anim.setEndValue(0.0)
            self._glow_anim.start()

    def nativeEvent(self, eventType, message):
        if eventType == b"windows_generic_MSG" or eventType == "windows_generic_MSG":
            msg = ctypes.wintypes.MSG.from_address(int(message))
            if msg.message == WM_SYSCOMMAND:
                # Never minimize on Win+D or Minimize-All
                if (msg.wParam & 0xFFF0) == SC_MINIMIZE:
                    return True, 0
            elif msg.message == WM_MOUSEACTIVATE:
                # Clicking an icon/card never activates or raises card above normal apps
                return True, MA_NOACTIVATE
        return super().nativeEvent(eventType, message)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)

        rect = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        path = QPainterPath()
        path.addRoundedRect(rect, self.RADIUS, self.RADIUS)

        # 1. Deep high-transparency glass fill: rgba(10, 15, 28, 135)
        painter.fillPath(path, self.GLASS_BG)

        # 2. Subtle top-edge specular frost sheen for realistic glass depth
        sheen = QLinearGradient(0, 0, 0, min(44.0, self.height()))
        sheen.setColorAt(0.0, QColor(255, 255, 255, int(10 + 10 * self._border_glow)))
        sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.fillPath(path, sheen)

        # 3. 1px Northern Lights gradient border (#2dd4bf -> #a855f7)
        # Silent low brightness at rest (alpha ~64), glowing aurora on hover (alpha ~215)
        g = self._border_glow
        alpha_main = int(64 + 151 * g)
        alpha_mid = int(42 + 125 * g)

        c_emerald = QColor(self.EMERALD)
        c_emerald.setAlpha(alpha_main)
        c_mid = QColor(self.CYAN_MID)
        c_mid.setAlpha(alpha_mid)
        c_purple = QColor(self.PURPLE)
        c_purple.setAlpha(alpha_main)

        # Subtle aurora angle shift on hover
        shift = 28.0 * g
        border_grad = QLinearGradient(
            QPointF(rect.left() + shift, rect.top()),
            QPointF(rect.right() - shift, rect.bottom()),
        )
        border_grad.setColorAt(0.0, c_emerald)
        border_grad.setColorAt(0.5, c_mid)
        border_grad.setColorAt(1.0, c_purple)

        pen = QPen(border_grad, 1.0)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)


class AICapsuleBar(AuroraBaseWindow):
    """Compact horizontal single-row Aurora Capsule Bar (used for AI Capsule and custom horizontal bars)."""
    itemMoveRequested = Signal(Path, str)
    contextActionTriggered = Signal(str)
    renameCapsuleRequested = Signal(str)
    deleteCapsuleRequested = Signal(str)

    CARD_WIDTH = 356
    CARD_HEIGHT = 66

    def __init__(
        self,
        folder_path: Path,
        icon_loader: ShortcutIconLoader,
        header_font_family: str,
        all_groups: dict[str, tuple[str, Path]],
        allow_drag_provider=None,
        group_key: str = "AI_CAPSULE",
        title: str = "AI 悬浮胶囊栏",
        badge_text: str = "AI",
    ):
        super().__init__(allow_drag_provider=allow_drag_provider)
        self.group_key = group_key
        self.title = title
        self.badge_text = badge_text
        self.folder_path = folder_path
        self.icon_loader = icon_loader
        self.header_font_family = header_font_family
        self.all_groups = all_groups

        self.setFixedSize(self.CARD_WIDTH, self.CARD_HEIGHT)
        self.setAcceptDrops(True)

        self._row_container = QWidget(self)
        self._row_layout = QHBoxLayout(self._row_container)
        self._row_layout.setContentsMargins(58, 7, 10, 7)
        self._row_layout.setSpacing(3)
        self._row_container.setGeometry(0, 0, self.CARD_WIDTH, self.CARD_HEIGHT)

        self.reload_items()

    def reload_items(self):
        while self._row_layout.count():
            item = self._row_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        files = list_valid_partition_items(self.folder_path)
        files = sort_group_items(self.group_key, files)

        # Dynamically adapt width if user ever adds >5 AI icons
        needed_w = max(self.CARD_WIDTH, 62 + len(files) * 59)
        self.setFixedSize(needed_w, self.CARD_HEIGHT)
        self._row_container.setGeometry(0, 0, needed_w, self.CARD_HEIGHT)

        for f in files:
            tile = AuroraIconTile(
                f,
                self.icon_loader,
                compact_capsule=True,
                all_groups=self.all_groups,
                current_group_key=self.group_key,
                parent=self._row_container,
            )
            tile.moveRequested.connect(self.itemMoveRequested.emit)
            self._row_layout.addWidget(tile)

        self._row_layout.addStretch(1)
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and event.position().x() < 52 and self._allow_drag_provider():
            self._dragging = True
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging and (event.buttons() & Qt.LeftButton):
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            self.positionChangedByUser.emit()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._dragging = False
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event):
        self.set_menu_open(True)
        menu = QMenu(self)
        menu.setStyleSheet(MENU_QSS)
        act_new_cap = menu.addAction("➕ 新建极光胶囊分区...")
        act_add = menu.addAction("添加文件 / 图片 / PDF / 应用...")
        act_add_dir = menu.addAction("添加文件夹到此栏...")
        act_folder = menu.addAction(f"打开映射文件夹 ({self.folder_path.name})")
        act_refresh = menu.addAction("刷新分区图标")
        menu.addSeparator()
        act_rename_cap = menu.addAction("重命名此胶囊徽标...")
        act_del_cap = menu.addAction("删除此极光胶囊...")
        menu.addSeparator()
        act_reset = menu.addAction("重置左侧山体黄金布局")
        act_hide = menu.addAction("淡出隐藏全部卡片 (双击桌面恢复)")

        chosen = menu.exec(event.globalPos())
        self.set_menu_open(False)
        if chosen == act_new_cap:
            self.contextActionTriggered.emit("create_capsule")
        elif chosen == act_add:
            if prompt_add_items_to_folder(self, self.folder_path):
                self.reload_items()
        elif chosen == act_add_dir:
            if prompt_add_directory_to_folder(self, self.folder_path):
                self.reload_items()
        elif chosen == act_folder:
            subprocess.Popen(["explorer.exe", str(self.folder_path)])
        elif chosen == act_refresh:
            self.reload_items()
        elif chosen == act_rename_cap:
            self.renameCapsuleRequested.emit(self.group_key)
        elif chosen == act_del_cap:
            self.deleteCapsuleRequested.emit(self.group_key)
        elif chosen == act_reset:
            self.contextActionTriggered.emit("reset_layout")
        elif chosen == act_hide:
            self.contextActionTriggered.emit("toggle_visibility")

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            local = Path(url.toLocalFile())
            if local.exists():
                import_item_into_group_folder(local, self.folder_path)
        self.reload_items()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)

        # Left vertical minimalist aurora badge + subtle divider
        badge_rect = QRectF(10.0, 14.0, 36.0, self.height() - 28.0)
        grad = QLinearGradient(badge_rect.topLeft(), badge_rect.bottomRight())
        grad.setColorAt(0.0, QColor(45, 212, 191, int(45 + 45 * self._border_glow)))
        grad.setColorAt(1.0, QColor(168, 85, 247, int(45 + 45 * self._border_glow)))
        painter.setBrush(grad)
        painter.setPen(QPen(QColor(45, 212, 191, int(95 + 75 * self._border_glow)), 1.0))
        painter.drawRoundedRect(badge_rect, 8.0, 8.0)

        disp_badge = self.badge_text[:3]
        font = make_apple_font(11 if len(disp_badge) >= 3 else 12, QFont.DemiBold, 0.3)
        painter.setFont(font)
        painter.setPen(QColor(0, 0, 0, 110))
        painter.drawText(badge_rect.translated(0, 1.0), Qt.AlignCenter, disp_badge)
        painter.setPen(QColor(255, 255, 255, 248))
        painter.drawText(badge_rect, Qt.AlignCenter, disp_badge)

        # Hairline vertical separator
        painter.setPen(QPen(QColor(255, 255, 255, 24), 1.0))
        painter.drawLine(QPointF(52.5, 15.0), QPointF(52.5, self.height() - 15.0))


class CollapsibleAuroraCard(AuroraBaseWindow):
    """Collapsible Aurora glass partition card: smoothly rolls up into a slender 38px Aurora capsule 0.5s after mouse leave."""
    heightAnimated = Signal()
    pinToggled = Signal(str, bool)
    itemMoveRequested = Signal(Path, str)
    contextActionTriggered = Signal(str)
    renameCapsuleRequested = Signal(str)
    deleteCapsuleRequested = Signal(str)

    CARD_WIDTH = 356
    HEADER_HEIGHT = 38
    COLS = 5
    TILE_W = 64
    TILE_H = 68
    GRID_PAD_X = 12
    GRID_PAD_BOTTOM = 12
    GRID_SPACING_X = 3
    GRID_SPACING_Y = 4

    def __init__(
        self,
        group_key: str,
        title: str,
        folder_path: Path,
        icon_loader: ShortcutIconLoader,
        header_font_family: str,
        all_groups: dict[str, tuple[str, Path]],
        pinned: bool = False,
        allow_drag_provider=None,
    ):
        super().__init__(allow_drag_provider=allow_drag_provider)
        self.group_key = group_key
        self.title = title
        self.folder_path = folder_path
        self.icon_loader = icon_loader
        self.header_font_family = header_font_family
        self.all_groups = all_groups
        self.pinned = pinned

        self._expanded = True
        self._item_count = 0
        self._hovered_item_label = ""
        self._expanded_height = 180
        self._pin_rect = QRectF(self.CARD_WIDTH - 34, 9, 20, 20)
        self._hover_pin = False

        self.setFixedWidth(self.CARD_WIDTH)
        self.setAcceptDrops(True)

        self._grid_container = QWidget(self)
        self._grid_container.setMouseTracking(True)

        # Smooth roll-up / expand animation
        self._height_anim = QVariantAnimation(self)
        self._height_anim.setDuration(230)
        self._height_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._height_anim.valueChanged.connect(self._on_height_val)

        # Exact 0.5s (500ms) auto-roll-up timer on mouse leave
        self._collapse_timer = QTimer(self)
        self._collapse_timer.setSingleShot(True)
        self._collapse_timer.setInterval(500)
        self._collapse_timer.timeout.connect(self._on_collapse_timeout)

        self.reload_items()
        self.setFixedHeight(self._expanded_height)

    def reload_items(self):
        for child in self._grid_container.findChildren(AuroraIconTile):
            child.deleteLater()

        files = list_valid_partition_items(self.folder_path)
        files = sort_group_items(self.group_key, files)
        self._item_count = len(files)

        rows = max(1, math.ceil(len(files) / self.COLS))
        grid_h = rows * self.TILE_H + max(0, rows - 1) * self.GRID_SPACING_Y + self.GRID_PAD_BOTTOM
        self._expanded_height = self.HEADER_HEIGHT + grid_h
        self._grid_container.setGeometry(0, self.HEADER_HEIGHT, self.CARD_WIDTH, grid_h)

        for idx, f in enumerate(files):
            r = idx // self.COLS
            c = idx % self.COLS
            tile = AuroraIconTile(
                f,
                self.icon_loader,
                compact_capsule=False,
                all_groups=self.all_groups,
                current_group_key=self.group_key,
                parent=self._grid_container,
            )
            x = self.GRID_PAD_X + c * (self.TILE_W + self.GRID_SPACING_X)
            y = r * (self.TILE_H + self.GRID_SPACING_Y)
            tile.move(x, y)
            tile.show()
            tile.moveRequested.connect(self.itemMoveRequested.emit)
            tile.hoverNameChanged.connect(self._on_tile_hovered)

        if self._expanded:
            self.setFixedHeight(self._expanded_height)
            self._grid_container.setVisible(True)
            self.heightAnimated.emit()
        self.update()

    def _on_tile_hovered(self, full_name: str):
        self._hovered_item_label = full_name
        self.update()

    def _on_height_val(self, val):
        h = int(val)
        self.setFixedHeight(h)
        self._grid_container.setVisible(h > self.HEADER_HEIGHT + 6)
        self.heightAnimated.emit()

    def expand_card(self):
        self._collapse_timer.stop()
        if self._expanded and self.height() == self._expanded_height:
            return
        self._expanded = True
        self._grid_container.setVisible(True)
        self._height_anim.stop()
        self._height_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._height_anim.setDuration(220)
        self._height_anim.setStartValue(self.height())
        self._height_anim.setEndValue(self._expanded_height)
        self._height_anim.start()

    def collapse_card(self, force: bool = False):
        if (self.pinned or self._menu_open) and not force:
            return
        if not self._expanded and self.height() == self.HEADER_HEIGHT:
            return
        self._expanded = False
        self._height_anim.stop()
        self._height_anim.setEasingCurve(QEasingCurve.InOutCubic)
        self._height_anim.setDuration(240)
        self._height_anim.setStartValue(self.height())
        self._height_anim.setEndValue(self.HEADER_HEIGHT)
        self._height_anim.start()

    def _on_collapse_timeout(self):
        if not self.underMouse() and not self._menu_open and not self.pinned:
            self.collapse_card()

    def enterEvent(self, event):
        self._collapse_timer.stop()
        self.expand_card()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover_pin = False
        if not self.pinned and not self._menu_open:
            self._collapse_timer.start(500)
        super().leaveEvent(event)

    def set_menu_open(self, is_open: bool):
        super().set_menu_open(is_open)
        if not is_open and not self.underMouse() and not self.pinned:
            self._collapse_timer.start(500)

    def mouseMoveEvent(self, event):
        pos = event.position()
        was_hover_pin = self._hover_pin
        self._hover_pin = self._pin_rect.contains(pos)
        if self._hover_pin != was_hover_pin:
            self.setCursor(Qt.PointingHandCursor if self._hover_pin else Qt.ArrowCursor)
            self.update()

        if self._dragging and (event.buttons() & Qt.LeftButton):
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            self.positionChangedByUser.emit()
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            pos = event.position()
            if self._pin_rect.contains(pos):
                self.pinned = not self.pinned
                self.pinToggled.emit(self.group_key, self.pinned)
                self.update()
                return
            if pos.y() <= self.HEADER_HEIGHT and self._allow_drag_provider():
                self._dragging = True
                self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton and event.position().y() <= self.HEADER_HEIGHT:
            if self._expanded:
                self.pinned = False
                self.pinToggled.emit(self.group_key, False)
                self.collapse_card(force=True)
            else:
                self.expand_card()
        super().mouseDoubleClickEvent(event)

    def mouseReleaseEvent(self, event):
        self._dragging = False
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event):
        self.set_menu_open(True)
        menu = QMenu(self)
        menu.setStyleSheet(MENU_QSS)

        pin_label = "取消常驻展开 (恢复 0.5s 自动卷起)" if self.pinned else "常驻展开此卡片 (不自动卷起)"
        act_pin = menu.addAction(pin_label)
        act_toggle = menu.addAction("立即卷起为胶囊" if self._expanded else "展开卡片")
        menu.addSeparator()
        act_new_cap = menu.addAction("➕ 新建极光胶囊分区...")
        act_add = menu.addAction("添加文件 / 图片 / PDF / 应用...")
        act_add_dir = menu.addAction("添加文件夹到此分区...")
        act_folder = menu.addAction(f"打开映射文件夹 ({self.folder_path.name})")
        act_refresh = menu.addAction("刷新分区图标")
        menu.addSeparator()
        act_rename_cap = menu.addAction("重命名此胶囊标题...")
        act_del_cap = menu.addAction("删除此极光胶囊...")
        menu.addSeparator()
        act_expand_all = menu.addAction("全部展开并常驻")
        act_auto_all = menu.addAction("全部开启 0.5s 自动卷起")
        act_reset = menu.addAction("重置左侧山体黄金布局")
        act_hide = menu.addAction("淡出隐藏全部卡片 (双击桌面恢复)")

        chosen = menu.exec(event.globalPos())
        self.set_menu_open(False)

        if chosen == act_pin:
            self.pinned = not self.pinned
            self.pinToggled.emit(self.group_key, self.pinned)
            self.update()
        elif chosen == act_toggle:
            if self._expanded:
                self.collapse_card(force=True)
            else:
                self.expand_card()
        elif chosen == act_new_cap:
            self.contextActionTriggered.emit("create_capsule")
        elif chosen == act_add:
            if prompt_add_items_to_folder(self, self.folder_path):
                self.reload_items()
        elif chosen == act_add_dir:
            if prompt_add_directory_to_folder(self, self.folder_path):
                self.reload_items()
        elif chosen == act_folder:
            subprocess.Popen(["explorer.exe", str(self.folder_path)])
        elif chosen == act_refresh:
            self.reload_items()
        elif chosen == act_rename_cap:
            self.renameCapsuleRequested.emit(self.group_key)
        elif chosen == act_del_cap:
            self.deleteCapsuleRequested.emit(self.group_key)
        elif chosen == act_expand_all:
            self.contextActionTriggered.emit("pin_all")
        elif chosen == act_auto_all:
            self.contextActionTriggered.emit("unpin_all")
        elif chosen == act_reset:
            self.contextActionTriggered.emit("reset_layout")
        elif chosen == act_hide:
            self.contextActionTriggered.emit("toggle_visibility")

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            local = Path(url.toLocalFile())
            if local.exists():
                import_item_into_group_folder(local, self.folder_path)
        self.reload_items()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)

        # 1. Glowing Aurora dot indicator on header left
        dot_rect = QRectF(14.0, (self.HEADER_HEIGHT - 7.0) / 2.0, 7.0, 7.0)
        dot_grad = QLinearGradient(dot_rect.topLeft(), dot_rect.bottomRight())
        dot_grad.setColorAt(0.0, self.EMERALD)
        dot_grad.setColorAt(1.0, self.PURPLE)
        painter.setPen(Qt.NoPen)
        painter.setBrush(dot_grad)
        painter.drawEllipse(dot_rect)

        # 2. Apple Widget style crisp SemiBold sans-serif category title
        font = make_apple_font(12, QFont.DemiBold, 0.65)
        painter.setFont(font)

        title_rect = QRectF(28.0, 0.0, 230.0, float(self.HEADER_HEIGHT))
        painter.setPen(QColor(0, 0, 0, 115))
        painter.drawText(title_rect.translated(0, 1.0), Qt.AlignLeft | Qt.AlignVCenter, self.title)

        title_alpha = int(232 + 23 * self._border_glow)
        painter.setPen(QColor(255, 255, 255, title_alpha))
        painter.drawText(title_rect, Qt.AlignLeft | Qt.AlignVCenter, self.title)

        # 3. Instant hover full-name reveal OR subtle item count pill on right
        if self._hovered_item_label and self._expanded:
            hov_font = make_apple_font(11, QFont.Medium, 0.0)
            painter.setFont(hov_font)
            fm = QFontMetrics(hov_font)
            hov_text = fm.elidedText(self._hovered_item_label, Qt.ElideRight, 138)
            hov_rect = QRectF(self.width() - 180.0, 0.0, 140.0, float(self.HEADER_HEIGHT))
            painter.setPen(QColor(0, 0, 0, 110))
            painter.drawText(hov_rect.translated(0, 1.0), Qt.AlignRight | Qt.AlignVCenter, hov_text)
            painter.setPen(QColor(167, 243, 208, 245))
            painter.drawText(hov_rect, Qt.AlignRight | Qt.AlignVCenter, hov_text)
        else:
            cnt_font = make_apple_font(11, QFont.Medium, 0.0)
            painter.setFont(cnt_font)
            painter.setPen(QColor(220, 232, 248, int(135 + 65 * self._border_glow)))
            cnt_rect = QRectF(self.width() - 66.0, 0.0, 26.0, float(self.HEADER_HEIGHT))
            painter.drawText(cnt_rect, Qt.AlignRight | Qt.AlignVCenter, str(self._item_count))

        # 4. Minimalist Pin / Auto-collapse indicator button (top-right)
        if self.pinned or self._border_glow > 0.05:
            cx, cy = self._pin_rect.center().x(), self._pin_rect.center().y()
            if self.pinned:
                # Filled emerald-ring indicator when pinned open
                painter.setBrush(QColor(45, 212, 191, 210))
                painter.setPen(QPen(QColor(45, 212, 191, 120), 2.0))
                painter.drawEllipse(QPointF(cx, cy), 4.0, 4.0)
            else:
                # Subtle hollow ring when in 0.5s auto-collapse mode
                alpha = 185 if self._hover_pin else int(95 * self._border_glow)
                painter.setBrush(Qt.NoBrush)
                painter.setPen(QPen(QColor(220, 235, 255, alpha), 1.2))
                painter.drawEllipse(QPointF(cx, cy), 4.0, 4.0)

        # 5. Subtle hairline divider under header when expanded
        if self.height() > self.HEADER_HEIGHT + 8:
            div_grad = QLinearGradient(14.0, 0.0, self.width() - 14.0, 0.0)
            div_grad.setColorAt(0.0, QColor(45, 212, 191, 42))
            div_grad.setColorAt(0.5, QColor(255, 255, 255, 20))
            div_grad.setColorAt(1.0, QColor(168, 85, 247, 36))
            painter.setPen(QPen(div_grad, 1.0))
            painter.drawLine(
                QPointF(14.0, float(self.HEADER_HEIGHT)),
                QPointF(self.width() - 14.0, float(self.HEADER_HEIGHT)),
            )
