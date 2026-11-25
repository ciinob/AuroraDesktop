import ast
import math
import operator
import os
import socket
import subprocess
import urllib.parse
import webbrowser
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QPointF,
    QRectF,
    Qt,
    QTimer,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QConicalGradient,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QKeyEvent,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from animator import HighRefreshAnimation
from icon_extractor import ShortcutIconLoader, format_display_name
from pinyin_helper import fuzzy_match_score
from win32_utils import apply_acrylic_and_rounded_corners

SAFE_MATH_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

SAFE_MATH_FUNCS = {
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "sqrt": math.sqrt,
    "log": math.log,
    "log10": math.log10,
    "exp": math.exp,
    "abs": abs,
    "round": round,
    "pi": math.pi,
    "e": math.e,
}


def try_eval_math(expr: str) -> str | None:
    """Safely evaluate math expressions like '128 * 4.5', '2^16', 'sqrt(2)', '= 350 / 7'."""
    s = expr.strip()
    if s.startswith("="):
        s = s[1:].strip()
    if not s or len(s) > 80:
        return None
    # Must look like a math expression (contain operator or math func, not just plain word)
    s_norm = s.replace("^", "**").replace("×", "*").replace("÷", "/")
    if not any(ch in s_norm for ch in "+-*/%()") and s_norm not in ("pi", "e"):
        return None
    if s_norm.isdigit():
        return None

    def _eval(node):
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in SAFE_MATH_OPS:
            return SAFE_MATH_OPS[type(node.op)](_eval(node.left), _eval(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in SAFE_MATH_OPS:
            return SAFE_MATH_OPS[type(node.op)](_eval(node.operand))
        if isinstance(node, ast.Name) and node.id in SAFE_MATH_FUNCS:
            val = SAFE_MATH_FUNCS[node.id]
            if isinstance(val, (int, float)):
                return val
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in SAFE_MATH_FUNCS:
            fn = SAFE_MATH_FUNCS[node.func.id]
            if callable(fn):
                args = [_eval(a) for a in node.args]
                return fn(*args)
        raise ValueError("Unsupported")

    try:
        tree = ast.parse(s_norm, mode="eval")
        res = _eval(tree)
        if isinstance(res, float):
            if res.is_integer():
                return str(int(res))
            return f"{res:.8g}"
        return str(res)
    except Exception:
        return None


@dataclass
class SearchEntry:
    title: str
    subtitle: str
    badge: str
    path: Path | None = None
    pixmap: QPixmap | None = None
    action_type: str = "file"  # "file", "copy", "url", "cmd"
    payload: str = ""
    score: int = 0


class SpotlightResultList(QWidget):
    """Custom-painted Apple Spotlight / Raycast glass result rows with smooth keyboard & mouse hover."""
    entryActivated = Signal(object, bool, bool)  # (SearchEntry, as_admin, open_loc)

    ROW_H = 48

    def __init__(self, font_maker, theme_provider, parent=None):
        super().__init__(parent)
        self._make_font = font_maker
        self._theme_provider = theme_provider
        self.entries: list[SearchEntry] = []
        self.selected_idx = 0
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)

    def set_entries(self, entries: list[SearchEntry]):
        self.entries = entries[:8]
        self.selected_idx = 0 if self.entries else -1
        self.setFixedHeight(len(self.entries) * self.ROW_H + (8 if self.entries else 0))
        self.update()

    def move_selection(self, delta: int):
        if not self.entries:
            return
        self.selected_idx = (self.selected_idx + delta) % len(self.entries)
        self.update()

    def current_entry(self) -> SearchEntry | None:
        if 0 <= self.selected_idx < len(self.entries):
            return self.entries[self.selected_idx]
        return None

    def mouseMoveEvent(self, event):
        idx = int((event.position().y() - 4) // self.ROW_H)
        if 0 <= idx < len(self.entries) and idx != self.selected_idx:
            self.selected_idx = idx
            self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            idx = int((event.position().y() - 4) // self.ROW_H)
            if 0 <= idx < len(self.entries):
                mods = event.modifiers()
                as_admin = bool(mods & Qt.ControlModifier)
                open_loc = bool(mods & Qt.AltModifier)
                self.entryActivated.emit(self.entries[idx], as_admin, open_loc)
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        if not self.entries:
            return
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing)

        c1, _, c2 = self._theme_provider()
        w = self.width()

        # Subtle separator under search input
        painter.setPen(QPen(QColor(255, 255, 255, 22), 1.0))
        painter.drawLine(QPointF(14.0, 1.0), QPointF(w - 14.0, 1.0))

        title_font = self._make_font(13, QFont.Medium, 0.0)
        sub_font = self._make_font(11, QFont.Normal, 0.0)
        badge_font = self._make_font(10, QFont.DemiBold, 0.3)
        fm_title = QFontMetrics(title_font)
        fm_sub = QFontMetrics(sub_font)
        fm_badge = QFontMetrics(badge_font)

        for i, entry in enumerate(self.entries):
            ry = 4.0 + i * self.ROW_H
            row_rect = QRectF(8.0, ry + 2.0, w - 16.0, self.ROW_H - 4.0)
            is_sel = (i == self.selected_idx)

            if is_sel:
                grad = QLinearGradient(row_rect.topLeft(), row_rect.topRight())
                c_left = QColor(c1)
                c_left.setAlpha(52)
                c_right = QColor(c2)
                c_right.setAlpha(42)
                grad.setColorAt(0.0, c_left)
                grad.setColorAt(1.0, c_right)
                painter.setBrush(grad)
                border_col = QColor(c1)
                border_col.setAlpha(120)
                painter.setPen(QPen(border_col, 1.0))
                painter.drawRoundedRect(row_rect, 10.0, 10.0)

            # Icon / glyph on left
            icon_rect = QRectF(20.0, ry + 8.0, 32.0, 32.0)
            if entry.pixmap and not entry.pixmap.isNull():
                painter.drawPixmap(icon_rect, entry.pixmap, QRectF(entry.pixmap.rect()))
            else:
                # Minimalist symbol badge for math / web / command
                sym_bg = QColor(c1)
                sym_bg.setAlpha(48 if is_sel else 32)
                painter.setBrush(sym_bg)
                painter.setPen(Qt.NoPen)
                painter.drawRoundedRect(icon_rect, 8.0, 8.0)
                painter.setFont(self._make_font(14, QFont.DemiBold))
                painter.setPen(QColor(255, 255, 255, 235))
                glyph = "＝" if entry.action_type == "copy" else ("🌐" if entry.action_type == "url" else "⚡")
                painter.drawText(icon_rect, Qt.AlignCenter, glyph)

            # Right-side capsule badge + Enter hint
            badge_text = entry.badge
            bw = fm_badge.horizontalAdvance(badge_text) + 14
            badge_rect = QRectF(w - bw - 22.0, ry + 13.0, float(bw), 22.0)
            b_bg = QColor(255, 255, 255, 26 if is_sel else 14)
            painter.setBrush(b_bg)
            painter.setPen(QPen(QColor(255, 255, 255, 38 if is_sel else 18), 1.0))
            painter.drawRoundedRect(badge_rect, 6.0, 6.0)
            painter.setFont(badge_font)
            painter.setPen(QColor(226, 242, 255, 230 if is_sel else 165))
            painter.drawText(badge_rect, Qt.AlignCenter, badge_text)

            # Title & subtitle
            avail_tw = int(badge_rect.left() - 66.0)
            painter.setFont(title_font)
            painter.setPen(QColor(255, 255, 255, 252 if is_sel else 228))
            t_elided = fm_title.elidedText(entry.title, Qt.ElideRight, avail_tw)
            painter.drawText(QRectF(62.0, ry + 6.0, float(avail_tw), 20.0), Qt.AlignLeft | Qt.AlignVCenter, t_elided)

            painter.setFont(sub_font)
            painter.setPen(QColor(186, 206, 230, 195 if is_sel else 135))
            s_elided = fm_sub.elidedText(entry.subtitle, Qt.ElideRight, avail_tw)
            painter.drawText(QRectF(62.0, ry + 25.0, float(avail_tw), 17.0), Qt.AlignLeft | Qt.AlignVCenter, s_elided)


class AuroraSpotlightOverlay(QWidget):
    """Apple Spotlight × Northern Lights global search launcher (Double-Tap Ctrl / Alt+S / Top Bar click)."""

    WIDTH = 590
    INPUT_BAR_H = 58
    RADIUS = 16.0

    def __init__(
        self,
        icon_loader: ShortcutIconLoader,
        partitions_provider,
        launch_callback,
        open_loc_callback,
        font_maker,
        theme_provider,
        settings_callback=None,
        parent=None,
    ):
        super().__init__(parent)
        self.icon_loader = icon_loader
        self._partitions_provider = partitions_provider
        self._launch_cb = launch_callback
        self._open_loc_cb = open_loc_callback
        self._make_font = font_maker
        self._theme_provider = theme_provider
        self._settings_cb = settings_callback

        self._acrylic_ready = False
        self._start_menu_cache: list[tuple[str, Path]] = []
        self._phase = 0.0

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedWidth(self.WIDTH)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # Top search bar row
        top_bar = QWidget(self)
        top_bar.setFixedHeight(self.INPUT_BAR_H)
        top_row = QHBoxLayout(top_bar)
        top_row.setContentsMargins(50, 10, 18, 10)

        self.input = QLineEdit(top_bar)
        self.input.setPlaceholderText("搜索应用、PDF、图片、拼音首字母 (如 wx / wyy)，或直接输入算式...")
        self.input.setFont(self._make_font(15, QFont.Medium))
        self.input.setStyleSheet("""
            QLineEdit {
                background: transparent;
                border: none;
                color: #ffffff;
                selection-background-color: rgba(45, 212, 191, 90);
            }
        """)
        self.input.textChanged.connect(self._on_query_changed)
        self.input.installEventFilter(self)
        top_row.addWidget(self.input)

        self.result_list = SpotlightResultList(self._make_font, self._theme_provider, self)
        self.result_list.entryActivated.connect(self._execute_entry)

        root_layout.addWidget(top_bar)
        root_layout.addWidget(self.result_list)

        # Flowing aurora border shimmer timer while Spotlight is visible (matched to high refresh)
        self._shimmer_timer = QTimer(self)
        self._shimmer_timer.setTimerType(Qt.PreciseTimer)
        self._shimmer_timer.setInterval(8)
        self._shimmer_timer.timeout.connect(self._tick_shimmer)

        # 240Hz Fade entrance animation
        self._fade_anim = HighRefreshAnimation(self)
        self._fade_anim.setDuration(140)
        self._fade_anim.setEasingCurve(QEasingCurve.OutQuart)
        self._fade_anim.valueChanged.connect(lambda v: self.setWindowOpacity(float(v)))

        # Lazily index Windows Start Menu shortcuts in background after 1.5s
        QTimer.singleShot(1500, self._index_start_menu)

    def _tick_shimmer(self):
        self._phase = (self._phase + 0.025) % (math.pi * 2)
        self.update()

    def _index_start_menu(self):
        dirs = [
            Path(os.environ.get("ProgramData", r"C:\ProgramData")) / r"Microsoft\Windows\Start Menu\Programs",
            Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs",
        ]
        seen = set()
        items = []
        for d in dirs:
            if not d.exists():
                continue
            for p in d.rglob("*.lnk"):
                low = p.stem.lower()
                if low in seen or any(skip in low for skip in ("uninstall", "卸载", "readme", "help", "website")):
                    continue
                seen.add(low)
                short, _ = format_display_name(p)
                items.append((short, p))
        self._start_menu_cache = items

    def toggle_spotlight(self):
        if self.isVisible():
            self.dismiss()
        else:
            self.summon()

    def summon(self):
        self.input.clear()
        self._on_query_changed("")
        self._recenter_and_resize()

        self.setWindowOpacity(0.0)
        self.show()
        if not self._acrylic_ready:
            apply_acrylic_and_rounded_corners(int(self.winId()))
            self._acrylic_ready = True

        self.raise_()
        self.activateWindow()
        self.input.setFocus(Qt.ActiveWindowFocusReason)
        self._shimmer_timer.start()

        self._fade_anim.stop()
        self._fade_anim.setStartValue(0.0)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.start()

    def dismiss(self):
        self._shimmer_timer.stop()
        self.hide()

    def _recenter_and_resize(self):
        total_h = self.INPUT_BAR_H + self.result_list.height()
        self.setFixedHeight(total_h)
        screen = QGuiApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else QRectF(0, 0, 2560, 1392)
        x = int(avail.x() + (avail.width() - self.WIDTH) / 2)
        y = int(avail.y() + avail.height() * 0.22)
        self.move(x, y)

    def eventFilter(self, obj, event):
        if obj == self.input and event.type() == QEvent.KeyPress:
            ke: QKeyEvent = event
            key = ke.key()
            if key == Qt.Key_Escape:
                self.dismiss()
                return True
            if key == Qt.Key_Down:
                self.result_list.move_selection(1)
                return True
            if key == Qt.Key_Up:
                self.result_list.move_selection(-1)
                return True
            if key in (Qt.Key_Return, Qt.Key_Enter):
                entry = self.result_list.current_entry()
                if entry:
                    mods = ke.modifiers()
                    self._execute_entry(
                        entry,
                        bool(mods & Qt.ControlModifier),
                        bool(mods & Qt.AltModifier),
                    )
                return True
        return super().eventFilter(obj, event)

    def changeEvent(self, event):
        if event.type() == QEvent.ActivationChange and not self.isActiveWindow():
            self.dismiss()
        super().changeEvent(event)

    def _on_query_changed(self, text: str):
        q = text.strip()
        results: list[SearchEntry] = []

        # 1. Instant Math Evaluator
        math_ans = try_eval_math(q)
        if math_ans is not None:
            results.append(
                SearchEntry(
                    title=f"= {math_ans}",
                    subtitle=f"算式计算结果 · 按 Enter 复制 {math_ans} 到剪贴板",
                    badge="计算器",
                    action_type="copy",
                    payload=math_ans,
                    score=10000,
                )
            )

        # 2. Search across all AuroraDesktop capsules first
        seen_names = set()
        all_parts = self._partitions_provider()
        for group_title, folder_path in all_parts:
            if not folder_path.exists():
                continue
            for item in folder_path.iterdir():
                if item.name.lower() in ("desktop.ini", "thumbs.db") or item.name.startswith("."):
                    continue
                short, full = format_display_name(item)
                if not q:
                    # When input is empty, show quick recent/featured AI + core apps (up to 6)
                    if len(results) < 6:
                        pm = self.icon_loader.get_icon_pixmap(item, 64)
                        results.append(
                            SearchEntry(
                                title=short,
                                subtitle=f"{full}  ·  Enter 打开 / Alt+Enter 所在位置",
                                badge=group_title,
                                path=item,
                                pixmap=pm,
                                score=500 - len(results),
                            )
                        )
                    continue

                sc = fuzzy_match_score(q, short, f"{full} {group_title}")
                if sc == 0 and short != full:
                    sc = fuzzy_match_score(q, full, group_title)
                if sc > 0:
                    seen_names.add(short.lower())
                    pm = self.icon_loader.get_icon_pixmap(item, 64)
                    results.append(
                        SearchEntry(
                            title=short,
                            subtitle=f"{full}  ·  Ctrl+Enter 管理员 / Alt+Enter 位置",
                            badge=group_title,
                            path=item,
                            pixmap=pm,
                            score=sc + 100,  # Prefer user's capsule items over generic Start Menu
                        )
                    )

        # 3. Search Start Menu apps if query is non-empty
        if q:
            for short, lnk_path in self._start_menu_cache:
                if short.lower() in seen_names:
                    continue
                sc = fuzzy_match_score(q, short, "开始菜单")
                if sc > 0:
                    seen_names.add(short.lower())
                    pm = self.icon_loader.get_icon_pixmap(lnk_path, 64) if sc > 600 or len(results) < 10 else None
                    results.append(
                        SearchEntry(
                            title=short,
                            subtitle=str(lnk_path.parent.name),
                            badge="开始菜单",
                            path=lnk_path,
                            pixmap=pm,
                            score=sc,
                        )
                    )

            # 4. Built-in quick system commands & Settings Center
            ql = q.lower()
            set_sc = fuzzy_match_score(q, "极光设置中心 Settings", "shezhi sz 分组 图标 热键 开机自启 外观 时钟 任务栏 偏好")
            if set_sc > 0 and self._settings_cb is not None:
                results.append(
                    SearchEntry(
                        title="⚙️ 打开极光设置中心 (Aurora Settings)",
                        subtitle="集中管理胶囊分组、自定义图标、全局热键、开机自启与外观",
                        badge="设置中心",
                        action_type="cmd",
                        payload="open_settings",
                        score=set_sc + 260,
                    )
                )
            if ql in ("ip", "ipv4", "网络"):
                try:
                    ip = socket.gethostbyname(socket.gethostname())
                except Exception:
                    ip = "127.0.0.1"
                results.append(
                    SearchEntry(
                        title=f"本机 IPv4: {ip}",
                        subtitle="按 Enter 一键复制 IP 地址",
                        badge="系统指令",
                        action_type="copy",
                        payload=ip,
                        score=950,
                    )
                )
            if any(ql.startswith(k) for k in ("lock", "锁屏", "suoping")):
                results.append(
                    SearchEntry(
                        title="立即锁定屏幕 (Lock Workstation)",
                        subtitle="调用 Windows 原生锁屏",
                        badge="系统指令",
                        action_type="cmd",
                        payload="lock",
                        score=900,
                    )
                )

            results.sort(key=lambda e: e.score, reverse=True)
            # Ensure top 8 visible Start Menu results have icons loaded
            for entry in results[:8]:
                if entry.action_type == "file" and entry.path and entry.pixmap is None:
                    entry.pixmap = self.icon_loader.get_icon_pixmap(entry.path, 64)

            # 5. Always offer instant web search fallback at bottom if few matches or prefixed with '?'
            web_q = q[1:].strip() if q.startswith("?") else q
            if web_q and len(results) < 8:
                results.append(
                    SearchEntry(
                        title=f"在浏览器中搜索 “{web_q}”",
                        subtitle="使用默认浏览器打开网页搜索",
                        badge="网页直达",
                        action_type="url",
                        payload=f"https://www.bing.com/search?q={urllib.parse.quote(web_q)}",
                        score=10,
                    )
                )

        self.result_list.set_entries(results)
        self._recenter_and_resize()
        self.update()

    def _execute_entry(self, entry: SearchEntry, as_admin: bool, open_loc: bool):
        self.dismiss()
        if entry.action_type == "file" and entry.path:
            if open_loc:
                self._open_loc_cb(entry.path)
            else:
                self._launch_cb(entry.path, as_admin)
        elif entry.action_type == "copy":
            QApplication.clipboard().setText(entry.payload)
        elif entry.action_type == "url":
            webbrowser.open(entry.payload)
        elif entry.action_type == "cmd":
            if entry.payload == "lock":
                subprocess.Popen(["rundll32.exe", "user32.dll,LockWorkStation"])
            elif entry.payload == "open_settings" and self._settings_cb is not None:
                self._settings_cb()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)

        rect = QRectF(0.75, 0.75, self.width() - 1.5, self.height() - 1.5)
        path = QPainterPath()
        path.addRoundedRect(rect, self.RADIUS, self.RADIUS)

        # Deep high-contrast Aurora Spotlight glass background
        painter.fillPath(path, QColor(10, 15, 28, 195))

        # Subtle top inner sheen
        sheen = QLinearGradient(0, 0, 0, 56)
        sheen.setColorAt(0.0, QColor(255, 255, 255, 18))
        sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.fillPath(path, sheen)

        # Animated flowing Northern Lights conical/linear border
        c1, c_mid, c2 = self._theme_provider()
        cx, cy = rect.center().x(), rect.center().y()
        angle_deg = math.degrees(self._phase)
        conical = QConicalGradient(QPointF(cx, cy), angle_deg)
        col1 = QColor(c1); col1.setAlpha(220)
        col_m = QColor(c_mid); col_m.setAlpha(155)
        col2 = QColor(c2); col2.setAlpha(220)
        col_dim = QColor(c1); col_dim.setAlpha(75)
        conical.setColorAt(0.0, col1)
        conical.setColorAt(0.28, col_m)
        conical.setColorAt(0.55, col2)
        conical.setColorAt(0.80, col_dim)
        conical.setColorAt(1.0, col1)

        painter.setPen(QPen(conical, 1.4))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)

        # Crisp vector magnifying glass icon on left of search input
        ix, iy = 25.0, 27.0
        lens_pen = QPen(QColor(c1), 2.0)
        lens_pen.setCapStyle(Qt.RoundCap)
        painter.setPen(lens_pen)
        painter.drawEllipse(QPointF(ix, iy), 6.8, 6.8)
        painter.drawLine(QPointF(ix + 5.0, iy + 5.0), QPointF(ix + 10.2, iy + 10.2))

        # Subtle 'ESC' shortcut badge on right of input bar
        esc_rect = QRectF(self.width() - 52.0, 18.0, 34.0, 22.0)
        painter.setBrush(QColor(255, 255, 255, 16))
        painter.setPen(QPen(QColor(255, 255, 255, 34), 1.0))
        painter.drawRoundedRect(esc_rect, 6.0, 6.0)
        painter.setFont(self._make_font(10, QFont.DemiBold, 0.4))
        painter.setPen(QColor(200, 215, 235, 170))
        painter.drawText(esc_rect, Qt.AlignCenter, "ESC")
