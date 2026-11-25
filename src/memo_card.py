from pathlib import Path
from PySide6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QMenu, QPlainTextEdit

from animator import HighRefreshAnimation
from paths import DATA_ROOT
from widgets import AuroraBaseWindow, MENU_QSS, make_apple_font

MEMO_FILE = DATA_ROOT / "memo.txt"
DEFAULT_MEMO_TEXT = """· 今日待办 / 灵感速记
[ ] 阅读桌面文献与整理笔记
[ ] 双击 Ctrl 随时唤出极光全局搜索
"""


class AuroraMemoCard(AuroraBaseWindow):
    """Collapsible Northern Lights Quick Memo & Todo glass card with real-time autosave."""
    heightAnimated = Signal()
    pinToggled = Signal(bool)
    closeMemoRequested = Signal()

    CARD_WIDTH = 368
    HEADER_HEIGHT = 38
    EXPANDED_HEIGHT = 196

    def __init__(self, pinned: bool = True, allow_drag_provider=None, theme_provider=None, opacity_provider=None):
        super().__init__(
            allow_drag_provider=allow_drag_provider,
            theme_provider=theme_provider,
            opacity_provider=opacity_provider,
        )
        self.group_key = "__AURORA_MEMO__"
        self.title = "QUICK MEMO · 速记"
        self.pinned = pinned
        self._expanded = True
        self._pin_rect = QRectF(self.CARD_WIDTH - 34, 9, 20, 20)
        self._hover_pin = False

        self.setFixedWidth(self.CARD_WIDTH)
        self.setMinimumHeight(self.HEADER_HEIGHT)
        self.setMaximumHeight(2000)
        self.resize(self.CARD_WIDTH, self.EXPANDED_HEIGHT)
        self._target_anim_h = self.EXPANDED_HEIGHT

        self.editor = QPlainTextEdit(self)
        self.editor.setGeometry(12, self.HEADER_HEIGHT + 6, self.CARD_WIDTH - 24, self.EXPANDED_HEIGHT - self.HEADER_HEIGHT - 16)
        self.editor.setFont(make_apple_font(12, QFont.Normal))
        self.editor.setPlaceholderText("在此随手记录灵感、公式或待办事项（自动保存）...")
        self.editor.setStyleSheet("""
            QPlainTextEdit {
                background: rgba(255, 255, 255, 7);
                color: rgba(244, 248, 255, 238);
                border: 1px solid rgba(255, 255, 255, 16);
                border-radius: 9px;
                padding: 7px 9px;
                selection-background-color: rgba(45, 212, 191, 80);
            }
            QScrollBar:vertical {
                width: 5px;
                background: transparent;
            }
            QScrollBar::handle:vertical {
                background: rgba(255, 255, 255, 45);
                border-radius: 2px;
            }
        """)

        if MEMO_FILE.exists():
            try:
                self.editor.setPlainText(MEMO_FILE.read_text(encoding="utf-8"))
            except Exception:
                self.editor.setPlainText(DEFAULT_MEMO_TEXT)
        else:
            self.editor.setPlainText(DEFAULT_MEMO_TEXT)

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(400)
        self._save_timer.timeout.connect(self._save_memo)
        self.editor.textChanged.connect(lambda: self._save_timer.start())

        self._height_anim = HighRefreshAnimation(self)
        self._height_anim.setDuration(190)
        self._height_anim.setEasingCurve(QEasingCurve.OutQuart)
        self._height_anim.valueChanged.connect(self._on_height_val)

        self._collapse_timer = QTimer(self)
        self._collapse_timer.setSingleShot(True)
        self._collapse_timer.setInterval(600)
        self._collapse_timer.timeout.connect(self._on_collapse_timeout)

    def _save_memo(self):
        try:
            MEMO_FILE.write_text(self.editor.toPlainText(), encoding="utf-8")
        except Exception:
            pass

    def desired_stack_height(self) -> int:
        return self._target_anim_h

    def _on_height_val(self, val):
        h = max(self.HEADER_HEIGHT, int(round(val)))
        self._target_anim_h = h
        self.editor.setVisible(h > self.HEADER_HEIGHT + 24)
        self.heightAnimated.emit()

    def expand_card(self):
        self._collapse_timer.stop()
        if self._expanded and self.height() == self.EXPANDED_HEIGHT:
            return
        self._expanded = True
        self.editor.setVisible(True)
        self._height_anim.stop()
        self._height_anim.setStartValue(self.height())
        self._height_anim.setEndValue(self.EXPANDED_HEIGHT)
        self._height_anim.start()

    def collapse_card(self, force: bool = False):
        if (self.pinned or self._menu_open or self.editor.hasFocus()) and not force:
            return
        if not self._expanded and self.height() == self.HEADER_HEIGHT:
            return
        self._expanded = False
        self._height_anim.stop()
        self._height_anim.setStartValue(self.height())
        self._height_anim.setEndValue(self.HEADER_HEIGHT)
        self._height_anim.start()

    def _on_collapse_timeout(self):
        if not self.underMouse() and not self.pinned and not self.editor.hasFocus():
            self.collapse_card()

    def enterEvent(self, event):
        self._collapse_timer.stop()
        self.expand_card()
        super().enterEvent(event)

    def leaveEvent(self, event):
        if not self.pinned and not self.editor.hasFocus():
            self._collapse_timer.start(600)
        super().leaveEvent(event)

    def mouseMoveEvent(self, event):
        pos = event.position()
        self._hover_pin = self._pin_rect.contains(pos)
        if self._dragging and (event.buttons() & Qt.LeftButton):
            new_pos = event.globalPosition().toPoint() - self._drag_offset
            if abs(new_pos.x() - 24) <= 12:
                new_pos.setX(24)
            self.move(new_pos)
            self.positionChangedByUser.emit()
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            pos = event.position()
            if self._pin_rect.contains(pos):
                self.pinned = not self.pinned
                self.pinToggled.emit(self.pinned)
                self.update()
                return
            if pos.y() <= self.HEADER_HEIGHT and self._allow_drag_provider():
                self._dragging = True
                self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton and event.position().y() <= self.HEADER_HEIGHT:
            if self._expanded:
                self.editor.clearFocus()
                self.pinned = False
                self.pinToggled.emit(False)
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
        act_pin = menu.addAction("取消常驻展开" if self.pinned else "常驻展开速记卡片")
        act_todo = menu.addAction("插入待办项 [ ]")
        menu.addSeparator()
        act_hide_memo = menu.addAction("关闭极光速记卡片 (可在托盘随时重开)")

        chosen = menu.exec(event.globalPos())
        self.set_menu_open(False)
        if chosen == act_pin:
            self.pinned = not self.pinned
            self.pinToggled.emit(self.pinned)
            self.update()
        elif chosen == act_todo:
            self.editor.appendPlainText("[ ] ")
        elif chosen == act_hide_memo:
            self.closeMemoRequested.emit()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        c1, _, c2 = self.get_theme_colors()

        dot_rect = QRectF(14.0, (self.HEADER_HEIGHT - 7.0) / 2.0, 7.0, 7.0)
        dot_grad = QLinearGradient(dot_rect.topLeft(), dot_rect.bottomRight())
        dot_grad.setColorAt(0.0, c1)
        dot_grad.setColorAt(1.0, c2)
        painter.setPen(Qt.NoPen)
        painter.setBrush(dot_grad)
        painter.drawEllipse(dot_rect)

        font = make_apple_font(12, QFont.DemiBold, 0.6)
        painter.setFont(font)
        title_rect = QRectF(28.0, 0.0, 240.0, float(self.HEADER_HEIGHT))
        painter.setPen(QColor(0, 0, 0, 115))
        painter.drawText(title_rect.translated(0, 1.0), Qt.AlignLeft | Qt.AlignVCenter, self.title)
        painter.setPen(QColor(255, 255, 255, 238))
        painter.drawText(title_rect, Qt.AlignLeft | Qt.AlignVCenter, self.title)

        cx, cy = self._pin_rect.center().x(), self._pin_rect.center().y()
        if self.pinned:
            col_p = QColor(c1); col_p.setAlpha(210)
            painter.setBrush(col_p)
            col_ring = QColor(c1); col_ring.setAlpha(120)
            painter.setPen(QPen(col_ring, 2.0))
            painter.drawEllipse(QPointF(cx, cy), 4.0, 4.0)
        elif self._border_glow > 0.05:
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor(220, 235, 255, int(110 * self._border_glow)), 1.2))
            painter.drawEllipse(QPointF(cx, cy), 4.0, 4.0)
