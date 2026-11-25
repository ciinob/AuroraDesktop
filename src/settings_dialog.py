# -*- coding: utf-8 -*-
"""Aurora Desktop Settings Center.

Centralized macOS / VisionOS-inspired dark glass settings window covering:
  1. General & Startup (auto-start, desktop double-click stealth, position lock, layout actions, updates)
  2. Capsules & Groups (create, rename, switch bar/card kind, reorder up/down, delete, open folder)
  3. Custom Icons & Items (per-shortcut custom PNG/ICO/EXE icon override, preview, rename, move, cache reset)
  4. Global Hotkeys (interactive shortcut recorder with conflict detection + Double-Ctrl toggle)
  5. Appearance, Clock & Taskbar (aurora themes, glass opacity, artistic clock styles/scale, native taskbar modes)
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, QSize, Qt, QVariantAnimation, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QIcon,
    QKeyEvent,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from clock_widget import CLOCK_STYLES
from icon_extractor import format_display_name
from paths import APP_VERSION, DATA_ROOT, GROUPS_DIR, ICON_ICO_PATH, ICON_PNG_PATH
from taskbar_engine import TASKBAR_MODES
from widgets import (
    AURORA_THEMES,
    DIALOG_QSS,
    GLASS_OPACITY_LEVELS,
    MENU_QSS,
    NewCapsuleDialog,
    SYSTEM_SHELL_ITEMS,
    create_system_shell_shortcut,
    extract_vibrant_accent,
    make_apple_font,
)
from win32_utils import apply_dark_title_bar, format_hotkey_label

if TYPE_CHECKING:
    from main import AuroraController


SETTINGS_QSS = """
QWidget#SettingsRoot {
    background-color: #0b1120;
    color: #f1f5f9;
    font-family: "Inter", "Noto Sans SC", "Microsoft YaHei UI";
    font-size: 13px;
}
QFrame#Sidebar {
    background-color: #0f172a;
    border-right: 1px solid rgba(255, 255, 255, 20);
}
QPushButton.navBtn {
    background-color: transparent;
    color: #94a3b8;
    border: 1px solid transparent;
    border-radius: 10px;
    padding: 10px 14px;
    text-align: left;
    font-size: 13px;
    font-weight: 500;
}
QPushButton.navBtn:hover {
    background-color: rgba(255, 255, 255, 10);
    color: #e2e8f0;
}
QPushButton.navBtn:checked {
    background-color: rgba(45, 212, 191, 34);
    border: 1px solid rgba(45, 212, 191, 110);
    color: #5eead4;
    font-weight: 600;
}
QFrame.sectionCard {
    background-color: #131c31;
    border: 1px solid rgba(255, 255, 255, 20);
    border-radius: 12px;
}
QLabel.pageTitle {
    color: #f8fafc;
    font-size: 20px;
    font-weight: 700;
}
QLabel.pageSub {
    color: #94a3b8;
    font-size: 12px;
}
QLabel.cardHeader {
    color: #5eead4;
    font-size: 12px;
    font-weight: 600;
}
QLabel.rowTitle {
    color: #f1f5f9;
    font-size: 13px;
    font-weight: 500;
}
QLabel.rowDesc {
    color: #94a3b8;
    font-size: 11px;
}
QScrollArea {
    background: transparent;
    border: none;
}
QScrollArea > QWidget > QWidget {
    background: transparent;
}
QScrollBar:vertical {
    background: transparent;
    width: 7px;
    margin: 4px 1px;
}
QScrollBar::handle:vertical {
    background: rgba(148, 163, 184, 70);
    border-radius: 3px;
    min-height: 28px;
}
QScrollBar::handle:vertical:hover {
    background: rgba(45, 212, 191, 140);
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
QLineEdit, QComboBox {
    background-color: #1a2640;
    color: #f8fafc;
    border: 1px solid rgba(148, 163, 184, 55);
    border-radius: 8px;
    padding: 6px 10px;
    font-size: 13px;
}
QLineEdit:focus, QComboBox:focus {
    border: 1px solid rgba(45, 212, 191, 165);
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
    outline: 0;
}
QListWidget {
    background-color: #0f172a;
    color: #e2e8f0;
    border: 1px solid rgba(255, 255, 255, 20);
    border-radius: 10px;
    padding: 4px;
    outline: 0;
}
QListWidget::item {
    border-radius: 8px;
    padding: 7px 10px;
    margin: 2px 2px;
}
QListWidget::item:hover {
    background-color: rgba(255, 255, 255, 12);
}
QListWidget::item:selected {
    background-color: rgba(45, 212, 191, 42);
    color: #ffffff;
    border: 1px solid rgba(45, 212, 191, 110);
}
QPushButton {
    background-color: #1e293b;
    color: #e2e8f0;
    border: 1px solid rgba(255, 255, 255, 30);
    border-radius: 8px;
    padding: 6px 14px;
    font-weight: 500;
}
QPushButton:hover {
    background-color: #28364f;
    border: 1px solid rgba(45, 212, 191, 95);
}
QPushButton:disabled {
    background-color: #151e30;
    color: #64748b;
    border: 1px solid rgba(255, 255, 255, 12);
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
QPushButton#dangerBtn {
    background-color: rgba(239, 68, 68, 28);
    color: #fca5a5;
    border: 1px solid rgba(239, 68, 68, 90);
}
QPushButton#dangerBtn:hover {
    background-color: rgba(239, 68, 68, 55);
    color: #ffffff;
}
"""


class AuroraToggleSwitch(QWidget):
    """Smooth iOS / VisionOS style pill toggle switch."""
    toggled = Signal(bool)

    def __init__(self, checked: bool = False, parent=None):
        super().__init__(parent)
        self._checked = bool(checked)
        self._pos = 1.0 if self._checked else 0.0
        self.setFixedSize(44, 24)
        self.setCursor(Qt.PointingHandCursor)

        self._anim = QVariantAnimation(self)
        self._anim.setDuration(150)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._on_anim)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool, animate: bool = False):
        checked = bool(checked)
        if self._checked == checked:
            return
        self._checked = checked
        self._anim.stop()
        if animate:
            self._anim.setStartValue(self._pos)
            self._anim.setEndValue(1.0 if checked else 0.0)
            self._anim.start()
        else:
            self._pos = 1.0 if checked else 0.0
            self.update()

    def _on_anim(self, val):
        self._pos = float(val)
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.setChecked(not self._checked, animate=True)
            self.toggled.emit(self._checked)
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        r = QRectF(1.0, 1.0, self.width() - 2.0, self.height() - 2.0)

        off_c = QColor("#334155")
        on_c = QColor("#14b8a6")
        p = self._pos
        bg = QColor(
            int(off_c.red() + (on_c.red() - off_c.red()) * p),
            int(off_c.green() + (on_c.green() - off_c.green()) * p),
            int(off_c.blue() + (on_c.blue() - off_c.blue()) * p),
        )
        painter.setPen(QPen(QColor(255, 255, 255, 30), 1.0))
        painter.setBrush(bg)
        painter.drawRoundedRect(r, 11.0, 11.0)

        knob_d = 18.0
        kx = 3.0 + p * (self.width() - knob_d - 6.0)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(QRectF(kx, 3.0, knob_d, knob_d))


def _qt_key_to_token(key: int) -> str | None:
    if Qt.Key_A <= key <= Qt.Key_Z:
        return chr(ord("A") + (key - Qt.Key_A))
    if Qt.Key_0 <= key <= Qt.Key_9:
        return chr(ord("0") + (key - Qt.Key_0))
    if Qt.Key_F1 <= key <= Qt.Key_F12:
        return f"F{key - Qt.Key_F1 + 1}"
    mapping = {
        Qt.Key_QuoteLeft: "~",
        Qt.Key_AsciiTilde: "~",
        Qt.Key_Space: "Space",
        Qt.Key_Tab: "Tab",
        Qt.Key_Return: "Enter",
        Qt.Key_Enter: "Enter",
        Qt.Key_Minus: "-",
        Qt.Key_Equal: "=",
        Qt.Key_BracketLeft: "[",
        Qt.Key_BracketRight: "]",
        Qt.Key_Backslash: "\\",
        Qt.Key_Semicolon: ";",
        Qt.Key_Apostrophe: "'",
        Qt.Key_Comma: ",",
        Qt.Key_Period: ".",
        Qt.Key_Slash: "/",
        Qt.Key_Up: "Up",
        Qt.Key_Down: "Down",
        Qt.Key_Left: "Left",
        Qt.Key_Right: "Right",
        Qt.Key_Home: "Home",
        Qt.Key_End: "End",
        Qt.Key_PageUp: "PageUp",
        Qt.Key_PageDown: "PageDown",
        Qt.Key_Insert: "Insert",
        Qt.Key_Delete: "Delete",
    }
    return mapping.get(key)


class HotkeyRecorderButton(QPushButton):
    """Interactive click-to-record global shortcut button."""
    hotkeyChanged = Signal(str)

    def __init__(self, spec: str = "", parent=None):
        super().__init__(parent)
        self._spec = spec
        self._recording = False
        self.setMinimumWidth(168)
        self.setCursor(Qt.PointingHandCursor)
        self._refresh_text()
        self.clicked.connect(self._start_recording)

    def spec(self) -> str:
        return self._spec

    def set_spec(self, spec: str):
        self._spec = spec or ""
        self._recording = False
        self._refresh_text()

    def _refresh_text(self):
        if self._recording:
            self.setText("请按下组合键... (Esc 取消)")
            self.setStyleSheet(
                "background-color: rgba(45, 212, 191, 45); color: #5eead4; "
                "border: 1px solid #2dd4bf; font-weight: 600;"
            )
        else:
            self.setText(format_hotkey_label(self._spec) if self._spec else "未设置（点击录制）")
            self.setStyleSheet("")

    def _start_recording(self):
        self._recording = True
        self._refresh_text()
        self.setFocus(Qt.MouseFocusReason)

    def focusOutEvent(self, event):
        if self._recording:
            self._recording = False
            self._refresh_text()
        super().focusOutEvent(event)

    def keyPressEvent(self, event: QKeyEvent):
        if not self._recording:
            super().keyPressEvent(event)
            return

        key = event.key()
        if key == Qt.Key_Escape:
            self._recording = False
            self._refresh_text()
            event.accept()
            return
        if key == Qt.Key_Backspace:
            self._spec = ""
            self._recording = False
            self._refresh_text()
            self.hotkeyChanged.emit("")
            event.accept()
            return

        if key in (Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta):
            event.accept()
            return

        token = _qt_key_to_token(key)
        if not token:
            event.accept()
            return

        mods = event.modifiers()
        parts: list[str] = []
        if mods & Qt.ControlModifier:
            parts.append("Ctrl")
        if mods & Qt.AltModifier:
            parts.append("Alt")
        if mods & Qt.ShiftModifier:
            parts.append("Shift")
        if mods & Qt.MetaModifier:
            parts.append("Win")

        is_fn = token.startswith("F") and token[1:].isdigit()
        if not parts and not is_fn:
            # Require at least one modifier key for normal keys so typing is never hijacked
            self.setText("需包含 Ctrl / Alt / Shift / Win")
            event.accept()
            return

        parts.append(token)
        new_spec = "+".join(parts)
        self._spec = new_spec
        self._recording = False
        self._refresh_text()
        self.hotkeyChanged.emit(new_spec)
        event.accept()


class IconPreviewBadge(QWidget):
    """High-DPI glass tile preview showing how an icon & its adaptive glow look on the desktop."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(96, 96)
        self._pixmap = QPixmap()
        self._accent = QColor("#2dd4bf")

    def set_pixmap(self, pm: QPixmap):
        self._pixmap = pm
        self._accent = extract_vibrant_accent(pm)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        rect = QRectF(2.0, 2.0, self.width() - 4.0, self.height() - 4.0)

        grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
        c1 = QColor(self._accent)
        c1.setAlpha(58)
        c2 = QColor("#0f172a")
        c2.setAlpha(220)
        grad.setColorAt(0.0, c1)
        grad.setColorAt(1.0, c2)

        border = QColor(self._accent)
        border.setAlpha(140)
        painter.setBrush(grad)
        painter.setPen(QPen(border, 1.2))
        painter.drawRoundedRect(rect, 18.0, 18.0)

        if not self._pixmap.isNull():
            isz = 56.0
            ix = (self.width() - isz) / 2.0
            iy = (self.height() - isz) / 2.0
            painter.drawPixmap(QRectF(ix, iy, isz, isz), self._pixmap, QRectF(self._pixmap.rect()))


