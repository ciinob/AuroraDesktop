from datetime import datetime
from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QActionGroup, QColor, QFont, QGuiApplication, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QMenu, QWidget

from widgets import MENU_QSS, make_apple_font
from win32_utils import (
    GWL_EXSTYLE,
    MA_NOACTIVATE,
    SC_MINIMIZE,
    WM_MOUSEACTIVATE,
    WM_SYSCOMMAND,
    WS_EX_NOACTIVATE,
    WS_EX_TOOLWINDOW,
    pin_window_to_desktop_bottom,
    send_to_bottom,
    user32,
)

WS_EX_TRANSPARENT = 0x00000020
WS_EX_LAYERED = 0x00080000

WEEKDAY_CN = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]

CLOCK_STYLES = {
    "aurora_signature": "✨ 极光艺术签名风 (Ruthligos 手写星期 + 果味数字)",
    "rainmeter_classic": "🕰️ Rainmeter 原版复刻 (Ruthligos + GeosansLight)",
    "apple_sonoma": "🍎 macOS 锁屏极简风 (纯正果味大字 + 中文日期)",
}


class AuroraClockWidget(QWidget):
    """Native desktop-pinned minimalist white clock replacing Rainmeter Welfare\\Clock.
    Stays visible even when organizer cards are hidden ('只留纯粹壁纸与时钟').
    """
    configChanged = Signal()

    BASE_W = 480
    BASE_H = 215

    def __init__(self, clock_cfg: dict, theme_provider=None, parent=None):
        super().__init__(parent)
        self.cfg = clock_cfg
        self._theme_provider = theme_provider or (lambda: (QColor("#2dd4bf"), QColor("#38bdf8"), QColor("#a855f7")))
        self._dragging = False
        self._drag_offset = QPoint()
        self._pinned_init = False

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        self._apply_size_and_pos()

        # Refresh every 500ms so minute/second transition is exact with ~0.00% CPU usage
        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(500)
        self._tick_timer.timeout.connect(self.update)
        self._tick_timer.start()

    def _scale(self) -> float:
        return float(self.cfg.get("scale", 1.0))

    def _apply_size_and_pos(self):
        sc = self._scale()
        w = int(round(self.BASE_W * sc))
        h = int(round(self.BASE_H * sc))
        self.setFixedSize(w, h)

        x = self.cfg.get("x")
        y = self.cfg.get("y")
        if x is None or y is None:
            # Synced from Rainmeter Welfare\Clock: top-right of primary screen (rect 2133..2560, y=0)
            screen = QGuiApplication.primaryScreen()
            geom = screen.geometry() if screen else QRectF(0, 0, 2560, 1440)
            x = int(geom.right() - w - 12)
            y = int(geom.top() + 4)
            self.cfg["x"] = x
            self.cfg["y"] = y
        self.move(int(x), int(y))

    def apply_click_through(self):
        hwnd = int(self.winId())
        if not hwnd:
            return
        ex = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        base = ex | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_LAYERED
        if self.cfg.get("click_through", False):
            new_ex = base | WS_EX_TRANSPARENT
        else:
            new_ex = base & ~WS_EX_TRANSPARENT
        user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, new_ex)

    def ensure_desktop_pinned(self):
        hwnd = int(self.winId())
        pin_window_to_desktop_bottom(hwnd)
        self.apply_click_through()
        self._pinned_init = True

    def showEvent(self, event):
        super().showEvent(event)
        if not self._pinned_init:
            QTimer.singleShot(15, self.ensure_desktop_pinned)
        else:
            send_to_bottom(int(self.winId()))

    def nativeEvent(self, eventType, message):
        if eventType == b"windows_generic_MSG" or eventType == "windows_generic_MSG":
            import ctypes
            msg = ctypes.wintypes.MSG.from_address(int(message))
            if msg.message == WM_SYSCOMMAND and (msg.wParam & 0xFFF0) == SC_MINIMIZE:
                return True, 0
            elif msg.message == WM_MOUSEACTIVATE:
                return True, MA_NOACTIVATE
        return super().nativeEvent(eventType, message)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and not self.cfg.get("locked", False):
            self._dragging = True
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging and (event.buttons() & Qt.LeftButton):
            new_pt = event.globalPosition().toPoint() - self._drag_offset
            # Snap to screen edges within 14px (matches Rainmeter SnapEdges=1 & KeepOnScreen=1)
            screen = QGuiApplication.screenAt(event.globalPosition().toPoint()) or QGuiApplication.primaryScreen()
            if screen:
                sg = screen.geometry()
                if abs(new_pt.x() - sg.left()) <= 14:
                    new_pt.setX(sg.left())
                elif abs((new_pt.x() + self.width()) - (sg.right() + 1)) <= 14:
                    new_pt.setX(sg.right() + 1 - self.width())
                if abs(new_pt.y() - sg.top()) <= 14:
                    new_pt.setY(sg.top())
            self.move(new_pt)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._dragging:
            self._dragging = False
            self.cfg["x"] = self.x()
            self.cfg["y"] = self.y()
            self.configChanged.emit()
        super().mouseReleaseEvent(event)

    def build_clock_menu(self, parent_menu: QMenu | None = None) -> QMenu:
        menu = parent_menu or QMenu(self)
        menu.setStyleSheet(MENU_QSS)

        act_vis = menu.addAction("启用右上角极简桌面时钟")
        act_vis.setCheckable(True)
        act_vis.setChecked(bool(self.cfg.get("enabled", True)))
        act_vis.toggled.connect(self._set_enabled)

        menu.addSeparator()
        style_menu = menu.addMenu("🎨 时钟视觉风格")
        style_menu.setStyleSheet(MENU_QSS)
        cur_style = self.cfg.get("style", "aurora_signature")
        grp_s = QActionGroup(menu)
        for s_key, s_label in CLOCK_STYLES.items():
            a = style_menu.addAction(s_label)
            a.setCheckable(True)
            a.setChecked(s_key == cur_style)
            grp_s.addAction(a)
            a.triggered.connect(lambda checked=False, k=s_key: self._set_style(k))

        scale_menu = menu.addMenu("🔍 时钟尺寸比例")
        scale_menu.setStyleSheet(MENU_QSS)
        cur_sc = round(float(self.cfg.get("scale", 1.0)), 2)
        grp_sc = QActionGroup(menu)
        for sc_val, sc_lbl in [(0.85, "紧凑 (85%)"), (1.0, "标准原版尺寸 (100%)"), (1.15, "舒展 (115%)"), (1.30, "大屏醒目 (130%)")]:
            a = scale_menu.addAction(sc_lbl)
            a.setCheckable(True)
            a.setChecked(abs(cur_sc - sc_val) < 0.03)
            grp_sc.addAction(a)
            a.triggered.connect(lambda checked=False, v=sc_val: self._set_scale(v))

        menu.addSeparator()
        act_24h = menu.addAction("使用 24 小时制")
        act_24h.setCheckable(True)
        act_24h.setChecked(bool(self.cfg.get("use_24h", True)))
        act_24h.toggled.connect(self._set_24h)

        act_sec = menu.addAction("显示秒数 (:SS)")
        act_sec.setCheckable(True)
        act_sec.setChecked(bool(self.cfg.get("show_seconds", False)))
        act_sec.toggled.connect(self._set_seconds)

        act_lock = menu.addAction("锁定时钟位置")
        act_lock.setCheckable(True)
        act_lock.setChecked(bool(self.cfg.get("locked", False)))
        act_lock.toggled.connect(self._set_locked)

        act_ct = menu.addAction("鼠标点击穿透 (Click-Through)")
        act_ct.setCheckable(True)
        act_ct.setChecked(bool(self.cfg.get("click_through", False)))
        act_ct.toggled.connect(self._set_click_through)

        act_reset_pos = menu.addAction("重置回右上角黄金位置")
        act_reset_pos.triggered.connect(self._reset_top_right)

        return menu

    def contextMenuEvent(self, event):
        m = self.build_clock_menu()
        m.exec(event.globalPos())

    def _set_enabled(self, val: bool):
        self.cfg["enabled"] = val
        self.setVisible(val)
        self.configChanged.emit()

    def _set_style(self, style_key: str):
        self.cfg["style"] = style_key
        self.update()
        self.configChanged.emit()

    def _set_scale(self, sc: float):
        self.cfg["scale"] = sc
        self._apply_size_and_pos()
        self.update()
        self.configChanged.emit()

    def _set_24h(self, val: bool):
        self.cfg["use_24h"] = val
        self.update()
        self.configChanged.emit()

    def _set_seconds(self, val: bool):
        self.cfg["show_seconds"] = val
        self.update()
        self.configChanged.emit()

    def _set_locked(self, val: bool):
        self.cfg["locked"] = val
        self.configChanged.emit()

    def _set_click_through(self, val: bool):
        self.cfg["click_through"] = val
        self.apply_click_through()
        self.configChanged.emit()

    def _reset_top_right(self):
        self.cfg["x"] = None
        self.cfg["y"] = None
        self._apply_size_and_pos()
        self.configChanged.emit()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)

        # Keep micro-alpha 1/255 hit region when unlocked & non-click-through so dragging anywhere on clock works smoothly
        if not self.cfg.get("click_through", False):
            painter.fillRect(self.rect(), QColor(0, 0, 0, 1))

        now = datetime.now()
        sc = self._scale()
        w, h = float(self.width()), float(self.height())
        style = self.cfg.get("style", "aurora_signature")
        use_24h = bool(self.cfg.get("use_24h", True))
        show_sec = bool(self.cfg.get("show_seconds", False))

        sec_fmt = ":%S" if show_sec else ""
        if use_24h:
            time_str = now.strftime(f"%H:%M{sec_fmt}")
            ampm_str = ""
        else:
            time_str = now.strftime(f"%I:%M{sec_fmt}").lstrip("0") or "12:00"
            ampm_str = now.strftime(" %p")

        weekday_en = now.strftime("%A")
        date_en = f"{now.day:02d} {now.strftime('%B')}"
        date_cn = f"{now.month}月{now.day}日  {WEEKDAY_CN[now.weekday()]}"

        if style == "apple_sonoma":
            # Pure Apple macOS Sonoma Lock Screen Clock
            t_font = make_apple_font(int(round(62 * sc)), QFont.DemiBold, -1.2)
            painter.setFont(t_font)
            t_rect = QRectF(0.0, 22.0 * sc, w, 74.0 * sc)
            painter.setPen(QColor(0, 0, 0, 105))
            painter.drawText(t_rect.translated(0, 2.0), Qt.AlignHCenter | Qt.AlignVCenter, time_str + ampm_str)
            painter.setPen(QColor(255, 255, 255, 248))
            painter.drawText(t_rect, Qt.AlignHCenter | Qt.AlignVCenter, time_str + ampm_str)

            d_font = make_apple_font(int(round(17 * sc)), QFont.Medium, 0.8)
            painter.setFont(d_font)
            d_rect = QRectF(0.0, 98.0 * sc, w, 30.0 * sc)
            painter.setPen(QColor(0, 0, 0, 95))
            painter.drawText(d_rect.translated(0, 1.5), Qt.AlignHCenter | Qt.AlignVCenter, date_cn)
            painter.setPen(QColor(245, 250, 255, 225))
            painter.drawText(d_rect, Qt.AlignHCenter | Qt.AlignVCenter, date_cn)
            return

        # 1. Background Ruthligos Script Weekday Watermark (Synced 1:1 with Welfare\Clock [MeterDay], unclipped!)
        script_font = QFont("Ruthligos")
        script_font.setPixelSize(int(round(62 * sc)))
        script_font.setStyleStrategy(QFont.PreferAntialias)
        painter.setFont(script_font)
        day_rect = QRectF(0.0, 8.0 * sc, w, h - 10.0 * sc)
        painter.setPen(QColor(255, 255, 255, 92))
        painter.drawText(day_rect, Qt.AlignHCenter | Qt.AlignTop | Qt.TextDontClip, weekday_en)

        # 2. Foreground Time ([Meter24hTime] / [Meter12hTime])
        if style == "rainmeter_classic":
            time_font = QFont("GeosansLight")
            time_font.setPixelSize(int(round(52 * sc)))
            time_font.setLetterSpacing(QFont.AbsoluteSpacing, 1.8 * sc)
            date_font = QFont("GeosansLight")
            date_font.setPixelSize(int(round(25 * sc)))
            date_font.setLetterSpacing(QFont.AbsoluteSpacing, 1.4 * sc)
        else:
            # aurora_signature: Ruthligos calligraphic background + crisp Apple SF Pro (Inter) numbers!
            time_font = make_apple_font(int(round(52 * sc)), QFont.Light, 1.6 * sc)
            date_font = make_apple_font(int(round(20 * sc)), QFont.Normal, 1.4 * sc)

        painter.setFont(time_font)
        time_rect = QRectF(0.0, 52.0 * sc, w, 64.0 * sc)
        painter.setPen(QColor(0, 0, 0, 95))
        painter.drawText(time_rect.translated(0, 1.5), Qt.AlignHCenter | Qt.AlignVCenter, time_str + ampm_str)
        painter.setPen(QColor(255, 255, 255, 252))
        painter.drawText(time_rect, Qt.AlignHCenter | Qt.AlignVCenter, time_str + ampm_str)

        # 3. Date below Time ([MeterDate]: "%d %B", e.g. "25 November")
        painter.setFont(date_font)
        date_rect = QRectF(0.0, 112.0 * sc, w, 36.0 * sc)
        painter.setPen(QColor(0, 0, 0, 85))
        painter.drawText(date_rect.translated(0, 1.0), Qt.AlignHCenter | Qt.AlignVCenter, date_en)
        painter.setPen(QColor(255, 255, 255, 236))
        painter.drawText(date_rect, Qt.AlignHCenter | Qt.AlignVCenter, date_en)
