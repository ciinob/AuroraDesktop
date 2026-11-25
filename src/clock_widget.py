from datetime import date, datetime

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QActionGroup,
    QBrush,
    QColor,
    QFont,
    QFontMetricsF,
    QGuiApplication,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
)
from PySide6.QtWidgets import QMenu, QWidget

from animator import HighRefreshAnimation
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
    "aurora_gradient": "🌈 极光渐变大字风 (Outfit Light · 主题流光渐变)",
    "aurora_calligraphy": "🌌 极光流光花体风 (Playfair Italic × Great Vibes)",
    "editorial_serif": "🏛️ 高定古典衬线风 (Apple Editorial · Cormorant)",
    "roman_inscription": "🕰️ 罗马铭文古典风 (Cormorant Italic · 罗马纪年)",
    "eastern_ink": "🖌️ 东方书韵行楷风 (干支 · 节气 · 时辰印章)",
    "apple_sonoma": "🍎 macOS 锁屏中文风 (果味极简排版)",
    "script_layered": "✍️ 手写艺术分层风 (无遮挡上下分层)",
}

# Per-style canvas height (base units @ scale 1.0); width is shared so the right edge never jumps.
STYLE_BASE_H = {
    "aurora_gradient": 170,
    "aurora_calligraphy": 178,
    "roman_inscription": 176,
    "editorial_serif": 172,
    "eastern_ink": 178,
    "script_layered": 178,
}

# ---------------------------------------------------------------------------
# Font stacks (all bundled in assets/fonts except the CJK calligraphy fallbacks
# which ship with Windows / Office: 华文行楷 → 楷体 → Noto Serif SC).
# ---------------------------------------------------------------------------
F_OUTFIT = ["Outfit Thin", "Segoe UI Variable Display Light", "Segoe UI Light"]
F_CORMORANT = ["Cormorant Garamond Light", "Palatino Linotype", "Georgia"]
F_PLAYFAIR = ["Playfair Display", "Cormorant Garamond Light", "Georgia"]
F_GREAT_VIBES = ["Great Vibes", "Allura", "Segoe Script"]
F_RUTHLIGOS = ["Ruthligos", "Great Vibes", "Segoe Script"]
F_XINGKAI = ["STXingkai", "华文行楷", "KaiTi", "楷体", "Noto Serif SC"]
F_CN_SERIF = ["Noto Serif SC Light", "Source Han Serif SC", "Noto Serif SC", "SimSun"]

# ---------------------------------------------------------------------------
# Small calendar helpers (干支 / 二十四节气 / 时辰 / Roman numerals / ordinals)
# ---------------------------------------------------------------------------
_STEMS = "甲乙丙丁戊己庚辛壬癸"
_BRANCHES = "子丑寅卯辰巳午未申酉戌亥"
_CN_DIGITS = "〇一二三四五六七八九"

# 21st-century solar term constants (寿星通用公式): day = int(Y*0.2422 + C) - L
_SOLAR_TERMS = [
    ("小寒", 5.4055), ("大寒", 20.12), ("立春", 3.87), ("雨水", 18.73),
    ("惊蛰", 5.63), ("春分", 20.646), ("清明", 4.81), ("谷雨", 20.1),
    ("立夏", 5.52), ("小满", 21.04), ("芒种", 5.678), ("夏至", 21.37),
    ("小暑", 7.108), ("大暑", 22.83), ("立秋", 7.5), ("处暑", 23.13),
    ("白露", 7.646), ("秋分", 23.042), ("寒露", 8.318), ("霜降", 23.438),
    ("立冬", 7.438), ("小雪", 22.36), ("大雪", 7.18), ("冬至", 21.94),
]