def _make_card(title: str = "") -> tuple[QFrame, QVBoxLayout]:
    card = QFrame()
    card.setProperty("class", "sectionCard")
    lay = QVBoxLayout(card)
    lay.setContentsMargins(18, 15, 18, 15)
    lay.setSpacing(12)
    if title:
        hdr = QLabel(title)
        hdr.setProperty("class", "cardHeader")
        lay.addWidget(hdr)
    return card, lay


def _make_setting_row(title: str, desc: str, right_widget: QWidget) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setSpacing(14)
    txt_col = QVBoxLayout()
    txt_col.setSpacing(2)
    lbl_t = QLabel(title)
    lbl_t.setProperty("class", "rowTitle")
    txt_col.addWidget(lbl_t)
    if desc:
        lbl_d = QLabel(desc)
        lbl_d.setProperty("class", "rowDesc")
        lbl_d.setWordWrap(True)
        txt_col.addWidget(lbl_d)
    row.addLayout(txt_col, 1)
    row.addWidget(right_widget, 0, Qt.AlignVCenter)
    return row


def _wrap_scroll(content: QWidget) -> QScrollArea:
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    sa.setWidget(content)
    return sa


class AuroraSettingsWindow(QWidget):
    """Unified Settings Center for Aurora Desktop."""

    PAGE_INDEX = {
        "general": 0,
        "groups": 1,
        "icons": 2,
        "hotkeys": 3,
        "appearance": 4,
    }

    def __init__(self, controller: AuroraController, parent=None):
        super().__init__(parent)
        self.ctrl = controller
        self._syncing = False
        self._selected_group_key: str = ""
        self._selected_item_path: Path | None = None

        self.setObjectName("SettingsRoot")
        self.setWindowTitle(f"Aurora Desktop · 极光桌面主控台 v{APP_VERSION}")
        self.resize(920, 640)
        self.setMinimumSize(840, 560)
        self.setStyleSheet(SETTINGS_QSS)

        icon_file = ICON_ICO_PATH if ICON_ICO_PATH.exists() else ICON_PNG_PATH
        if icon_file.exists():
            self.setWindowIcon(QIcon(str(icon_file)))

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Left navigation sidebar
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(220)
        sb_lay = QVBoxLayout(sidebar)
        sb_lay.setContentsMargins(14, 20, 14, 16)
        sb_lay.setSpacing(6)

        brand_row = QHBoxLayout()
        brand_row.setSpacing(10)
        logo_lbl = QLabel()
        if ICON_PNG_PATH.exists():
            pm = QPixmap(str(ICON_PNG_PATH)).scaled(34, 34, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            logo_lbl.setPixmap(pm)
        brand_col = QVBoxLayout()
        brand_col.setSpacing(1)
        b_title = QLabel("Aurora Desktop")
        b_title.setFont(make_apple_font(14, QFont.Bold))
        b_title.setStyleSheet("color: #f8fafc;")
        b_ver = QLabel(f"极光桌面主控台 · v{APP_VERSION}")
        b_ver.setStyleSheet("color: #5eead4; font-size: 11px; font-weight: 600;")
        brand_col.addWidget(b_title)
        brand_col.addWidget(b_ver)
        brand_row.addWidget(logo_lbl)
        brand_row.addLayout(brand_col, 1)
        sb_lay.addLayout(brand_row)
        sb_lay.addSpacing(8)

        # Instant quick-action bar right inside the sidebar
        qa_row = QHBoxLayout()
        qa_row.setSpacing(6)
        btn_qa_spot = QPushButton("🔍 搜索")
        btn_qa_spot.setToolTip("呼出极光全局搜索 (双击 Ctrl / Alt+S)")
        btn_qa_spot.clicked.connect(self.ctrl.spotlight.toggle_spotlight)
        self.btn_qa_vis = QPushButton("🙈 隐藏卡片")
        self.btn_qa_vis.setToolTip("一键隐藏或恢复桌面上的所有极光胶囊")
        self.btn_qa_vis.clicked.connect(self._on_toggle_desktop_cards)
        qa_row.addWidget(btn_qa_spot, 1)
        qa_row.addWidget(self.btn_qa_vis, 1)
        sb_lay.addLayout(qa_row)
        sb_lay.addSpacing(8)

        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        self._nav_buttons: list[QPushButton] = []

        nav_specs = [
            ("⚡  常规与开机自启", 0),
            ("🧊  胶囊分组增删", 1),
            ("🎨  图标自定义", 2),
            ("⌨️  全局热键设置", 3),
            ("✨  外观 · 时钟 · 任务栏", 4),
        ]
        for label, idx in nav_specs:
            btn = QPushButton(label)
            btn.setProperty("class", "navBtn")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            self._nav_group.addButton(btn, idx)
            self._nav_buttons.append(btn)
            sb_lay.addWidget(btn)

        sb_lay.addStretch(1)
        foot_hint = QLabel("点右上角 × 关闭窗口后\n胶囊与任务栏继续后台运行")
        foot_hint.setStyleSheet("color: #64748b; font-size: 11px;")
        sb_lay.addWidget(foot_hint)
        sb_lay.addSpacing(4)
        btn_quit_app = QPushButton("🚪 完全退出程序")
        btn_quit_app.setObjectName("dangerBtn")
        btn_quit_app.clicked.connect(self.ctrl.quit_app)
        sb_lay.addWidget(btn_quit_app)

        # Right stacked pages
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_general_page())
        self.stack.addWidget(self._build_groups_page())
        self.stack.addWidget(self._build_icons_page())
        self.stack.addWidget(self._build_hotkeys_page())
        self.stack.addWidget(self._build_appearance_page())

        self._nav_group.idClicked.connect(self.stack.setCurrentIndex)
        self._nav_buttons[0].setChecked(True)

        root.addWidget(sidebar)
        root.addWidget(self.stack, 1)

        self.ctrl.stateChanged.connect(self.refresh_all)
        self.ctrl.update_checker.checkStarted.connect(self._on_upd_started)
        self.ctrl.update_checker.checkFinished.connect(self._on_upd_finished)

        self._center_on_screen()
        self.refresh_all()

    def showEvent(self, event):
        super().showEvent(event)
        apply_dark_title_bar(int(self.winId()))

    def _center_on_screen(self):
        scr = QGuiApplication.primaryScreen()
        if scr:
            ag = scr.availableGeometry()
            self.move(ag.center().x() - self.width() // 2, ag.center().y() - self.height() // 2)

    def navigate_to(self, page_key: str = "general", target: object = None):
        idx = self.PAGE_INDEX.get(page_key, 0)
        if 0 <= idx < len(self._nav_buttons):
            self._nav_buttons[idx].setChecked(True)
            self.stack.setCurrentIndex(idx)

        self.refresh_all()

        if page_key == "groups" and isinstance(target, str) and target:
            self._select_group_in_list(target)
        elif page_key == "icons" and isinstance(target, Path):
            self._focus_specific_item(target)

    # =========================================================================
    # Page 1: General & Startup
    # =========================================================================
    def _build_general_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(16)

        t = QLabel("常规与启动")
        t.setProperty("class", "pageTitle")
        s = QLabel("集中管理开机自启、桌面交互手势、布局重排与版本检查")
        s.setProperty("class", "pageSub")
        lay.addWidget(t)
        lay.addWidget(s)

        c_boot, l_boot = _make_card("🚀 启动与桌面接管")
        self.sw_hide_desk_icons = AuroraToggleSwitch()
        self.sw_hide_desk_icons.toggled.connect(
            lambda v: not self._syncing and self.ctrl.set_hide_desktop_icons(v)
        )
        l_boot.addLayout(_make_setting_row(
            "✨ 接管纯净桌面（隐藏 Windows 原生桌面图标）",
            "一键隐藏原本杂乱的系统桌面图标，壁纸 100% 纯净通透（绝不删改文件；关闭此开关或退出程序时自动无损还原）",
            self.sw_hide_desk_icons,
        ))

        self.sw_autorun = AuroraToggleSwitch()
        self.sw_autorun.toggled.connect(self._on_autorun_toggled)
        l_boot.addLayout(_make_setting_row(
            "开机自动启动",
            "登录 Windows 时自动在后台启动 Aurora Desktop，并同步写入任务管理器启动项批准标志",
            self.sw_autorun,
        ))

        self.sw_dbl_hide = AuroraToggleSwitch()
        self.sw_dbl_hide.toggled.connect(lambda v: not self._syncing and self.ctrl.set_double_click_hide(v))
        l_boot.addLayout(_make_setting_row(
            "双击桌面空白处一键隐身",
            "在壁纸空白区域双击鼠标左键时淡出隐藏全部极光卡片，再次双击立即恢复",
            self.sw_dbl_hide,
        ))

        self.sw_lock_pos = AuroraToggleSwitch()
        self.sw_lock_pos.toggled.connect(lambda v: not self._syncing and self.ctrl.set_lock_positions(v))
        l_boot.addLayout(_make_setting_row(
            "锁定桌面胶囊卡片位置",
            "防止日常点击时误拖拽移动胶囊卡片（仍支持卡片展开、卷起与内部图标拖拽）",
            self.sw_lock_pos,
        ))

        self.sw_memo = AuroraToggleSwitch()
        self.sw_memo.toggled.connect(lambda v: not self._syncing and self.ctrl.set_show_memo(v))
        l_boot.addLayout(_make_setting_row(
            "显示极光速记便签卡 (Quick Memo)",
            "在胶囊瀑布流末尾挂载一张实时自动保存的毛玻璃桌面速记便签",
            self.sw_memo,
        ))
        lay.addWidget(c_boot)

        c_layout, l_layout = _make_card("📐 布局与桌面快捷方式同步")
        btn_row1 = QHBoxLayout()
        btn_row1.setSpacing(10)
        b_reset = QPushButton("重置左侧黄金布局")
        b_reset.clicked.connect(lambda: self.ctrl.reset_to_left_golden_layout(True))
        b_pin_all = QPushButton("全部展开并常驻")
        b_pin_all.clicked.connect(lambda: self.ctrl.handle_context_action("pin_all"))
        b_unpin_all = QPushButton("全部开启 0.5s 自动卷起")
        b_unpin_all.clicked.connect(lambda: self.ctrl.handle_context_action("unpin_all"))
        btn_row1.addWidget(b_reset)
        btn_row1.addWidget(b_pin_all)
        btn_row1.addWidget(b_unpin_all)
        btn_row1.addStretch(1)
        l_layout.addLayout(btn_row1)

        btn_row2 = QHBoxLayout()
        btn_row2.setSpacing(10)
        b_rescan = QPushButton("🔄 重新扫描导入桌面快捷方式")
        b_rescan.clicked.connect(self._on_rescan_clicked)
        b_open_data = QPushButton("📂 打开数据存储目录")
        b_open_data.clicked.connect(self.ctrl.open_data_root)
        btn_row2.addWidget(b_rescan)
        btn_row2.addWidget(b_open_data)
        btn_row2.addStretch(1)
        l_layout.addLayout(btn_row2)
        lay.addWidget(c_layout)

        c_about, l_about = _make_card("📦 版本与数据存储")
        self.btn_check_update = QPushButton("🔄 检查新版本")
        self.btn_check_update.setObjectName("primaryBtn")
        self.btn_check_update.clicked.connect(self.ctrl.update_checker.check)
        l_about.addLayout(_make_setting_row(
            f"当前版本：v{APP_VERSION}",
            f"配置与分组目录：{DATA_ROOT}",
            self.btn_check_update,
        ))
        lay.addWidget(c_about)
        lay.addStretch(1)
        return _wrap_scroll(page)

    def _on_autorun_toggled(self, val: bool):
        if self._syncing:
            return
        self.ctrl.set_autorun(val)

    def _on_rescan_clicked(self):
        added = self.ctrl.rescan_desktop_shortcuts()
        box = QMessageBox(self)
        box.setStyleSheet(DIALOG_QSS)
        box.setWindowTitle("扫描完成")
        box.setText(f"已同步桌面快捷方式，本次新导入 {added} 个条目。" if added else "桌面没有发现尚未收纳的新快捷方式。")
        box.addButton("知道了", QMessageBox.AcceptRole)
        box.exec()

    def _on_upd_started(self):
        self.btn_check_update.setEnabled(False)
        self.btn_check_update.setText("⏳ 正在检查...")

    def _on_upd_finished(self):
        self.btn_check_update.setEnabled(True)
        self.btn_check_update.setText("🔄 检查新版本")

    # =========================================================================
    # Page 2: Capsules & Groups
    # =========================================================================
    def _build_groups_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(14)

        t = QLabel("胶囊分组管理")
        t.setProperty("class", "pageTitle")
        s = QLabel("自由增删胶囊分区、切换「折叠卡片 / 横向胶囊栏」形态，或上下调整排列顺序")
        s.setProperty("class", "pageSub")
        lay.addWidget(t)
        lay.addWidget(s)

        split = QHBoxLayout()
        split.setSpacing(16)

        # Left list + toolbar
        left_col = QVBoxLayout()
        left_col.setSpacing(10)
        self.group_list = QListWidget()
        self.group_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.group_list.currentRowChanged.connect(self._on_group_selected)
        left_col.addWidget(self.group_list, 1)

        bar_btns = QHBoxLayout()
        bar_btns.setSpacing(6)
        self.btn_grp_add = QPushButton("➕ 新建分组")
        self.btn_grp_add.setObjectName("primaryBtn")
        self.btn_grp_add.clicked.connect(self._on_create_group)
        self.btn_grp_up = QPushButton("⬆️ 上移")
        self.btn_grp_up.clicked.connect(lambda: self._on_move_group(-1))
        self.btn_grp_down = QPushButton("⬇️ 下移")
        self.btn_grp_down.clicked.connect(lambda: self._on_move_group(1))
        self.btn_grp_del = QPushButton("🗑️ 删除")
        self.btn_grp_del.setObjectName("dangerBtn")
        self.btn_grp_del.clicked.connect(self._on_delete_group)
        bar_btns.addWidget(self.btn_grp_add)
        bar_btns.addWidget(self.btn_grp_up)
        bar_btns.addWidget(self.btn_grp_down)
        bar_btns.addWidget(self.btn_grp_del)
        left_col.addLayout(bar_btns)

        # Right inspector card
        self.grp_detail_card, d_lay = _make_card("✏️ 当前选中分组属性")
        lbl_title = QLabel("分组标题：")
        self.edit_grp_title = QLineEdit()
        self.edit_grp_title.setPlaceholderText("输入胶囊标题...")

        lbl_kind = QLabel("展示形态：")
        self.combo_grp_kind = QComboBox()
        self.combo_grp_kind.addItem("🧊 可折叠极光卡片（5 列网格，支持自动卷起）", "card")
        self.combo_grp_kind.addItem("💊 横向单行悬浮胶囊栏（紧凑单行徽标栏）", "bar")
        self.combo_grp_kind.addItem("📂 文件夹实时映射胶囊（Folder Portal · 实时同步本地目录）", "portal")

        self.lbl_grp_badge = QLabel("左侧徽标文字（1~3 字符，仅横向胶囊栏显示）：")
        self.edit_grp_badge = QLineEdit()
        self.edit_grp_badge.setMaxLength(4)
        self.edit_grp_badge.setPlaceholderText("如 AI / DEV")

        # Portal-specific inspector controls
        self.portal_props_wrap = QWidget()
        pp_lay = QVBoxLayout(self.portal_props_wrap)
        pp_lay.setContentsMargins(0, 2, 0, 2)
        pp_lay.setSpacing(8)
        pp_lay.addWidget(QLabel("实时映射源目录（新增/删除文件将自动同步展示）："))
        pp_path_row = QHBoxLayout()
        pp_path_row.setSpacing(6)
        self.edit_grp_portal_path = QLineEdit()
        btn_pp_browse = QPushButton("浏览...")
        btn_pp_browse.clicked.connect(self._browse_grp_portal_path)
        pp_path_row.addWidget(self.edit_grp_portal_path, 1)
        pp_path_row.addWidget(btn_pp_browse)
        pp_lay.addLayout(pp_path_row)

        pp_opt_row = QHBoxLayout()
        pp_opt_row.setSpacing(8)
        self.combo_grp_portal_sort = QComboBox()
        self.combo_grp_portal_sort.addItem("🕒 最新修改优先", "mtime_desc")
        self.combo_grp_portal_sort.addItem("📁 文件夹优先", "dirs_first")
        self.combo_grp_portal_sort.addItem("🔤 按名称排序", "name_asc")
        self.combo_grp_portal_max = QComboBox()
        for cnt_v in (10, 15, 20, 30, 50):
            self.combo_grp_portal_max.addItem(f"最多显示 {cnt_v} 项", cnt_v)
        pp_opt_row.addWidget(self.combo_grp_portal_sort, 3)
        pp_opt_row.addWidget(self.combo_grp_portal_max, 2)
        pp_lay.addLayout(pp_opt_row)

        self.sw_grp_pin = AuroraToggleSwitch()
        self.row_grp_pin_wrap = QWidget()
        pin_lay = _make_setting_row("常驻展开（不自动卷起）", "关闭后鼠标移开 0.5 秒自动折叠为紧凑标题条", self.sw_grp_pin)
        pin_lay.setContentsMargins(0, 4, 0, 4)
        self.row_grp_pin_wrap.setLayout(pin_lay)

        self.btn_save_grp = QPushButton("💾 保存分组修改")
        self.btn_save_grp.setObjectName("primaryBtn")
        self.btn_save_grp.clicked.connect(self._on_save_group_props)
        self.edit_grp_title.returnPressed.connect(self._on_save_group_props)
        self.edit_grp_badge.returnPressed.connect(self._on_save_group_props)
        self.combo_grp_kind.currentIndexChanged.connect(self._update_grp_kind_visibility)

        d_lay.addWidget(lbl_title)
        d_lay.addWidget(self.edit_grp_title)
        d_lay.addWidget(lbl_kind)
        d_lay.addWidget(self.combo_grp_kind)
        d_lay.addWidget(self.lbl_grp_badge)
        d_lay.addWidget(self.edit_grp_badge)
        d_lay.addWidget(self.portal_props_wrap)
        d_lay.addWidget(self.row_grp_pin_wrap)
        d_lay.addWidget(self.btn_save_grp)
        d_lay.addSpacing(8)

        act_hdr = QLabel("📦 分组内容快捷管理")
        act_hdr.setProperty("class", "cardHeader")
        d_lay.addWidget(act_hdr)

        g_act_row = QHBoxLayout()
        g_act_row.setSpacing(8)
        self.btn_grp_add_file = QPushButton("➕ 添加应用/文件...")
        self.btn_grp_add_file.clicked.connect(self._on_add_files_to_selected_group)
        self.btn_grp_add_dir = QPushButton("📁 添加文件夹...")
        self.btn_grp_add_dir.clicked.connect(self._on_add_dir_to_selected_group)
        b_open_dir = QPushButton("📂 打开文件夹")
        b_open_dir.clicked.connect(self._on_open_selected_group_folder)
        g_act_row.addWidget(self.btn_grp_add_file)
        g_act_row.addWidget(self.btn_grp_add_dir)
        g_act_row.addWidget(b_open_dir)
        d_lay.addLayout(g_act_row)

        self.btn_add_sys_item = QPushButton("🖥️ 一键添加系统图标（此电脑 / 回收站 / 控制面板 / 网络 / 下载） ▾")
        self.btn_add_sys_item.clicked.connect(self._on_add_system_item_menu)
        d_lay.addWidget(self.btn_add_sys_item)

        self.btn_jump_icons = QPushButton("🎨 前往「图标自定义」管理此分组内的图标 →")
        self.btn_jump_icons.clicked.connect(self._jump_to_group_icons)
        d_lay.addWidget(self.btn_jump_icons)
        d_lay.addStretch(1)

        split.addLayout(left_col, 5)
        split.addWidget(self.grp_detail_card, 6)
        lay.addLayout(split, 1)
        return page

    def _refresh_groups_page(self):
        prev_key = self._selected_group_key
        self.group_list.blockSignals(True)
        self.group_list.clear()

        target_row = 0
        for i, p in enumerate(self.ctrl.partitions):
            pk = p.get("kind", "card")
            kind_tag = "胶囊栏" if pk == "bar" else ("📂映射" if pk == "portal" else "折叠卡")
            cnt = len(self.ctrl.get_partition_items(p["key"]))
            item = QListWidgetItem(f"[{kind_tag}]  {p['title']}   ({cnt} 项)")
            item.setData(Qt.UserRole, p["key"])
            self.group_list.addItem(item)
            if p["key"] == prev_key:
                target_row = i

        self.group_list.blockSignals(False)
        if self.group_list.count() > 0:
            self.group_list.setCurrentRow(target_row)
            self._on_group_selected(target_row)
        self.btn_grp_del.setEnabled(len(self.ctrl.partitions) > 1)

    def _select_group_in_list(self, group_key: str):
        for i in range(self.group_list.count()):
            if self.group_list.item(i).data(Qt.UserRole) == group_key:
                self.group_list.setCurrentRow(i)
                break

    def _on_group_selected(self, row: int):
        if row < 0 or row >= len(self.ctrl.partitions):
            self._selected_group_key = ""
            return
        p = self.ctrl.partitions[row]
        self._selected_group_key = p["key"]
        self.edit_grp_title.setText(p["title"])
        pk = p.get("kind", "card")
        kind_idx = 1 if pk == "bar" else (2 if pk == "portal" else 0)
        self.combo_grp_kind.blockSignals(True)
        self.combo_grp_kind.setCurrentIndex(kind_idx)
        self.combo_grp_kind.blockSignals(False)
        self.edit_grp_badge.setText(p.get("badge") or p["title"][:2].upper())
        default_dl = Path.home() / "Downloads"
        self.edit_grp_portal_path.setText(p.get("portal_path") or str(default_dl if default_dl.exists() else Path.home()))
        cur_sort = p.get("sort_by", "mtime_desc")
        for i in range(self.combo_grp_portal_sort.count()):
            if self.combo_grp_portal_sort.itemData(i) == cur_sort:
                self.combo_grp_portal_sort.setCurrentIndex(i)
                break
        cur_max = int(p.get("max_items") or 15)
        for i in range(self.combo_grp_portal_max.count()):
            if int(self.combo_grp_portal_max.itemData(i)) == cur_max:
                self.combo_grp_portal_max.setCurrentIndex(i)
                break
        self.sw_grp_pin.setChecked(self.ctrl.is_partition_pinned(p["key"]))
        self._update_grp_kind_visibility()

        self.btn_grp_up.setEnabled(row > 0)
        self.btn_grp_down.setEnabled(row < len(self.ctrl.partitions) - 1)
        self.btn_grp_del.setEnabled(len(self.ctrl.partitions) > 1)

    def _browse_grp_portal_path(self):
        cur = self.edit_grp_portal_path.text().strip() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, "选择要实时映射的本地目录", cur)
        if chosen:
            self.edit_grp_portal_path.setText(chosen)

    def _update_grp_kind_visibility(self):
        cur_k = self.combo_grp_kind.currentData()
        is_bar = cur_k == "bar"
        is_portal = cur_k == "portal"
        self.lbl_grp_badge.setVisible(is_bar)
        self.edit_grp_badge.setVisible(is_bar)
        self.portal_props_wrap.setVisible(is_portal)
        self.row_grp_pin_wrap.setVisible(not is_bar)
        self.btn_grp_add_file.setVisible(not is_portal)
        self.btn_grp_add_dir.setVisible(not is_portal)
        self.btn_add_sys_item.setVisible(not is_portal)
        self.btn_jump_icons.setVisible(not is_portal)

    def _on_save_group_props(self):
        if not self._selected_group_key:
            return
        title = self.edit_grp_title.text().strip()
        if not title:
            self.edit_grp_title.setFocus()
            return
        kind = str(self.combo_grp_kind.currentData())
        p_path = self.edit_grp_portal_path.text().strip()
        if kind == "portal" and (not p_path or not Path(p_path).is_dir()):
            self.edit_grp_portal_path.setFocus()
            return
        badge = self.edit_grp_badge.text().strip() or title[:2].upper()
        pinned = self.sw_grp_pin.isChecked()
        self.ctrl.update_partition(
            self._selected_group_key,
            title=title,
            kind=kind,
            badge=badge,
            pinned=pinned,
            portal_path=p_path if kind == "portal" else None,
            sort_by=str(self.combo_grp_portal_sort.currentData() or "mtime_desc"),
            max_items=int(self.combo_grp_portal_max.currentData() or 15),
        )

    def _on_create_group(self):
        dlg = NewCapsuleDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return
        title, kind = dlg.get_result()
        p_path, p_sort, p_max = dlg.get_portal_options()
        part = self.ctrl.add_partition(title, kind, portal_path=p_path, sort_by=p_sort, max_items=p_max)
        self._selected_group_key = part["key"]
        self.refresh_all()

    def _on_move_group(self, delta: int):
        if self._selected_group_key:
            self.ctrl.move_partition(self._selected_group_key, delta)

    def _on_delete_group(self):
        if not self._selected_group_key or len(self.ctrl.partitions) <= 1:
            return
        self.ctrl.delete_capsule_dialog(self._selected_group_key, parent_widget=self)

    def _on_add_files_to_selected_group(self):
        if self._selected_group_key:
            self.ctrl.add_files_to_partition(self, self._selected_group_key)

    def _on_add_dir_to_selected_group(self):
        if self._selected_group_key:
            self.ctrl.add_dir_to_partition(self, self._selected_group_key)

    def _on_open_selected_group_folder(self):
        if self._selected_group_key:
            self.ctrl.open_partition_folder(self._selected_group_key)

    def _on_add_system_item_menu(self):
        if not self._selected_group_key:
            return
        part = next((p for p in self.ctrl.partitions if p["key"] == self._selected_group_key), None)
        if not part:
            return
        menu = QMenu(self)
        menu.setStyleSheet(MENU_QSS)
        actions = {menu.addAction(v["label"]): k for k, v in SYSTEM_SHELL_ITEMS.items()}
        chosen = menu.exec(self.btn_add_sys_item.mapToGlobal(self.btn_add_sys_item.rect().bottomLeft()))
        if chosen in actions:
            dest_folder = GROUPS_DIR / part["folder"]
            if create_system_shell_shortcut(actions[chosen], dest_folder):
                self.ctrl.reload_all_groups()
                self.refresh_all()

    def _jump_to_group_icons(self):
        key = self._selected_group_key
        self._nav_buttons[2].setChecked(True)
        self.stack.setCurrentIndex(2)
        for i in range(self.combo_icon_group_filter.count()):
            if self.combo_icon_group_filter.itemData(i) == key:
                self.combo_icon_group_filter.setCurrentIndex(i)
                break

    # =========================================================================
    # Page 3: Custom Icons & Items
    # =========================================================================
    def _build_icons_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(14)

        t = QLabel("图标自定义与快捷方式管理")
        t.setProperty("class", "pageTitle")
        s = QLabel("为任意应用、文件夹或文档替换高清 PNG / ICO / EXE 图标，实时预览自适应流光光晕")
        s.setProperty("class", "pageSub")
        lay.addWidget(t)
        lay.addWidget(s)

        # Filter bar
        f_row = QHBoxLayout()
        f_row.setSpacing(10)
        self.combo_icon_group_filter = QComboBox()
        self.combo_icon_group_filter.setMinimumWidth(200)
        self.combo_icon_group_filter.currentIndexChanged.connect(self._populate_items_list)

        self.edit_icon_search = QLineEdit()
        self.edit_icon_search.setPlaceholderText("🔍 输入名称筛选图标...")
        self.edit_icon_search.textChanged.connect(self._populate_items_list)

        btn_clear_cache = QPushButton("🧹 清空图标缓存并重提")
        btn_clear_cache.clicked.connect(self._on_clear_icon_cache)

        f_row.addWidget(self.combo_icon_group_filter)
        f_row.addWidget(self.edit_icon_search, 1)
        f_row.addWidget(btn_clear_cache)
        lay.addLayout(f_row)

        split = QHBoxLayout()
        split.setSpacing(16)

        self.item_list = QListWidget()
        self.item_list.setIconSize(QSize(34, 34))
        self.item_list.currentRowChanged.connect(self._on_item_selected)
        split.addWidget(self.item_list, 5)

        # Right item editor
        detail_card, i_lay = _make_card("🖼️ 图标与条目编辑")
        prev_row = QHBoxLayout()
        prev_row.setSpacing(16)
        self.icon_preview = IconPreviewBadge()
        prev_info = QVBoxLayout()
        prev_info.setSpacing(6)
        self.lbl_item_title = QLabel("未选择条目")
        self.lbl_item_title.setFont(make_apple_font(15, QFont.DemiBold))
        self.lbl_item_status = QLabel("从左侧列表点击任意图标进行编辑")
        self.lbl_item_status.setProperty("class", "rowDesc")
        self.lbl_item_target = QLabel("")
        self.lbl_item_target.setProperty("class", "rowDesc")
        self.lbl_item_target.setWordWrap(True)
        prev_info.addWidget(self.lbl_item_title)
        prev_info.addWidget(self.lbl_item_status)
        prev_info.addWidget(self.lbl_item_target)
        prev_row.addWidget(self.icon_preview)
        prev_row.addLayout(prev_info, 1)
        i_lay.addLayout(prev_row)

        icon_btn_row = QHBoxLayout()
        icon_btn_row.setSpacing(8)
        self.btn_pick_icon = QPushButton("🖼️ 更换自定义图标...")
        self.btn_pick_icon.setObjectName("primaryBtn")
        self.btn_pick_icon.clicked.connect(self._on_pick_custom_icon)
        self.btn_reset_icon = QPushButton("↺ 恢复默认图标")
        self.btn_reset_icon.clicked.connect(self._on_reset_custom_icon)
        icon_btn_row.addWidget(self.btn_pick_icon)
        icon_btn_row.addWidget(self.btn_reset_icon)
        icon_btn_row.addStretch(1)
        i_lay.addLayout(icon_btn_row)

        i_lay.addSpacing(6)
        i_lay.addWidget(QLabel("显示名称："))
        ren_row = QHBoxLayout()
        ren_row.setSpacing(8)
        self.edit_item_name = QLineEdit()
        self.edit_item_name.returnPressed.connect(self._on_rename_item)
        self.btn_rename_item = QPushButton("保存名称")
        self.btn_rename_item.clicked.connect(self._on_rename_item)
        ren_row.addWidget(self.edit_item_name, 1)
        ren_row.addWidget(self.btn_rename_item)
        i_lay.addLayout(ren_row)

        i_lay.addWidget(QLabel("所属胶囊分组："))
        mv_row = QHBoxLayout()
        mv_row.setSpacing(8)
        self.combo_item_move = QComboBox()
        self.btn_move_item = QPushButton("移至此分组")
        self.btn_move_item.clicked.connect(self._on_move_item_group)
        mv_row.addWidget(self.combo_item_move, 1)
        mv_row.addWidget(self.btn_move_item)
        i_lay.addLayout(mv_row)

        i_lay.addStretch(1)
        bot_row = QHBoxLayout()
        bot_row.setSpacing(8)
        self.btn_item_loc = QPushButton("📂 打开目标位置")
        self.btn_item_loc.clicked.connect(self._on_open_item_loc)
        self.btn_item_remove = QPushButton("🗑️ 从分组移除")
        self.btn_item_remove.setObjectName("dangerBtn")
        self.btn_item_remove.clicked.connect(self._on_remove_item)
        bot_row.addWidget(self.btn_item_loc)
        bot_row.addStretch(1)
        bot_row.addWidget(self.btn_item_remove)
        i_lay.addLayout(bot_row)

        split.addWidget(detail_card, 6)
        lay.addLayout(split, 1)
        return page

    def _refresh_icons_page(self):
        cur_filter = self.combo_icon_group_filter.currentData()
        self.combo_icon_group_filter.blockSignals(True)
        self.combo_icon_group_filter.clear()
        self.combo_icon_group_filter.addItem("📚 全部分组图标", "__ALL__")
        restore_idx = 0
        managed_parts = [p for p in self.ctrl.partitions if p.get("kind") != "portal"]
        for idx, p in enumerate(managed_parts, start=1):
            self.combo_icon_group_filter.addItem(f"{p['title']}", p["key"])
            if p["key"] == cur_filter:
                restore_idx = idx
        self.combo_icon_group_filter.setCurrentIndex(restore_idx)
        self.combo_icon_group_filter.blockSignals(False)

        self.combo_item_move.clear()
        for p in managed_parts:
            self.combo_item_move.addItem(p["title"], p["key"])

        self._populate_items_list()

    def _populate_items_list(self):
        grp_filter = self.combo_icon_group_filter.currentData() or "__ALL__"
        q = self.edit_icon_search.text().strip().lower()
        prev_path = self._selected_item_path

        self.item_list.blockSignals(True)
        self.item_list.clear()

        selected_row = -1
        row_idx = 0
        for p in self.ctrl.partitions:
            if p.get("kind") == "portal":
                continue
            if grp_filter != "__ALL__" and p["key"] != grp_filter:
                continue
            for item_path in self.ctrl.get_partition_items(p["key"]):
                short_name, full_name = format_display_name(item_path)
                if q and q not in short_name.lower() and q not in full_name.lower() and q not in item_path.name.lower():
                    continue
                is_custom = self.ctrl.icon_loader.has_custom_icon(item_path)
                prefix = "✨ " if is_custom else ""
                grp_hint = f"  ·  {p['title']}" if grp_filter == "__ALL__" else ""
                lw_item = QListWidgetItem(f"{prefix}{short_name}{grp_hint}")
                pm = self.ctrl.icon_loader.get_icon_pixmap(item_path, 68)
                if not pm.isNull():
                    lw_item.setIcon(QIcon(pm))
                lw_item.setData(Qt.UserRole, (p["key"], str(item_path)))
                self.item_list.addItem(lw_item)
                if prev_path is not None and item_path == prev_path:
                    selected_row = row_idx
                row_idx += 1

        self.item_list.blockSignals(False)
        if self.item_list.count() > 0:
            sel = selected_row if selected_row >= 0 else 0
            self.item_list.setCurrentRow(sel)
            self._on_item_selected(sel)
        else:
            self._on_item_selected(-1)

    def _focus_specific_item(self, target_path: Path):
        self._selected_item_path = target_path
        self.combo_icon_group_filter.setCurrentIndex(0)
        self.edit_icon_search.clear()
        self._populate_items_list()

    def _on_item_selected(self, row: int):
        has_sel = 0 <= row < self.item_list.count()
        for w in (
            self.btn_pick_icon, self.btn_reset_icon, self.edit_item_name,
            self.btn_rename_item, self.combo_item_move, self.btn_move_item,
            self.btn_item_loc, self.btn_item_remove,
        ):
            w.setEnabled(has_sel)

        if not has_sel:
            self._selected_item_path = None
            self.icon_preview.set_pixmap(QPixmap())
            self.lbl_item_title.setText("未选择条目")
            self.lbl_item_status.setText("在左侧列表选择任意图标以自定义")
            self.lbl_item_target.setText("")
            self.edit_item_name.clear()
            return

        grp_key, path_str = self.item_list.item(row).data(Qt.UserRole)
        p = Path(path_str)
        self._selected_item_path = p
        short_name, _ = format_display_name(p)
        pm = self.ctrl.icon_loader.get_icon_pixmap(p, 128)
        is_custom = self.ctrl.icon_loader.has_custom_icon(p)
        target_str = self.ctrl.icon_loader.resolve_target_path(p)

        self.icon_preview.set_pixmap(pm)
        self.lbl_item_title.setText(short_name)
        self.lbl_item_status.setText("✨ 当前使用自定义图标" if is_custom else "使用程序原生高清图标")
        self.lbl_item_target.setText(f"目标：{target_str}")
        self.btn_reset_icon.setEnabled(is_custom)
        self.edit_item_name.setText(short_name)

        for i in range(self.combo_item_move.count()):
            if self.combo_item_move.itemData(i) == grp_key:
                self.combo_item_move.setCurrentIndex(i)
                break

    def _on_pick_custom_icon(self):
        if not self._selected_item_path:
            return
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择自定义图标图片或程序文件",
            str(Path.home()),
            "图标与图片 (*.png *.ico *.webp *.jpg *.jpeg *.bmp *.svg *.exe *.dll);;所有文件 (*.*)",
        )
        if not file_path:
            return
        ok = self.ctrl.set_item_custom_icon(self._selected_item_path, Path(file_path))
        if not ok:
            box = QMessageBox(self)
            box.setStyleSheet(DIALOG_QSS)
            box.setIcon(QMessageBox.Warning)
            box.setWindowTitle("无法读取图标")
            box.setText("未能从所选文件中提取有效图像，请换一张 PNG / ICO 图片或 EXE 程序试试。")
            box.addButton("知道了", QMessageBox.AcceptRole)
            box.exec()

    def _on_reset_custom_icon(self):
        if self._selected_item_path:
            self.ctrl.clear_item_custom_icon(self._selected_item_path)

    def _on_rename_item(self):
        if not self._selected_item_path:
            return
        new_name = self.edit_item_name.text().strip()
        if not new_name:
            return
        new_path = self.ctrl.rename_partition_item(self._selected_item_path, new_name)
        if new_path is not None:
            self._selected_item_path = new_path
            self.refresh_all()

    def _on_move_item_group(self):
        if not self._selected_item_path:
            return
        target_key = str(self.combo_item_move.currentData() or "")
        if target_key:
            new_path = self.ctrl.move_shortcut_between_groups(self._selected_item_path, target_key)
            if new_path is not None:
                self._selected_item_path = new_path
                self.refresh_all()

    def _on_open_item_loc(self):
        if self._selected_item_path:
            self.ctrl.open_item_location(self._selected_item_path)

    def _on_remove_item(self):
        if self._selected_item_path:
            self.ctrl.remove_partition_item(self._selected_item_path)
            self._selected_item_path = None
            self.refresh_all()

    def _on_clear_icon_cache(self):
        self.ctrl.clear_icon_cache()
        self.refresh_all()

    # =========================================================================
    # Page 4: Global Hotkeys
    # =========================================================================
    def _build_hotkeys_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(16)

        t = QLabel("全局热键")
        t.setProperty("class", "pageTitle")
        s = QLabel("点击按钮即可直接按下新组合键录制；按 Backspace 可清除禁用，自动检测系统热键占用冲突")
        s.setProperty("class", "pageSub")
        lay.addWidget(t)
        lay.addWidget(s)

        c_hk, l_hk = _make_card("⚡ 快捷唤出与隐身热键")

        self.sw_double_ctrl = AuroraToggleSwitch()
        self.sw_double_ctrl.toggled.connect(
            lambda v: not self._syncing and self._apply_hotkey_change(double_ctrl_spotlight=v)
        )
        l_hk.addLayout(_make_setting_row(
            "连按两下 Ctrl 唤出极光全局搜索",
            "类似 Raycast / Listary 的零心智负担手势，单独快速敲击两次 Ctrl 键立即呼出（不影响组合键）",
            self.sw_double_ctrl,
        ))

        self.rec_spotlight, self.lbl_st_spot, row_spot = self._build_hotkey_row(
            "极光全局搜索 (Spotlight) 组合键",
            "在任意全屏或桌面窗口下秒开搜索面板",
            on_change=lambda spec: self._apply_hotkey_change(spotlight=spec),
        )
        l_hk.addLayout(row_spot)

        self.rec_toggle, self.lbl_st_toggle, row_toggle = self._build_hotkey_row(
            "一键隐藏 / 显示全部桌面卡片",
            "快速淡出或唤回桌面上的所有极光胶囊与便签卡",
            on_change=lambda spec: self._apply_hotkey_change(toggle_cards=spec),
        )
        l_hk.addLayout(row_toggle)

        self.rec_settings, self.lbl_st_settings, row_settings = self._build_hotkey_row(
            "打开极光设置中心",
            "随时呼出本设置窗口（留空则仅通过托盘或右键菜单打开）",
            on_change=lambda spec: self._apply_hotkey_change(settings=spec),
        )
        l_hk.addLayout(row_settings)

        rst_row = QHBoxLayout()
        rst_row.addStretch(1)
        b_rst_hk = QPushButton("↺ 恢复默认热键 (双击 Ctrl / Alt+S / Alt+~ / Alt+,)")
        b_rst_hk.clicked.connect(self._on_reset_hotkeys)
        rst_row.addWidget(b_rst_hk)
        l_hk.addLayout(rst_row)

        lay.addWidget(c_hk)
        lay.addStretch(1)
        return _wrap_scroll(page)

    def _build_hotkey_row(self, title: str, desc: str, on_change):
        wrap = QWidget()
        h = QHBoxLayout(wrap)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        status_lbl = QLabel("")
        status_lbl.setStyleSheet("font-size: 11px;")
        rec = HotkeyRecorderButton()
        rec.hotkeyChanged.connect(on_change)
        btn_clr = QPushButton("清除")
        btn_clr.setFixedWidth(56)
        btn_clr.clicked.connect(lambda: (rec.set_spec(""), on_change("")))
        h.addWidget(status_lbl)
        h.addWidget(rec)
        h.addWidget(btn_clr)
        return rec, status_lbl, _make_setting_row(title, desc, wrap)

    def _apply_hotkey_change(self, **kwargs):
        self.ctrl.update_hotkeys(**kwargs)
        self._refresh_hotkeys_page()

    def _on_reset_hotkeys(self):
        self.ctrl.reset_default_hotkeys()
        self._refresh_hotkeys_page()

    def _refresh_hotkeys_page(self):
        hk = self.ctrl.hotkeys_cfg
        st = self.ctrl.hotkey_status
        self.sw_double_ctrl.setChecked(bool(hk.get("double_ctrl_spotlight", True)))
        self.rec_spotlight.set_spec(hk.get("spotlight", ""))
        self.rec_toggle.set_spec(hk.get("toggle_cards", ""))
        self.rec_settings.set_spec(hk.get("settings", ""))

        for key, spec_val, lbl in [
            ("spotlight", hk.get("spotlight", ""), self.lbl_st_spot),
            ("toggle_cards", hk.get("toggle_cards", ""), self.lbl_st_toggle),
            ("settings", hk.get("settings", ""), self.lbl_st_settings),
        ]:
            if not spec_val:
                lbl.setText("已停用")
                lbl.setStyleSheet("color: #64748b; font-size: 11px;")
            elif st.get(key, True):
                lbl.setText("✓ 已生效")
                lbl.setStyleSheet("color: #34d399; font-size: 11px; font-weight: 600;")
            else:
                lbl.setText("⚠️ 热键冲突（已被占用）")
                lbl.setStyleSheet("color: #fbbf24; font-size: 11px; font-weight: 600;")

    # =========================================================================
    # Page 5: Appearance, Clock & Taskbar
    # =========================================================================
    def _build_appearance_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(16)

        t = QLabel("外观 · 艺术时钟 · 透明任务栏")
        t.setProperty("class", "pageTitle")
        s = QLabel("调校极光毛玻璃色温、8 款高定桌面时钟排版与原生 XAML 任务栏透明引擎")
        s.setProperty("class", "pageSub")
        lay.addWidget(t)
        lay.addWidget(s)

        # Card 1: Theme & Opacity
        c_vis, l_vis = _make_card("🌌 极光流光色温与毛玻璃通透度")
        self.combo_theme = QComboBox()
        for t_key, (_, _, _, t_label) in AURORA_THEMES.items():
            self.combo_theme.addItem(t_label, t_key)
        self.combo_theme.currentIndexChanged.connect(
            lambda: not self._syncing and self.ctrl.set_aurora_theme(str(self.combo_theme.currentData()))
        )
        l_vis.addLayout(_make_setting_row("极光主题色温", "同步作用于卡片追光描边、全局搜索高亮与艺术时钟点缀色", self.combo_theme))

        self.combo_opacity = QComboBox()
        for o_key, (_, o_label) in GLASS_OPACITY_LEVELS.items():
            self.combo_opacity.addItem(o_label, o_key)
        self.combo_opacity.currentIndexChanged.connect(
            lambda: not self._syncing and self.ctrl.set_glass_opacity(str(self.combo_opacity.currentData()))
        )
        l_vis.addLayout(_make_setting_row("毛玻璃底色通透度", "针对亮色或暗色壁纸调节卡片玻璃底色浓度", self.combo_opacity))
        lay.addWidget(c_vis)

        # Card 2: Clock
        c_clk, l_clk = _make_card("🕒 右上角高定艺术桌面时钟")
        self.sw_clk_en = AuroraToggleSwitch()
        self.sw_clk_en.toggled.connect(lambda v: not self._syncing and self.ctrl.clock_widget._set_enabled(v))
        l_clk.addLayout(_make_setting_row("启用桌面艺术时钟", "替代 Rainmeter，无秒针模式下每分钟仅重绘一次，零后台负担", self.sw_clk_en))

        self.combo_clk_style = QComboBox()
        for s_key, s_lbl in CLOCK_STYLES.items():
            self.combo_clk_style.addItem(s_lbl, s_key)
        self.combo_clk_style.currentIndexChanged.connect(
            lambda: not self._syncing and self.ctrl.clock_widget._set_style(str(self.combo_clk_style.currentData()))
        )
        l_clk.addLayout(_make_setting_row("时钟字体排版风格", "8 款手工调校中西文字体排版，切换时平滑交叉淡入", self.combo_clk_style))

        self.combo_clk_scale = QComboBox()
        for sc_val, sc_lbl in [
            (0.85, "精致小巧 (85%)"),
            (1.00, "黄金标准 (100%)"),
            (1.15, "舒展大气 (115%)"),
            (1.30, "巨幕醒目 (130%)"),
            (1.50, "殿堂巨幅 (150%)"),
        ]:
            self.combo_clk_scale.addItem(sc_lbl, sc_val)
        self.combo_clk_scale.currentIndexChanged.connect(
            lambda: not self._syncing and self.ctrl.clock_widget._set_scale(float(self.combo_clk_scale.currentData()))
        )
        l_clk.addLayout(_make_setting_row("时钟显示比例", "适配 1080p / 2K / 4K 不同显示器观感", self.combo_clk_scale))

        self.sw_clk_24h = AuroraToggleSwitch()
        self.sw_clk_24h.toggled.connect(lambda v: not self._syncing and self.ctrl.clock_widget._set_24h(v))
        l_clk.addLayout(_make_setting_row("使用 24 小时制", "关闭后以 12 小时制 + AM/PM 展示", self.sw_clk_24h))

        self.sw_clk_sec = AuroraToggleSwitch()
        self.sw_clk_sec.toggled.connect(lambda v: not self._syncing and self.ctrl.clock_widget._set_seconds(v))
        l_clk.addLayout(_make_setting_row("显示秒数 (:SS)", "精确对齐每秒边界刷新", self.sw_clk_sec))

        self.sw_clk_lock = AuroraToggleSwitch()
        self.sw_clk_lock.toggled.connect(lambda v: not self._syncing and self.ctrl.clock_widget._set_locked(v))
        l_clk.addLayout(_make_setting_row("锁定时钟位置", "防止鼠标拖动时钟", self.sw_clk_lock))

        self.sw_clk_ct = AuroraToggleSwitch()
        self.sw_clk_ct.toggled.connect(lambda v: not self._syncing and self.ctrl.clock_widget._set_click_through(v))
        l_clk.addLayout(_make_setting_row("鼠标点击穿透 (Click-Through)", "开启后鼠标完全穿透时钟直达下层壁纸，可在设置中心随时关闭", self.sw_clk_ct))

        clk_btn_row = QHBoxLayout()
        clk_btn_row.addStretch(1)
        b_clk_rst = QPushButton("重置时钟回主屏右上角")
        b_clk_rst.clicked.connect(self.ctrl.clock_widget._reset_top_right)
        clk_btn_row.addWidget(b_clk_rst)
        l_clk.addLayout(clk_btn_row)
        lay.addWidget(c_clk)

        # Card 3: Taskbar
        c_tb, l_tb = _make_card("🪟 自研原生全透明任务栏引擎 (AuroraTaskbarTAP)")
        self.combo_tb_mode = QComboBox()
        for m_key, (m_lbl, _) in TASKBAR_MODES.items():
            self.combo_tb_mode.addItem(m_lbl, m_key)
        self.combo_tb_mode.currentIndexChanged.connect(
            lambda: not self._syncing and self.ctrl.taskbar_engine._set_mode(str(self.combo_tb_mode.currentData()))
        )
        l_tb.addLayout(_make_setting_row("任务栏视觉模式", "无需 TranslucentTB，原生注入 Explorer XAML 渲染树消除黑底", self.combo_tb_mode))

        self.sw_tb_max_acrylic = AuroraToggleSwitch()
        self.sw_tb_max_acrylic.toggled.connect(
            lambda v: not self._syncing and self.ctrl.taskbar_engine._set_max_win_acrylic(v)
        )
        l_tb.addLayout(_make_setting_row(
            "窗口最大化时自动切换深色毛玻璃",
            "桌面无遮挡时保持全透明看壁纸；当任意窗口全屏最大化时自动切换深色毛玻璃，防止白底网页刺眼看不清图标",
            self.sw_tb_max_acrylic,
        ))

        self.sw_tb_line = AuroraToggleSwitch()
        self.sw_tb_line.toggled.connect(lambda v: not self._syncing and self.ctrl.taskbar_engine._set_show_line(v))
        l_tb.addLayout(_make_setting_row("保留任务栏顶部 1px 分割细线", "关闭时壁纸从屏幕顶部无缝贯穿到底部", self.sw_tb_line))
        lay.addWidget(c_tb)

        lay.addStretch(1)
        return _wrap_scroll(page)

    def _refresh_appearance_page(self):
        for i in range(self.combo_theme.count()):
            if self.combo_theme.itemData(i) == self.ctrl.theme_key:
                self.combo_theme.setCurrentIndex(i)
                break
        for i in range(self.combo_opacity.count()):
            if self.combo_opacity.itemData(i) == self.ctrl.opacity_key:
                self.combo_opacity.setCurrentIndex(i)
                break

        cc = self.ctrl.clock_cfg
        self.sw_clk_en.setChecked(bool(cc.get("enabled", True)))
        for i in range(self.combo_clk_style.count()):
            if self.combo_clk_style.itemData(i) == cc.get("style", "nordic_modern"):
                self.combo_clk_style.setCurrentIndex(i)
                break
        cur_sc = float(cc.get("scale", 1.0))
        for i in range(self.combo_clk_scale.count()):
            if abs(float(self.combo_clk_scale.itemData(i)) - cur_sc) < 0.04:
                self.combo_clk_scale.setCurrentIndex(i)
                break
        self.sw_clk_24h.setChecked(bool(cc.get("use_24h", True)))
        self.sw_clk_sec.setChecked(bool(cc.get("show_seconds", False)))
        self.sw_clk_lock.setChecked(bool(cc.get("locked", False)))
        self.sw_clk_ct.setChecked(bool(cc.get("click_through", False)))

        tc = self.ctrl.taskbar_cfg
        for i in range(self.combo_tb_mode.count()):
            if self.combo_tb_mode.itemData(i) == tc.get("mode", "clear"):
                self.combo_tb_mode.setCurrentIndex(i)
                break
        self.sw_tb_max_acrylic.setChecked(bool(tc.get("max_win_acrylic", False)))
        self.sw_tb_line.setChecked(bool(tc.get("show_line", False)))

    # =========================================================================
    # Master Refresh
    # =========================================================================
    def _on_toggle_desktop_cards(self):
        self.ctrl.toggle_all_visibility()
        self._sync_vis_btn()

    def _sync_vis_btn(self):
        if hasattr(self, "btn_qa_vis"):
            self.btn_qa_vis.setText("🙈 隐藏卡片" if self.ctrl.visible_state else "✨ 显示卡片")

    def refresh_all(self):
        self._syncing = True
        try:
            self._sync_vis_btn()
            self.sw_hide_desk_icons.setChecked(self.ctrl.are_desktop_icons_hidden())
            self.sw_autorun.setChecked(self.ctrl.is_autorun_enabled())
            self.sw_dbl_hide.setChecked(self.ctrl.double_click_hide)
            self.sw_lock_pos.setChecked(self.ctrl.lock_positions)
            self.sw_memo.setChecked(self.ctrl.show_memo)
            self._refresh_groups_page()
            self._refresh_icons_page()
            self._refresh_hotkeys_page()
            self._refresh_appearance_page()
        finally:
            self._syncing = False
