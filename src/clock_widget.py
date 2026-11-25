from datetime import datetime
from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QActionGroup,
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
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
    "nordic_modern": "✨ 极光纤雅几何风 (Nordic Outfit · 默认推荐)",
    "editorial_serif": "🏛️ 高定古典衬线风 (Apple Editorial · Cormorant)",
    "apple_sonoma": "🍎 macOS 锁屏中文风 (果味极简排版)",
    "script_layered": "✍️ 手写艺术分层风 (无遮挡上下分层)",
}


class AuroraClockWidget(QWidget):
    """Refined luxury minimalist desktop clock (Outfit ExtraLight / Cormorant Editorial / Sonoma).
    Uses optically-centered glowing twin-dot colon and silk-white gradient numerals.
    """
    configChanged = Signal()

    BASE_W = 360
    BASE_H = 165

    def __init__(self, clock_cfg: dict, theme_provider=None, parent=None):
        super().__init__(parent)
        self.cfg = clock_cfg
        if self.cfg.get("style") not in CLOCK_STYLES:
            self.cfg["style"] = "nordic_modern"
        self._theme_provider = theme_provider or (lambda: (QColor("#2dd4bf"), QColor("#38bdf8"), QColor("#a855f7")))
        self._dragging = False
        self._drag_offset = QPoint()
        self._pinned_init = False

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        self._apply_size_and_pos()

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
        screen = QGuiApplication.primaryScreen()
        geom = screen.geometry() if screen else QRectF(0, 0, 2560, 1440)
        if x is None or y is None or int(x) + w > geom.right() + 20:
            x = int(geom.right() - w - 28)
            y = int(geom.top() + 22)
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
            screen = QGuiApplication.screenAt(event.globalPosition().toPoint()) or QGuiApplication.primaryScreen()
            if screen:
                sg = screen.geometry()
                if abs((new_pt.x() + self.width()) - (sg.right() - 24)) <= 14:
                    new_pt.setX(sg.right() - 24 - self.width())
                if abs(new_pt.y() - (sg.top() + 22)) <= 14:
                    new_pt.setY(sg.top() + 22)
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
        style_menu = menu.addMenu("🎨 时钟高定字体风格")
        style_menu.setStyleSheet(MENU_QSS)
        cur_style = self.cfg.get("style", "nordic_modern")
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
        for sc_val, sc_lbl in [(0.85, "精致小巧 (85%)"), (1.0, "黄金标准 (100%)"), (1.15, "舒展大气 (115%)"), (1.30, "巨幕醒目 (130%)")]:
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

    def _draw_optical_time(
        self,
        painter: QPainter,
        hh: str,
        mm: str,
        ss: str,
        font: QFont,
        center_x: float,
        baseline_y: float,
        sc: float,
    ):
        """Draw HH and MM separated by optically-centered twin circular dots + silk-white vertical gradient."""
        painter.setFont(font)
        fm = QFontMetrics(font)
        cap_h = fm.capHeight()
        colon_gap = 22.0 * sc

        w_hh = fm.horizontalAdvance(hh)
        w_mm = fm.horizontalAdvance(mm)

        sec_font = make_apple_font(int(round(20 * sc)), QFont.Light, 0.5)
        fm_sec = QFontMetrics(sec_font)
        w_ss = (fm_sec.horizontalAdvance(ss) + 8.0 * sc) if ss else 0.0

        total_w = w_hh + colon_gap + w_mm + w_ss
        start_x = center_x - total_w / 2.0

        path = QPainterPath()
        path.addText(QPointF(start_x, baseline_y), font, hh)
        mm_x = start_x + w_hh + colon_gap
        path.addText(QPointF(mm_x, baseline_y), font, mm)
        if ss:
            path.addText(QPointF(mm_x + w_mm + 8.0 * sc, baseline_y - 2.0 * sc), sec_font, ss)

        # Optically centered twin circular dots for ':'
        dot_cx = start_x + w_hh + colon_gap / 2.0
        mid_y = baseline_y - cap_h * 0.48
        dot_r = 2.5 * sc
        dot_sep = cap_h * 0.21
        path.addEllipse(QPointF(dot_cx, mid_y - dot_sep), dot_r, dot_r)
        path.addEllipse(QPointF(dot_cx, mid_y + dot_sep), dot_r, dot_r)

        # Soft subtle drop shadow
        painter.save()
        painter.translate(0.0, 2.0 * sc)
        painter.fillPath(path, QColor(0, 0, 0, 72))
        painter.restore()

        # Silk-white to ice-mist vertical gradient fill
        grad = QLinearGradient(0.0, baseline_y - cap_h, 0.0, baseline_y + 4.0)
        grad.setColorAt(0.0, QColor(255, 255, 255, 252))
        grad.setColorAt(1.0, QColor(232, 242, 255, 222))
        painter.fillPath(path, QBrush(grad))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)

        if not self.cfg.get("click_through", False):
            painter.fillRect(self.rect(), QColor(0, 0, 0, 1))

        now = datetime.now()
        sc = self._scale()
        w, h = float(self.width()), float(self.height())
        cx = w / 2.0
        style = self.cfg.get("style", "nordic_modern")
        use_24h = bool(self.cfg.get("use_24h", True))
        show_sec = bool(self.cfg.get("show_seconds", False))

        hh = now.strftime("%H") if use_24h else (now.strftime("%I").lstrip("0") or "12")
        mm = now.strftime("%M")
        ss = now.strftime("%S") if show_sec else ("" if use_24h else now.strftime("%p"))

        weekday_upper = now.strftime("%A").upper()
        date_upper = f"{weekday_upper}  ·  {now.strftime('%b').upper()} {now.day:02d}"
        date_cn = f"{now.month}月{now.day}日  ·  {WEEKDAY_CN[now.weekday()]}"
        c1, _, c2 = self._theme_provider()

        if style == "editorial_serif":
            # Luxury Editorial Serif (Apple iOS Classic Serif Lock Screen aesthetic)
            t_font = QFont("Cormorant Garamond Light")
            t_font.setPixelSize(int(round(86 * sc)))
            t_font.setWeight(QFont.Light)
            t_font.setStyleStrategy(QFont.PreferAntialias)
            self._draw_optical_time(painter, hh, mm, ss, t_font, cx, 84.0 * sc, sc)

            # Delicate aurora hairline divider
            line_grad = QLinearGradient(cx - 48 * sc, 0, cx + 48 * sc, 0)
            line_grad.setColorAt(0.0, QColor(255, 255, 255, 0))
            lc = QColor(c1); lc.setAlpha(135)
            line_grad.setColorAt(0.5, lc)
            line_grad.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.setPen(QPen(line_grad, 1.0))
            painter.drawLine(QPointF(cx - 48 * sc, 99.0 * sc), QPointF(cx + 48 * sc, 99.0 * sc))

            d_font = make_apple_font(int(round(12 * sc)), QFont.Medium, 2.8 * sc)
            painter.setFont(d_font)
            d_rect = QRectF(0.0, 108.0 * sc, w, 26.0 * sc)
            painter.setPen(QColor(0, 0, 0, 75))
            painter.drawText(d_rect.translated(0, 1.0), Qt.AlignHCenter | Qt.AlignVCenter, date_upper)
            painter.setPen(QColor(242, 248, 255, 215))
            painter.drawText(d_rect, Qt.AlignHCenter | Qt.AlignVCenter, date_upper)
            return

        if style == "apple_sonoma":
            # macOS Sonoma Lock Screen: Chinese Eyebrow Date ABOVE sleek rounded numerals
            d_font = make_apple_font(int(round(14 * sc)), QFont.Medium, 1.2 * sc)
            painter.setFont(d_font)
            d_rect = QRectF(0.0, 12.0 * sc, w, 26.0 * sc)
            painter.setPen(QColor(0, 0, 0, 80))
            painter.drawText(d_rect.translated(0, 1.0), Qt.AlignHCenter | Qt.AlignVCenter, date_cn)
            painter.setPen(QColor(245, 250, 255, 222))
            painter.drawText(d_rect, Qt.AlignHCenter | Qt.AlignVCenter, date_cn)

            t_font = QFont("Outfit Thin")
            t_font.setPixelSize(int(round(74 * sc)))
            t_font.setWeight(QFont.Light)
            t_font.setStyleStrategy(QFont.PreferAntialias)
            self._draw_optical_time(painter, hh, mm, ss, t_font, cx, 106.0 * sc, sc)
            return

        if style == "script_layered":
            # Cleanly separated Ruthligos Script Weekday ABOVE Outfit ExtraLight Time (zero overlap!)
            s_font = QFont("Ruthligos")
            s_font.setPixelSize(int(round(44 * sc)))
            s_font.setStyleStrategy(QFont.PreferAntialias)
            painter.setFont(s_font)
            s_rect = QRectF(0.0, 2.0 * sc, w, 58.0 * sc)
            painter.setPen(QColor(255, 255, 255, 165))
            painter.drawText(s_rect, Qt.AlignHCenter | Qt.AlignTop | Qt.TextDontClip, now.strftime("%A"))

            t_font = QFont("Outfit Thin")
            t_font.setPixelSize(int(round(64 * sc)))
            t_font.setWeight(QFont.ExtraLight)
            t_font.setStyleStrategy(QFont.PreferAntialias)
            self._draw_optical_time(painter, hh, mm, ss, t_font, cx, 114.0 * sc, sc)

            d_font = make_apple_font(int(round(12 * sc)), QFont.Normal, 2.2 * sc)
            painter.setFont(d_font)
            d_rect = QRectF(0.0, 124.0 * sc, w, 24.0 * sc)
            painter.setPen(QColor(235, 245, 255, 195))
            painter.drawText(d_rect, Qt.AlignHCenter | Qt.AlignVCenter, f"{now.day:02d} {now.strftime('%B').upper()}")
            return

        # Default: nordic_modern (Outfit ExtraLight sculptural numerals + Aurora whisper divider + airy tracked date)
        t_font = QFont("Outfit Thin")
        t_font.setPixelSize(int(round(76 * sc)))
        t_font.setWeight(QFont.ExtraLight)
        t_font.setStyleStrategy(QFont.PreferAntialias)
        self._draw_optical_time(painter, hh, mm, ss, t_font, cx, 82.0 * sc, sc)

        # Whisper-thin glowing aurora divider line
        line_grad = QLinearGradient(cx - 44 * sc, 0, cx + 44 * sc, 0)
        line_grad.setColorAt(0.0, QColor(255, 255, 255, 0))
        lc1 = QColor(c1); lc1.setAlpha(150)
        lc2 = QColor(c2); lc2.setAlpha(150)
        line_grad.setColorAt(0.35, lc1)
        line_grad.setColorAt(0.65, lc2)
        line_grad.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.setPen(QPen(line_grad, 1.0))
        painter.drawLine(QPointF(cx - 44 * sc, 97.0 * sc), QPointF(cx + 44 * sc, 97.0 * sc))

        d_font = make_apple_font(int(round(12 * sc)), QFont.Medium, 2.6 * sc)
        painter.setFont(d_font)
        d_rect = QRectF(0.0, 106.0 * sc, w, 26.0 * sc)
        painter.setPen(QColor(0, 0, 0, 75))
        painter.drawText(d_rect.translated(0, 1.0), Qt.AlignHCenter | Qt.AlignVCenter, date_upper)
        painter.setPen(QColor(242, 248, 255, 212))
        painter.drawText(d_rect, Qt.AlignHCenter | Qt.AlignVCenter, date_upper)