def _solar_term_dates(year: int) -> list[tuple[str, date]]:
    y = year % 100
    out = []
    for i, (name, c) in enumerate(_SOLAR_TERMS):
        leap = (y - 1) // 4 if i < 4 else y // 4
        day = int(y * 0.2422 + c) - leap
        out.append((name, date(year, i // 2 + 1, max(1, min(28 if i // 2 == 1 else 30, day)))))
    return out


def current_solar_term(d: date) -> tuple[str, bool]:
    """Return (most recent solar term name, whether today is that term's day)."""
    last = ("冬至", False)
    for name, td in _solar_term_dates(d.year):
        if td <= d:
            last = (name, td == d)
        else:
            break
    return last


def ganzhi_year(d: date) -> str:
    lichun = _solar_term_dates(d.year)[2][1]
    y = d.year if d >= lichun else d.year - 1
    return _STEMS[(y - 4) % 10] + _BRANCHES[(y - 4) % 12]


def shichen(hour: int) -> str:
    return _BRANCHES[((hour + 1) // 2) % 12] + "时"


def cn_number(n: int) -> str:
    if n < 10:
        return _CN_DIGITS[n]
    tens, ones = divmod(n, 10)
    return ("" if tens == 1 else _CN_DIGITS[tens]) + "十" + (_CN_DIGITS[ones] if ones else "")


def roman(n: int) -> str:
    vals = [(1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
            (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]
    res = []
    for v, s in vals:
        while n >= v:
            res.append(s)
            n -= v
    return "".join(res)


def ordinal(n: int) -> str:
    suf = "th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


def _mix(c: QColor, white: float, alpha: int = 255) -> QColor:
    """Blend a theme colour towards white (keeps the aurora hue but stays silk-soft)."""
    r = int(c.red() + (255 - c.red()) * white)
    g = int(c.green() + (255 - c.green()) * white)
    b = int(c.blue() + (255 - c.blue()) * white)
    return QColor(r, g, b, alpha)


def _mkfont(families, px: float, weight=None, italic: bool = False, spacing: float = 0.0) -> QFont:
    f = QFont()
    f.setFamilies(list(families))
    f.setPixelSize(max(1, int(round(px))))
    if weight is not None:
        f.setWeight(weight)
    f.setItalic(italic)
    f.setHintingPreference(QFont.PreferNoHinting)
    f.setStyleStrategy(QFont.PreferAntialias)
    if spacing:
        f.setLetterSpacing(QFont.AbsoluteSpacing, spacing)
    return f


def _digit_bottom(font: QFont, baseline: float) -> float:
    """Worst-case bottom of old-style numerals (3/4/5/7/9 descend) so rules never jitter minute to minute."""
    p = QPainterPath()
    p.addText(QPointF(0.0, baseline), font, "345792")
    return p.boundingRect().bottom()


def _fit_font(font: QFont, text: str, max_w: float, min_px: int = 8) -> QFont:
    f = QFont(font)
    px = f.pixelSize()
    while px > min_px and QFontMetricsF(f).horizontalAdvance(text) > max_w:
        px -= 1
        f.setPixelSize(px)
    return f


class AuroraClockWidget(QWidget):
    """Artistic luxury desktop clock.

    Seven hand-tuned typographic styles (Outfit / Cormorant / Playfair Italic / Great Vibes /
    Ruthligos / 华文行楷), optically-centred colon glyphs tinted with the active aurora theme,
    soft multi-layer halo shadows for legibility on any wallpaper, second/minute-aligned
    ticking (near-zero idle CPU), cross-fade style switching and a hover glass affordance.
    """
    configChanged = Signal()
    openSettingsRequested = Signal()

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
        self._menu_open = False

        self._painters = {
            "nordic_modern": self._paint_nordic,
            "aurora_gradient": self._paint_gradient,
            "aurora_calligraphy": self._paint_calligraphy,
            "editorial_serif": self._paint_editorial,
            "roman_inscription": self._paint_roman,
            "eastern_ink": self._paint_eastern,
            "apple_sonoma": self._paint_sonoma,
            "script_layered": self._paint_script,
        }

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        self._apply_size_and_pos()

        # Hover glass affordance (only when the clock is interactive)
        self._hover = 0.0
        self._hover_anim = HighRefreshAnimation(self)
        self._hover_anim.setDuration(220)
        self._hover_anim.valueChanged.connect(self._on_hover_val)

        # Style cross-fade & static face cache (avoids 20x strokePath re-rasterization during 240Hz hover!)
        self._xfade = 1.0
        self._xfade_pix = None
        self._face_cache_key = None
        self._face_cache_pix: QPixmap | None = None
        self._xfade_anim = HighRefreshAnimation(self)
        self._xfade_anim.setDuration(360)
        self._xfade_anim.valueChanged.connect(self._on_xfade_val)
        self._xfade_anim.finished.connect(self._on_xfade_done)

        # Boundary-aligned ticking: repaint exactly when the displayed digits change.
        self._tick_timer = QTimer(self)
        self._tick_timer.setSingleShot(True)
        self._tick_timer.setTimerType(Qt.PreciseTimer)
        self._tick_timer.timeout.connect(self._on_tick)
        self._schedule_tick()

    # ------------------------------------------------------------------ timing
    def _schedule_tick(self):
        now = datetime.now()
        ms_into_sec = now.microsecond // 1000
        if self.cfg.get("show_seconds", False):
            delay = 1000 - ms_into_sec
        else:
            delay = (59 - now.second) * 1000 + (1000 - ms_into_sec)
        self._tick_timer.start(max(20, delay + 12))

    def _on_tick(self):
        self.update()
        self._schedule_tick()

    def refresh(self):
        """Force an immediate repaint (e.g. after theme change) and re-align the tick."""
        self.update()
        self._schedule_tick()

    # ------------------------------------------------------------- geometry
    def _scale(self) -> float:
        return float(self.cfg.get("scale", 1.0))

    def _base_h(self) -> int:
        return STYLE_BASE_H.get(self.cfg.get("style", "nordic_modern"), self.BASE_H)

    def _apply_size_and_pos(self):
        sc = self._scale()
        w = int(round(self.BASE_W * sc))
        h = int(round(self._base_h() * sc))
        self.setFixedSize(w, h)

        x = self.cfg.get("x")
        y = self.cfg.get("y")
        primary = QGuiApplication.primaryScreen()
        pg = primary.geometry() if primary else None
        valid = False
        if x is not None and y is not None:
            # Multi-monitor aware: keep the saved position as long as its centre is on *any* screen.
            centre = QPoint(int(x) + w // 2, int(y) + h // 2)
            valid = QGuiApplication.screenAt(centre) is not None
        if not valid:
            right = pg.right() if pg else 2560
            top = pg.top() if pg else 0
            x = int(right - w - 28)
            y = int(top + 22)
            self.cfg["x"] = x
            self.cfg["y"] = y
        self.move(int(x), int(y))

    # ---------------------------------------------------------- win32 glue
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
        self._schedule_tick()
        if not self._pinned_init:
            QTimer.singleShot(15, self.ensure_desktop_pinned)
        else:
            send_to_bottom(int(self.winId()))

    def hideEvent(self, event):
        self._tick_timer.stop()
        super().hideEvent(event)

    def nativeEvent(self, eventType, message):
        if eventType == b"windows_generic_MSG" or eventType == "windows_generic_MSG":
            import ctypes
            msg = ctypes.wintypes.MSG.from_address(int(message))
            if msg.message == WM_SYSCOMMAND and (msg.wParam & 0xFFF0) == SC_MINIMIZE:
                return True, 0
            elif msg.message == WM_MOUSEACTIVATE:
                return True, MA_NOACTIVATE
        return super().nativeEvent(eventType, message)

    # ------------------------------------------------------- interaction
    def _animate_hover(self, target: float):
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover)
        self._hover_anim.setEndValue(target)
        self._hover_anim.start()

    def _on_hover_val(self, v):
        self._hover = float(v)
        self.update()

    def enterEvent(self, event):
        if not self.cfg.get("click_through", False):
            self._animate_hover(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event):
        if not self._dragging and not self._menu_open:
            self._animate_hover(0.0)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and not self.cfg.get("locked", False):
            self._dragging = True
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self.setCursor(Qt.ClosedHandCursor)
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
                # Horizontal centre magnet
                if abs((new_pt.x() + self.width() / 2) - sg.center().x()) <= 12:
                    new_pt.setX(int(sg.center().x() - self.width() / 2))
            self.move(new_pt)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._dragging:
            self._dragging = False
            self.unsetCursor()
            self.cfg["x"] = self.x()
            self.cfg["y"] = self.y()
            self.configChanged.emit()
            if not self.underMouse():
                self._animate_hover(0.0)
        super().mouseReleaseEvent(event)

    # ------------------------------------------------------------- menus
    def build_clock_menu(self, parent_menu: QMenu | None = None) -> QMenu:
        menu = parent_menu or QMenu(self)
        menu.setStyleSheet(MENU_QSS)

        style_menu = menu.addMenu("🎨 切换时钟字体风格")
        style_menu.setStyleSheet(MENU_QSS)
        cur_style = self.cfg.get("style", "nordic_modern")
        grp_s = QActionGroup(menu)
        for s_key, s_label in CLOCK_STYLES.items():
            a = style_menu.addAction(s_label)
            a.setCheckable(True)
            a.setChecked(s_key == cur_style)
            grp_s.addAction(a)
            a.triggered.connect(lambda checked=False, k=s_key: self._set_style(k))

        act_lock = menu.addAction("🔒 锁定时钟位置")
        act_lock.setCheckable(True)
        act_lock.setChecked(bool(self.cfg.get("locked", False)))
        act_lock.toggled.connect(self._set_locked)

        act_reset_pos = menu.addAction("重置回右上角")
        act_reset_pos.triggered.connect(self._reset_top_right)

        menu.addSeparator()
        act_settings = menu.addAction("⚙️ 更多时钟与外观设置...")
        act_settings.triggered.connect(self.openSettingsRequested.emit)

        act_hide = menu.addAction("隐藏桌面时钟")
        act_hide.triggered.connect(lambda: self._set_enabled(False))

        return menu

    def contextMenuEvent(self, event):
        m = self.build_clock_menu()
        self._menu_open = True
        m.exec(event.globalPos())
        self._menu_open = False
        if not self.underMouse():
            self._animate_hover(0.0)

    def _set_enabled(self, val: bool):
        self.cfg["enabled"] = val
        self.setVisible(val)
        self.configChanged.emit()

    def _set_style(self, style_key: str):
        if style_key == self.cfg.get("style") or style_key not in CLOCK_STYLES:
            return
        if self.isVisible():
            hv = self._hover
            self._hover = 0.0
            self._xfade = 1.0
            self._xfade_pix = None
            self._xfade_pix = self.grab()
            self._hover = hv
        self.cfg["style"] = style_key
        self._apply_size_and_pos()
        if self._xfade_pix is not None:
            self._xfade = 0.0
            self._xfade_anim.stop()
            self._xfade_anim.setStartValue(0.0)
            self._xfade_anim.setEndValue(1.0)
            self._xfade_anim.start()
        self.update()
        self.configChanged.emit()

    def _on_xfade_val(self, v):
        self._xfade = float(v)
        self.update()

    def _on_xfade_done(self):
        self._xfade = 1.0
        self._xfade_pix = None
        self.update()

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
        self.refresh()
        self.configChanged.emit()

    def _set_locked(self, val: bool):
        self.cfg["locked"] = val
        self.configChanged.emit()

    def _set_click_through(self, val: bool):
        self.cfg["click_through"] = val
        self.apply_click_through()
        if val:
            self._animate_hover(0.0)
        self.configChanged.emit()

    def _reset_top_right(self):
        self.cfg["x"] = None
        self.cfg["y"] = None
        self._apply_size_and_pos()
        self.configChanged.emit()

    # ---------------------------------------------------------- drawing kit
    @staticmethod
    def _text_path(text: str, font: QFont, cx: float, baseline: float, align: str = "center") -> tuple[QPainterPath, float, float]:
        """Return (path, left_x, width) of `text` laid out at `baseline` and centred on `cx`."""
        fm = QFontMetricsF(font)
        w = fm.horizontalAdvance(text)
        sp = font.letterSpacing() if font.letterSpacingType() == QFont.AbsoluteSpacing else 0.0
        vis_w = w - sp  # letter-spacing adds trailing space after the last glyph
        if align == "center":
            x = cx - vis_w / 2.0
        elif align == "right":
            x = cx - vis_w
        else:
            x = cx
        p = QPainterPath()
        p.addText(QPointF(x, baseline), font, text)
        return p, x, vis_w

    def _build_time(
        self,
        hh: str,
        mm: str,
        suffix: str,
        font: QFont,
        cx: float,
        baseline: float,
        sc: float,
        suffix_font: QFont | None = None,
        gap: float = 22.0,
        colon: str = "dots",
        mid_mode: str = "cap",
        slant: float = 0.0,
        dot_r: float = 2.5,
    ) -> tuple[QPainterPath, QPainterPath, float, float]:
        """Lay out HH · MM [suffix] centred on cx.

        Returns (digits_path, colon_path, left_x, right_x). The colon is built as separate
        geometry so it can be tinted with the aurora accent independently from the numerals.
        """
        fm = QFontMetricsF(font)
        gap_px = gap * sc
        w_hh = fm.horizontalAdvance(hh)
        w_mm = fm.horizontalAdvance(mm)

        sfont = suffix_font or make_apple_font(int(round(20 * sc)), QFont.Light, 0.5)
        fm_s = QFontMetricsF(sfont)
        s_gap = 8.0 * sc
        w_s = (fm_s.horizontalAdvance(suffix) + s_gap) if suffix else 0.0

        total = w_hh + gap_px + w_mm + w_s
        x0 = cx - total / 2.0

        digits = QPainterPath()
        digits.addText(QPointF(x0, baseline), font, hh)
        mm_x = x0 + w_hh + gap_px
        digits.addText(QPointF(mm_x, baseline), font, mm)
        if suffix:
            digits.addText(QPointF(mm_x + w_mm + s_gap, baseline - 2.0 * sc), sfont, suffix)

        colon_path = QPainterPath()
        dcx = x0 + w_hh + gap_px / 2.0
        if mid_mode == "x":
            ref = fm.xHeight()
            mid_y = baseline - ref * 0.50
            sep = ref * 0.30
        else:
            ref = fm.capHeight()
            mid_y = baseline - ref * 0.48
            sep = ref * 0.21
        r = dot_r * sc
        for dy in (-sep, sep):
            y = mid_y + dy
            x = dcx + slant * (mid_y - y)
            if colon == "diamond":
                rr = r * 1.45
                colon_path.addPolygon(QPolygonF([
                    QPointF(x, y - rr), QPointF(x + rr * 0.72, y), QPointF(x, y + rr), QPointF(x - rr * 0.72, y), QPointF(x, y - rr),
                ]))
                colon_path.closeSubpath()
            else:
                colon_path.addEllipse(QPointF(x, y), r, r)
        return digits, colon_path, x0, x0 + total

    @staticmethod
    def _halo(painter: QPainter, path: QPainterPath, sc: float, strength: float = 1.0):
        """Soft multi-layer dark halo + drop shadow: legible on bright wallpapers, invisible on dark ones."""
        painter.save()
        painter.setBrush(Qt.NoBrush)
        painter.translate(0.0, 1.6 * sc)
        for width, alpha in ((14.0, 6), (8.0, 12), (4.5, 22), (2.0, 36)):
            pen = QPen(QColor(0, 0, 0, int(alpha * strength)), width * sc, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
            painter.strokePath(path, pen)
        painter.fillPath(path, QColor(0, 0, 0, int(96 * strength)))
        painter.restore()

    @staticmethod
    def _glow(painter: QPainter, path: QPainterPath, color: QColor, sc: float, strength: float = 1.0):
        painter.save()
        for width, alpha in ((18.0, 7), (10.0, 13), (5.0, 22)):
            c = QColor(color)
            c.setAlpha(int(alpha * strength))
            painter.strokePath(path, QPen(c, width * sc, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.restore()

    def _draw_text(self, painter: QPainter, path: QPainterPath, fill, sc: float, halo: float = 1.0):
        if halo > 0:
            self._halo(painter, path, sc, halo)
        painter.fillPath(path, fill if isinstance(fill, QBrush) else QBrush(fill))

    @staticmethod
    def _silk(top: float, bottom: float, warm: bool = False) -> QBrush:
        g = QLinearGradient(0.0, top, 0.0, bottom)
        if warm:
            g.setColorAt(0.0, QColor(255, 251, 242, 252))
            g.setColorAt(1.0, QColor(240, 228, 206, 228))
        else:
            g.setColorAt(0.0, QColor(255, 255, 255, 252))
            g.setColorAt(1.0, QColor(228, 240, 255, 224))
        return QBrush(g)

    def _accent_colon(self, painter: QPainter, colon: QPainterPath, sc: float, c1: QColor, c2: QColor):
        if colon.isEmpty():
            return
        r = colon.boundingRect()
        g = QLinearGradient(r.topLeft(), r.bottomRight())
        g.setColorAt(0.0, _mix(c1, 0.35, 250))
        g.setColorAt(1.0, _mix(c2, 0.35, 250))
        self._glow(painter, colon, c1, sc * 0.55, 1.2)
        self._halo(painter, colon, sc, 0.8)
        painter.fillPath(colon, QBrush(g))

    def _hairline(self, painter: QPainter, cx: float, y: float, half: float, c1: QColor, c2: QColor, alpha: int = 150, ornament: bool = False, sc: float = 1.0):
        g = QLinearGradient(cx - half, 0, cx + half, 0)
        g.setColorAt(0.0, QColor(255, 255, 255, 0))
        a1 = QColor(c1); a1.setAlpha(alpha)
        a2 = QColor(c2); a2.setAlpha(alpha)
        g.setColorAt(0.35, a1)
        g.setColorAt(0.65, a2)
        g.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.setPen(QPen(QBrush(g), 1.0))
        if ornament:
            gap = 7.0 * sc
            painter.drawLine(QPointF(cx - half, y), QPointF(cx - gap, y))
            painter.drawLine(QPointF(cx + gap, y), QPointF(cx + half, y))
            rr = 2.6 * sc
            dia = QPainterPath()
            dia.addPolygon(QPolygonF([QPointF(cx, y - rr), QPointF(cx + rr, y), QPointF(cx, y + rr), QPointF(cx - rr, y), QPointF(cx, y - rr)]))
            painter.fillPath(dia, _mix(c1, 0.3, 220))
        else:
            painter.drawLine(QPointF(cx - half, y), QPointF(cx + half, y))

    def _paint_hover_glass(self, painter: QPainter, c1: QColor, c2: QColor):
        h = self._hover
        if h <= 0.01:
            return
        rect = QRectF(1.5, 1.5, self.width() - 3.0, self.height() - 3.0)
        path = QPainterPath()
        path.addRoundedRect(rect, 16.0, 16.0)
        painter.fillPath(path, QColor(10, 15, 28, int(70 * h)))
        sheen = QLinearGradient(0, 0, 0, rect.height() * 0.5)
        sheen.setColorAt(0.0, QColor(255, 255, 255, int(14 * h)))
        sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.fillPath(path, sheen)
        bg = QLinearGradient(rect.topLeft(), rect.bottomRight())
        a1 = QColor(c1); a1.setAlpha(int(110 * h))
        a2 = QColor(c2); a2.setAlpha(int(110 * h))
        bg.setColorAt(0.0, a1)
        bg.setColorAt(1.0, a2)
        painter.setPen(QPen(QBrush(bg), 1.0))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)

    # ------------------------------------------------------------- paint
    def _ensure_face_pixmap(self, style: str, now: datetime, hh: str, mm: str, suffix: str, sc: float, c1: QColor, cm: QColor, c2: QColor) -> QPixmap:
        w, h = self.width(), self.height()
        dpr = self.devicePixelRatioF() or 1.0
        key = (
            style,
            hh,
            mm,
            suffix,
            now.year,
            now.month,
            now.day,
            now.hour,
            round(sc, 3),
            w,
            h,
            round(dpr, 2),
            c1.rgba(),
            cm.rgba(),
            c2.rgba(),
        )
        if self._face_cache_key == key and self._face_cache_pix is not None:
            return self._face_cache_pix

        pm = QPixmap(max(1, int(round(w * dpr))), max(1, int(round(h * dpr))))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.transparent)

        sub = QPainter(pm)
        sub.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
        fn = self._painters.get(style, self._paint_nordic)
        fn(sub, now, hh, mm, suffix, sc, float(w), c1, cm, c2)
        sub.end()

        self._face_cache_key = key
        self._face_cache_pix = pm
        return pm

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)

        if not self.cfg.get("click_through", False):
            painter.fillRect(self.rect(), QColor(0, 0, 0, 1))

        c1, cm, c2 = self._theme_provider()
        self._paint_hover_glass(painter, c1, c2)

        now = datetime.now()
        sc = self._scale()
        use_24h = bool(self.cfg.get("use_24h", True))
        show_sec = bool(self.cfg.get("show_seconds", False))
        hh = now.strftime("%H") if use_24h else (now.strftime("%I").lstrip("0") or "12")
        mm = now.strftime("%M")
        suffix = now.strftime("%S") if show_sec else ("" if use_24h else now.strftime("%p"))
        style = self.cfg.get("style", "nordic_modern")

        face_pm = self._ensure_face_pixmap(style, now, hh, mm, suffix, sc, c1, cm, c2)

        if self._xfade_pix is not None and self._xfade < 1.0:
            painter.setOpacity(1.0 - self._xfade)
            painter.drawPixmap(0, 0, self._xfade_pix)
            painter.setOpacity(self._xfade)

        painter.drawPixmap(0, 0, face_pm)

    # ---- 1. Nordic Modern ------------------------------------------------
    def _paint_nordic(self, painter, now, hh, mm, sfx, sc, w, c1, cm, c2):
        cx = w / 2.0
        t_font = _mkfont(F_OUTFIT, 78 * sc, QFont.ExtraLight)
        digits, colon, _, _ = self._build_time(hh, mm, sfx, t_font, cx, 84.0 * sc, sc)
        fm = QFontMetricsF(t_font)
        self._draw_text(painter, digits, self._silk(84.0 * sc - fm.capHeight(), 84.0 * sc), sc)
        self._accent_colon(painter, colon, sc, c1, c2)

        self._hairline(painter, cx, 99.0 * sc, 46 * sc, c1, c2)

        d_font = make_apple_font(int(round(12 * sc)), QFont.Medium, 2.6 * sc)
        txt = f"{now.strftime('%A').upper()}  ·  {now.strftime('%b').upper()} {now.day:02d}"
        p, _, _ = self._text_path(txt, d_font, cx, 124.0 * sc)
        self._draw_text(painter, p, QColor(242, 248, 255, 214), sc, 0.8)

    # ---- 2. Aurora Gradient (clean geometric numerals in theme gradient) ----
    def _paint_gradient(self, painter, now, hh, mm, sfx, sc, w, c1, cm, c2):
        cx = w / 2.0
        base = 92.0 * sc
        t_font = _mkfont(F_OUTFIT, 84 * sc, QFont.Light)
        s_font = _mkfont(F_OUTFIT, 24 * sc, QFont.Light)
        digits, colon, x0, x1 = self._build_time(
            hh, mm, sfx, t_font, cx, base, sc, suffix_font=s_font, gap=22.0
        )
        fm = QFontMetricsF(t_font)
        top = base - fm.capHeight()

        self._glow(painter, digits, cm, sc, 0.8)
        self._halo(painter, digits, sc, 0.9)
        aur = QLinearGradient(QPointF(x0, top), QPointF(x1, base))
        aur.setColorAt(0.0, _mix(c1, 0.40, 250))
        aur.setColorAt(0.5, _mix(cm, 0.55, 250))
        aur.setColorAt(1.0, _mix(c2, 0.40, 250))
        painter.fillPath(digits, QBrush(aur))
        # Silk specular sheen over the upper half, kept subtle so the gradient stays vivid
        sheen = QLinearGradient(0.0, top, 0.0, base)
        sheen.setColorAt(0.0, QColor(255, 255, 255, 100))
        sheen.setColorAt(0.55, QColor(255, 255, 255, 0))
        painter.fillPath(digits, QBrush(sheen))
        self._accent_colon(painter, colon, sc, c1, c2)

        self._hairline(painter, cx, 108.0 * sc, 50 * sc, c1, c2)

        d_font = make_apple_font(int(round(12 * sc)), QFont.Medium, 2.6 * sc)
        txt = f"{now.strftime('%A').upper()}  ·  {now.strftime('%b').upper()} {now.day:02d}"
        p, _, _ = self._text_path(txt, d_font, cx, 134.0 * sc)
        self._draw_text(painter, p, QColor(242, 248, 255, 218), sc, 0.8)

    # ---- 3. Aurora Calligraphy (flagship artistic) -------------------------
    def _paint_calligraphy(self, painter, now, hh, mm, sfx, sc, w, c1, cm, c2):
        cx = w / 2.0
        base = 94.0 * sc
        t_font = _mkfont(F_PLAYFAIR, 86 * sc, italic=True)
        s_font = _mkfont(F_PLAYFAIR, 24 * sc, italic=True)
        digits, colon, x0, x1 = self._build_time(
            hh, mm, sfx, t_font, cx, base, sc, suffix_font=s_font, gap=20.0, slant=0.22, dot_r=3.0
        )
        fm = QFontMetricsF(t_font)
        top = base - fm.capHeight()

        self._glow(painter, digits, c1, sc, 0.9)
        self._halo(painter, digits, sc, 0.9)
        aur = QLinearGradient(QPointF(x0, top), QPointF(x1, base))
        aur.setColorAt(0.0, _mix(c1, 0.42, 252))
        aur.setColorAt(0.5, _mix(cm, 0.62, 252))
        aur.setColorAt(1.0, _mix(c2, 0.42, 252))
        painter.fillPath(digits, QBrush(aur))
        # Silk specular sheen over the upper half of the numerals
        sheen = QLinearGradient(0.0, top, 0.0, base)
        sheen.setColorAt(0.0, QColor(255, 255, 255, 110))
        sheen.setColorAt(0.55, QColor(255, 255, 255, 0))
        painter.fillPath(digits, QBrush(sheen))
        self._accent_colon(painter, colon, sc, c1, c2)

        # Ribbon of script beneath: "Wednesday, the 25th of November"
        script = f"{now.strftime('%A')}, the {ordinal(now.day)} of {now.strftime('%B')}"
        g_font = _fit_font(_mkfont(F_GREAT_VIBES, 33 * sc), script, w - 30 * sc)
        p, sx, sw = self._text_path(script, g_font, cx, 148.0 * sc)
        sg = QLinearGradient(sx, 0, sx + sw, 0)
        sg.setColorAt(0.0, QColor(255, 255, 255, 232))
        sg.setColorAt(0.5, _mix(cm, 0.7, 236))
        sg.setColorAt(1.0, QColor(255, 255, 255, 232))
        self._draw_text(painter, p, QBrush(sg), sc, 0.9)

    # ---- 3. Editorial Serif ------------------------------------------------
    def _paint_editorial(self, painter, now, hh, mm, sfx, sc, w, c1, cm, c2):
        cx = w / 2.0
        base = 80.0 * sc
        t_font = _mkfont(F_CORMORANT, 92 * sc, QFont.Light)
        s_font = _mkfont(F_CORMORANT, 26 * sc, QFont.Light)
        digits, colon, _, _ = self._build_time(
            hh, mm, sfx, t_font, cx, base, sc, suffix_font=s_font, gap=24.0, colon="diamond", mid_mode="x", dot_r=2.4
        )
        fm = QFontMetricsF(t_font)
        self._draw_text(painter, digits, self._silk(base - fm.ascent() * 0.75, base + fm.descent()), sc)
        self._accent_colon(painter, colon, sc, c1, c2)

        # Ornamented hairline sits below the old-style descenders (5 / 9 / 3 / 4 / 7)
        line_y = max(108.0 * sc, _digit_bottom(t_font, base) + 10.0 * sc)
        self._hairline(painter, cx, line_y, 58 * sc, c1, c2, 140, ornament=True, sc=sc)

        d_font = _mkfont(F_CORMORANT, 15 * sc, QFont.Light, spacing=2.8 * sc)
        txt = f"{now.strftime('%A').upper()}  ·  {now.strftime('%B').upper()} {now.day}"
        d_font = _fit_font(d_font, txt, w - 40 * sc)
        p, _, _ = self._text_path(txt, d_font, cx, line_y + 26.0 * sc)
        self._draw_text(painter, p, QColor(244, 248, 255, 226), sc, 0.9)

    # ---- 4. Roman Inscription ----------------------------------------------
    def _paint_roman(self, painter, now, hh, mm, sfx, sc, w, c1, cm, c2):
        cx = w / 2.0
        ivory = QColor(250, 242, 226, 222)

        # Eyebrow: — WEDNESDAY —
        e_font = _mkfont(F_CORMORANT, 14 * sc, QFont.Light, spacing=6.0 * sc)
        p, ex, ew = self._text_path(now.strftime("%A").upper(), e_font, cx, 26.0 * sc)
        self._draw_text(painter, p, ivory, sc, 0.8)
        line_y = 21.5 * sc
        for sign in (-1, 1):
            inner = (ex - 12 * sc) if sign < 0 else (ex + ew + 12 * sc)
            outer = inner + sign * 38 * sc
            g = QLinearGradient(inner, 0, outer, 0)
            a = QColor(c1); a.setAlpha(150)
            g.setColorAt(0.0, a)
            g.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.setPen(QPen(QBrush(g), 1.0))
            painter.drawLine(QPointF(inner, line_y), QPointF(outer, line_y))
            painter.setPen(Qt.NoPen)
            painter.setBrush(_mix(c1, 0.3, 200))
            painter.drawEllipse(QPointF(inner + sign * 3.0 * sc, line_y), 1.4 * sc, 1.4 * sc)

        # Italic old-style numerals
        base = 104.0 * sc
        t_font = _mkfont(F_CORMORANT, 96 * sc, QFont.Light, italic=True)
        s_font = _mkfont(F_CORMORANT, 26 * sc, QFont.Light, italic=True)
        digits, colon, _, _ = self._build_time(
            hh, mm, sfx, t_font, cx, base, sc, suffix_font=s_font, gap=20.0, mid_mode="x", slant=0.2, dot_r=2.6
        )
        fm = QFontMetricsF(t_font)
        self._draw_text(painter, digits, self._silk(base - fm.ascent() * 0.75, base + fm.descent(), warm=True), sc)
        self._accent_colon(painter, colon, sc, c1, c2)

        # Roman date: XXV · XI · MMXXVI
        r_font = _mkfont(F_CORMORANT, 15 * sc, QFont.Light, spacing=3.6 * sc)
        txt = f"{roman(now.day)}  ·  {roman(now.month)}  ·  {roman(now.year)}"
        r_base = max(150.0 * sc, _digit_bottom(t_font, base) + 6.0 * sc + QFontMetricsF(r_font).capHeight())
        p, _, _ = self._text_path(txt, r_font, cx, r_base)
        self._draw_text(painter, p, ivory, sc, 0.8)

    # ---- 5. Eastern Ink (东方书韵) ------------------------------------------
    def _paint_eastern(self, painter, now, hh, mm, sfx, sc, w, c1, cm, c2):
        cx = w / 2.0
        today = now.date()
        term, is_term_day = current_solar_term(today)
        head = f"{ganzhi_year(today)}年  ·  {'今日' if is_term_day else ''}{term}"
        ink_white = QColor(250, 246, 238, 236)

        h_font = _mkfont(F_XINGKAI, 30 * sc)
        p, _, _ = self._text_path(head, h_font, cx, 42.0 * sc)
        self._draw_text(painter, p, ink_white, sc, 0.8)

        # Numerals + vermilion seal (时辰) composed as one optically-centred group
        base = 116.0 * sc
        t_font = _mkfont(F_CN_SERIF, 74 * sc, QFont.Light)
        s_font = _mkfont(F_CN_SERIF, 20 * sc, QFont.Light)
        seal_w, seal_h, seal_gap = 24.0 * sc, 44.0 * sc, 14.0 * sc
        shift = (seal_w + seal_gap) / 2.0
        digits, colon, _, x1 = self._build_time(
            hh, mm, sfx, t_font, cx - shift, base, sc, suffix_font=s_font, gap=22.0, dot_r=2.6
        )
        fm = QFontMetricsF(t_font)
        self._draw_text(painter, digits, self._silk(base - fm.capHeight(), base, warm=True), sc)
        self._accent_colon(painter, colon, sc, c1, c2)

        seal_rect = QRectF(x1 + seal_gap, base - fm.capHeight() + 2.0 * sc, seal_w, seal_h)
        seal = QPainterPath()
        seal.addRoundedRect(seal_rect, 3.5 * sc, 3.5 * sc)
        self._halo(painter, seal, sc, 0.5)
        sg = QLinearGradient(seal_rect.topLeft(), seal_rect.bottomRight())
        sg.setColorAt(0.0, QColor(214, 72, 56, 228))
        sg.setColorAt(1.0, QColor(170, 40, 36, 228))
        chars = QPainterPath()
        c_font = _mkfont(F_XINGKAI, 17 * sc)
        cfm = QFontMetricsF(c_font)
        sc_txt = shichen(now.hour)
        for i, ch in enumerate(sc_txt):
            cw = cfm.horizontalAdvance(ch)
            cy = seal_rect.top() + seal_h * (0.25 + 0.5 * i) + cfm.capHeight() * 0.5 + 2.0 * sc
            chars.addText(QPointF(seal_rect.center().x() - cw / 2.0, cy), c_font, ch)
        painter.fillPath(seal.subtracted(chars), QBrush(sg))  # 阳刻反白: characters knocked out of the seal

        # Gregorian date in Chinese numerals
        d_font = _mkfont(F_CN_SERIF, 14 * sc, QFont.Light, spacing=2.6 * sc)
        txt = f"{cn_number(now.month)}月{cn_number(now.day)}日  ·  {WEEKDAY_CN[now.weekday()]}"
        p, _, _ = self._text_path(txt, d_font, cx, 154.0 * sc)
        self._draw_text(painter, p, QColor(240, 236, 228, 210), sc, 0.8)

    # ---- 6. macOS Sonoma -----------------------------------------------------
    def _paint_sonoma(self, painter, now, hh, mm, sfx, sc, w, c1, cm, c2):
        cx = w / 2.0
        term, is_term_day = current_solar_term(now.date())
        date_cn = f"{now.month}月{now.day}日 {WEEKDAY_CN[now.weekday()]}"
        if is_term_day:
            date_cn += f"  ·  {term}"
        d_font = make_apple_font(int(round(15 * sc)), QFont.Medium, 1.0 * sc)
        p, _, _ = self._text_path(date_cn, d_font, cx, 30.0 * sc)
        self._draw_text(painter, p, QColor(245, 250, 255, 226), sc, 0.9)

        base = 110.0 * sc
        t_font = _mkfont(F_OUTFIT, 80 * sc, QFont.Light)
        digits, colon, _, _ = self._build_time(hh, mm, sfx, t_font, cx, base, sc)
        fm = QFontMetricsF(t_font)
        self._draw_text(painter, digits, self._silk(base - fm.capHeight(), base), sc)
        self._accent_colon(painter, colon, sc, c1, c2)

    # ---- 7. Script Layered -----------------------------------------------------
    def _paint_script(self, painter, now, hh, mm, sfx, sc, w, c1, cm, c2):
        cx = w / 2.0
        s_font = _mkfont(F_RUTHLIGOS, 46 * sc)
        word = now.strftime("%A")
        s_font = _fit_font(s_font, word, w - 30 * sc)
        p, sx, sw = self._text_path(word, s_font, cx, 54.0 * sc)
        g = QLinearGradient(sx, 0, sx + sw, 0)
        g.setColorAt(0.0, QColor(255, 255, 255, 215))
        g.setColorAt(0.45, _mix(c1, 0.55, 225))
        g.setColorAt(0.8, _mix(c2, 0.55, 225))
        g.setColorAt(1.0, QColor(255, 255, 255, 215))
        self._glow(painter, p, c1, sc * 0.7, 0.6)
        self._draw_text(painter, p, QBrush(g), sc, 0.8)

        base = 128.0 * sc
        t_font = _mkfont(F_OUTFIT, 66 * sc, QFont.ExtraLight)
        digits, colon, _, _ = self._build_time(hh, mm, sfx, t_font, cx, base, sc)
        fm = QFontMetricsF(t_font)
        self._draw_text(painter, digits, self._silk(base - fm.capHeight(), base), sc)
        self._accent_colon(painter, colon, sc, c1, c2)

        d_font = make_apple_font(int(round(12 * sc)), QFont.Normal, 2.4 * sc)
        p, _, _ = self._text_path(f"{now.day:02d}  {now.strftime('%B').upper()}", d_font, cx, 158.0 * sc)
        self._draw_text(painter, p, QColor(235, 245, 255, 200), sc, 0.8)
