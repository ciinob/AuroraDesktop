# -*- coding: utf-8 -*-
"""Aurora Media Capsule — Windows SMTC Now-Playing Glass Widget.

Automatically detects active media playback from NetEase Cloud Music, Spotify,
QQ Music, Apple Music, Edge/Chrome/Firefox, Bilibili, etc. via Windows SMTC
(GlobalSystemMediaTransportControlsSessionManager), extracts dominant colors
from the album cover for an adaptive Northern Lights backlight, and reveals
sleek hover transport controls (Prev / Play-Pause / Next).
"""
from __future__ import annotations

import asyncio
import math
import threading
import time
from dataclasses import dataclass

from PySide6.QtCore import QEasingCurve, QObject, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
    QRadialGradient,
)
from PySide6.QtWidgets import QMenu

from animator import HighRefreshAnimation
from widgets import AuroraBaseWindow, MENU_QSS, make_apple_font

try:
    from winrt.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as _GSMTC,
        GlobalSystemMediaTransportControlsSessionPlaybackStatus as _PBStatus,
    )
    from winrt.windows.storage.streams import DataReader as _DataReader

    SMTC_AVAILABLE = True
except Exception:
    _GSMTC = None
    _PBStatus = None
    _DataReader = None
    SMTC_AVAILABLE = False


# Friendly app names + preference boost for dedicated music players
_APP_LABELS: tuple[tuple[str, str, int], ...] = (
    ("cloudmusic", "网易云音乐", 30),
    ("netease", "网易云音乐", 30),
    ("appleinc.applemusic", "Apple Music", 30),
    ("applemusic", "Apple Music", 30),
    ("appmusic", "Apple Music", 30),
    ("music.apple", "Apple Music", 30),
    ("cider", "Apple Music (Cider)", 30),
    ("itunes", "Apple Music", 29),
    ("spotify", "Spotify", 30),
    ("qqmusic", "QQ 音乐", 28),
    ("kugou", "酷狗音乐", 25),
    ("kuwo", "酷我音乐", 25),
    ("foobar", "foobar2000", 24),
    ("potplayer", "PotPlayer", 18),
    ("vlc", "VLC", 18),
    ("bilibili", "哔哩哔哩", 16),
    ("msedgewebview2", "媒体播放", 2),
    ("msedge", "Edge", 12),
    ("chrome", "Chrome", 12),
    ("firefox", "Firefox", 12),
    ("brave", "Brave", 12),
    ("opera", "Opera", 12),
)


def friendly_app_name(aumid: str) -> tuple[str, int]:
    """Return (human_label, priority_score) for a Windows SMTC source AUMID."""
    low = (aumid or "").lower()
    for token, label, score in _APP_LABELS:
        if token in low:
            return label, score
    cleaned = (aumid or "").split("!")[0].split("\\")[-1]
    if cleaned.lower().endswith(".exe"):
        cleaned = cleaned[:-4]
    return (cleaned[:18] or "系统媒体"), 8


@dataclass
class MediaState:
    has_session: bool = False
    is_playing: bool = False
    title: str = ""
    artist: str = ""
    album: str = ""
    app_id: str = ""
    app_label: str = ""
    cover_bytes: bytes = b""
    cover_key: str = ""
    progress: float = -1.0  # 0.0..1.0 or -1.0 when unknown
    can_prev: bool = True
    can_next: bool = True
    can_toggle: bool = True
    # List of (app_id, friendly_label, is_playing) for all active SMTC sources
    sources: tuple[tuple[str, str, bool], ...] = ()
    pinned_app_id: str = ""


def extract_cover_palette(pm: QPixmap, fallback: tuple[QColor, QColor, QColor]) -> tuple[QColor, QColor]:
    """Extract a vivid primary + harmonious secondary aurora tint from album cover art."""
    if pm.isNull():
        return QColor(fallback[0]), QColor(fallback[2])

    img = pm.scaled(20, 20, Qt.IgnoreAspectRatio, Qt.FastTransformation).toImage()
    if img.isNull():
        return QColor(fallback[0]), QColor(fallback[2])

    buckets: dict[int, list[float]] = {}
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            if c.alpha() < 120:
                continue
            h, s, v, _ = c.getHsv()
            if h < 0 or s < 35 or v < 35:
                continue
            # Skip washed-out near-whites
            if s < 55 and v > 220:
                continue
            b = (h // 24) % 15
            w = 0.35 + (s / 255.0) * 2.2 + (0.45 if 55 < v < 235 else 0.0)
            acc = buckets.get(b)
            if acc is None:
                buckets[b] = [c.red() * w, c.green() * w, c.blue() * w, w]
            else:
                acc[0] += c.red() * w
                acc[1] += c.green() * w
                acc[2] += c.blue() * w
                acc[3] += w

    if not buckets:
        return QColor(fallback[0]), QColor(fallback[2])

    ranked = sorted(buckets.items(), key=lambda kv: kv[1][3], reverse=True)

    def _to_aurora_color(acc: list[float]) -> QColor:
        w = max(0.01, acc[3])
        col = QColor(int(acc[0] / w), int(acc[1] / w), int(acc[2] / w))
        h, s, l, _ = col.getHsl()
        if h < 0:
            return QColor(fallback[0])
        col.setHsl(h, max(145, min(238, s)), max(128, min(178, l)))
        return col

    c1 = _to_aurora_color(ranked[0][1])
    c2 = None
    h1 = c1.hslHue()
    for _, acc in ranked[1:]:
        cand = _to_aurora_color(acc)
        dh = abs(cand.hslHue() - h1)
        dh = min(dh, 360 - dh)
        if dh >= 28:
            c2 = cand
            break
    if c2 is None:
        c2 = QColor(c1)
        c2.setHsl((h1 + 42) % 360, c1.hslSaturation(), max(118, c1.lightness() - 10))
    return c1, c2


class SmtcBridge(QObject):
    """Dedicated background asyncio thread polling Windows SMTC & executing media commands."""

    mediaUpdated = Signal(object)  # MediaState

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stop_evt = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._mgr = None
        self._active_session = None
        self._pinned_app_id: str = ""
        self._available_sources: tuple[tuple[str, str, bool], ...] = ()
        self._cached_cover_key = ""
        self._cached_cover_bytes = b""
        self._last_sig: tuple | None = None

    def start(self):
        if not SMTC_AVAILABLE:
            return
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_evt.clear()
        self._thread = threading.Thread(target=self._run_thread, name="AuroraSmtcWorker", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_evt.set()
        loop = self._loop
        if loop is not None and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(loop.stop)
            except Exception:
                pass
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=0.6)
        self._thread = None
        self._loop = None

    def send_command(self, action: str):
        loop = self._loop
        if loop is None or loop.is_closed() or not SMTC_AVAILABLE:
            return
        try:
            asyncio.run_coroutine_threadsafe(self._exec_command(action), loop)
        except Exception:
            pass

    def set_pinned_source(self, app_id: str):
        """Pin a specific SMTC source app_id, or empty string for Auto."""
        self._pinned_app_id = app_id or ""
        self._last_sig = None
        loop = self._loop
        if loop is not None and not loop.is_closed() and SMTC_AVAILABLE:
            try:
                asyncio.run_coroutine_threadsafe(self._poll_once(), loop)
            except Exception:
                pass

    def cycle_source(self, delta: int = 1):
        sources = self._available_sources
        if len(sources) <= 1:
            return
        ids = [s[0] for s in sources]
        cur_id = self._pinned_app_id or (self._active_session.source_app_user_model_id if self._active_session else "")
        try:
            idx = ids.index(cur_id)
        except ValueError:
            idx = 0
        nxt = ids[(idx + delta) % len(ids)]
        self.set_pinned_source(nxt)

    def _run_thread(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        task = loop.create_task(self._poll_loop())
        try:
            loop.run_forever()
        finally:
            task.cancel()
            try:
                loop.run_until_complete(asyncio.gather(task, return_exceptions=True))
            except Exception:
                pass
            loop.close()

    async def _pick_best_session(self):
        if self._mgr is None:
            self._mgr = await _GSMTC.request_async()
        if self._mgr is None:
            self._available_sources = ()
            return None

        sessions = list(self._mgr.get_sessions())
        if not sessions:
            self._available_sources = ()
            return None

        current = self._mgr.get_current_session()
        current_id = current.source_app_user_model_id if current else ""

        valid_entries: list[tuple[tuple[int, int, int], object, str, str, bool]] = []
        for s in sessions:
            try:
                pb = s.get_playback_info()
                st = int(pb.playback_status) if pb else 0
                is_playing = st == int(_PBStatus.PLAYING)
                is_paused = st == int(_PBStatus.PAUSED)
                if not is_playing and not is_paused:
                    continue
                aid = s.source_app_user_model_id or ""
                lbl, app_prio = friendly_app_name(aid)
                is_cur = 1 if (aid == current_id) else 0
                rank = (1 if is_playing else 0, app_prio, is_cur)
                valid_entries.append((rank, s, aid, lbl, is_playing))
            except Exception:
                continue

        if not valid_entries:
            self._available_sources = ()
            return current

        valid_entries.sort(key=lambda e: e[0], reverse=True)
        self._available_sources = tuple((e[2], e[3], e[4]) for e in valid_entries)

        if self._pinned_app_id:
            for _, s, aid, _, _ in valid_entries:
                if aid == self._pinned_app_id:
                    return s

        return valid_entries[0][1]

    async def _read_thumbnail_bytes(self, thumb_ref) -> bytes:
        if thumb_ref is None or _DataReader is None:
            return b""
        try:
            stream = await thumb_ref.open_read_async()
            size = int(stream.size)
            if size <= 0 or size > 4 * 1024 * 1024:
                return b""
            reader = _DataReader(stream)
            await reader.load_async(size)
            buf = bytearray(size)
            reader.read_bytes(buf)
            return bytes(buf)
        except Exception:
            return b""

    async def _poll_once(self):
        session = await self._pick_best_session()
        self._active_session = session

        if session is None:
            sig = (False,)
            if sig != self._last_sig:
                self._last_sig = sig
                self._cached_cover_key = ""
                self._cached_cover_bytes = b""
                self.mediaUpdated.emit(MediaState(has_session=False))
            return

        pb = session.get_playback_info()
        st = int(pb.playback_status) if pb else 0
        is_playing = st == int(_PBStatus.PLAYING)
        controls = pb.controls if pb else None
        can_prev = bool(getattr(controls, "is_previous_enabled", True))
        can_next = bool(getattr(controls, "is_next_enabled", True))
        can_toggle = bool(
            getattr(controls, "is_play_pause_toggle_enabled", True)
            or getattr(controls, "is_play_enabled", True)
            or getattr(controls, "is_pause_enabled", True)
        )

        props = await session.try_get_media_properties_async()
        title = (props.title or "").strip() if props else ""
        artist = (props.artist or "").strip() if props else ""
        album = (props.album_title or "").strip() if props else ""
        app_id = session.source_app_user_model_id or ""
        app_label, _ = friendly_app_name(app_id)

        if not title and not artist:
            sig = (False,)
            if sig != self._last_sig:
                self._last_sig = sig
                self.mediaUpdated.emit(MediaState(has_session=False))
            return

        cover_key = f"{app_id}|{title}|{artist}|{album}"
        if cover_key != self._cached_cover_key:
            raw = await self._read_thumbnail_bytes(props.thumbnail if props else None)
            self._cached_cover_key = cover_key
            self._cached_cover_bytes = raw

        progress = -1.0
        try:
            tl = session.get_timeline_properties()
            if tl is not None:
                start_s = tl.start_time.total_seconds()
                end_s = tl.end_time.total_seconds()
                pos_s = tl.position.total_seconds()
                dur = end_s - start_s
                if dur > 1.0:
                    progress = max(0.0, min(1.0, (pos_s - start_s) / dur))
        except Exception:
            progress = -1.0

        prog_bucket = round(progress, 3) if progress >= 0 else -1.0
        sig = (
            True, is_playing, title, artist, album, app_label,
            len(self._cached_cover_bytes), prog_bucket, can_prev, can_next,
            self._available_sources, self._pinned_app_id,
        )
        if sig != self._last_sig:
            self._last_sig = sig
            self.mediaUpdated.emit(
                MediaState(
                    has_session=True,
                    is_playing=is_playing,
                    title=title,
                    artist=artist,
                    album=album,
                    app_id=app_id,
                    app_label=app_label,
                    cover_bytes=self._cached_cover_bytes,
                    cover_key=cover_key,
                    progress=progress,
                    can_prev=can_prev,
                    can_next=can_next,
                    can_toggle=can_toggle,
                    sources=self._available_sources,
                    pinned_app_id=self._pinned_app_id,
                )
            )

    async def _exec_command(self, action: str):
        session = self._active_session or await self._pick_best_session()
        if session is None:
            return
        try:
            if action == "toggle":
                await session.try_toggle_play_pause_async()
            elif action == "next":
                await session.try_skip_next_async()
            elif action == "prev":
                await session.try_skip_previous_async()
        except Exception:
            pass
        await asyncio.sleep(0.12)
        try:
            await self._poll_once()
        except Exception:
            pass

    async def _poll_loop(self):
        while not self._stop_evt.is_set():
            try:
                await self._poll_once()
            except Exception:
                self._mgr = None
            await asyncio.sleep(0.75)


class AuroraMediaCapsule(AuroraBaseWindow):
    """Floating Northern Lights SMTC Media Capsule with album-cover backlight & hover controls."""

    closeMediaRequested = Signal()

    CARD_WIDTH = 368
    CARD_HEIGHT = 74

    def __init__(
        self,
        allow_drag_provider=None,
        theme_provider=None,
        opacity_provider=None,
        snap_manager=None,
    ):
        super().__init__(
            allow_drag_provider=allow_drag_provider,
            theme_provider=theme_provider,
            opacity_provider=opacity_provider,
            snap_manager=snap_manager,
        )
        self.group_key = "__AURORA_MEDIA__"
        self.title = "NOW PLAYING · 媒体胶囊"

        self.setFixedSize(self.CARD_WIDTH, self.CARD_HEIGHT)

        self._state = MediaState()
        self._cover_pm = QPixmap()
        self._cover_key = ""

        c1, _, c2 = self.get_theme_colors()
        self._aura_c1 = QColor(c1)
        self._aura_c2 = QColor(c2)

        # Hover controls geometry (right side)
        cy = self.CARD_HEIGHT / 2.0
        self._btn_prev = QRectF(self.CARD_WIDTH - 114.0, cy - 15.0, 28.0, 30.0)
        self._btn_play = QRectF(self.CARD_WIDTH - 80.0, cy - 17.0, 34.0, 34.0)
        self._btn_next = QRectF(self.CARD_WIDTH - 40.0, cy - 15.0, 28.0, 30.0)
        self._hover_btn = ""  # "prev" | "play" | "next" | ""
        self._pressed_btn = ""

        # Smooth hover cross-fade between equalizer & transport buttons
        self._ctrl_alpha = 0.0
        self._ctrl_anim = HighRefreshAnimation(self)
        self._ctrl_anim.setDuration(170)
        self._ctrl_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._ctrl_anim.valueChanged.connect(self._on_ctrl_alpha)

        # Gentle 24fps audio bar visualizer timer (runs ONLY while playing & visible)
        self._viz_phase = 0.0
        self._viz_timer = QTimer(self)
        self._viz_timer.setInterval(42)
        self._viz_timer.timeout.connect(self._tick_viz)

        # SMTC background bridge
        self._smtc = SmtcBridge(self)
        self._smtc.mediaUpdated.connect(self._on_media_updated)
        self._smtc.start()

    def shutdown(self):
        self._viz_timer.stop()
        self._smtc.stop()

    def _on_ctrl_alpha(self, v):
        self._ctrl_alpha = float(v)
        self.update()

    def _tick_viz(self):
        self._viz_phase = (self._viz_phase + 0.22) % (math.pi * 20.0)
        self.update()

    def _sync_viz_timer(self):
        should_run = self.isVisible() and self._state.has_session and self._state.is_playing
        if should_run and not self._viz_timer.isActive():
            self._viz_timer.start()
        elif not should_run and self._viz_timer.isActive():
            self._viz_timer.stop()

    def _on_media_updated(self, state: MediaState):
        self._state = state
        if not state.has_session:
            self._cover_pm = QPixmap()
            self._cover_key = ""
            c1, _, c2 = self.get_theme_colors()
            self._aura_c1 = QColor(c1)
            self._aura_c2 = QColor(c2)
        elif state.cover_key != self._cover_key:
            self._cover_key = state.cover_key
            if state.cover_bytes:
                img = QImage.fromData(state.cover_bytes)
                self._cover_pm = QPixmap.fromImage(img) if not img.isNull() else QPixmap()
            else:
                self._cover_pm = QPixmap()
            self._aura_c1, self._aura_c2 = extract_cover_palette(self._cover_pm, self.get_theme_colors())

        self._sync_viz_timer()
        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_viz_timer()

    def hideEvent(self, event):
        self._viz_timer.stop()
        super().hideEvent(event)

    def enterEvent(self, event):
        self._ctrl_anim.stop()
        self._ctrl_anim.setStartValue(self._ctrl_alpha)
        self._ctrl_anim.setEndValue(1.0)
        self._ctrl_anim.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover_btn = ""
        self._pressed_btn = ""
        if not self._menu_open:
            self._ctrl_anim.stop()
            self._ctrl_anim.setStartValue(self._ctrl_alpha)
            self._ctrl_anim.setEndValue(0.0)
            self._ctrl_anim.start()
        super().leaveEvent(event)

    def _hit_button(self, pos: QPointF) -> str:
        if not self._state.has_session:
            return ""
        if self._btn_play.contains(pos):
            return "play"
        if self._btn_prev.contains(pos):
            return "prev"
        if self._btn_next.contains(pos):
            return "next"
        return ""

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            btn = self._hit_button(event.position())
            if btn:
                self._pressed_btn = btn
                self.update()
                return
            if self._allow_drag_provider():
                self._begin_smart_drag(event.globalPosition().toPoint())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not self._dragging:
            hit = self._hit_button(event.position())
            if hit != self._hover_btn:
                self._hover_btn = hit
                self.setCursor(Qt.PointingHandCursor if hit else Qt.ArrowCursor)
                self.update()
        if self._dragging and (event.buttons() & Qt.LeftButton):
            self._move_smart_drag(event.globalPosition().toPoint(), event.modifiers())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._pressed_btn:
            btn = self._pressed_btn
            self._pressed_btn = ""
            if self._hit_button(event.position()) == btn:
                if btn == "play":
                    self._smtc.send_command("toggle")
                elif btn == "prev":
                    self._smtc.send_command("prev")
                elif btn == "next":
                    self._smtc.send_command("next")
            self.update()
            return
        self._end_smart_drag()
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        if len(self._state.sources) > 1:
            delta = -1 if event.angleDelta().y() > 0 else 1
            self._smtc.cycle_source(delta)
            event.accept()
            return
        super().wheelEvent(event)

    def contextMenuEvent(self, event):
        self.set_menu_open(True)
        menu = QMenu(self)
        menu.setStyleSheet(MENU_QSS)
        act_toggle = act_prev = act_next = None
        source_actions: dict = {}
        if self._state.has_session:
            act_toggle = menu.addAction("⏸ 暂停播放" if self._state.is_playing else "▶ 继续播放")
            act_prev = menu.addAction("⏮ 上一首")
            act_next = menu.addAction("⏭ 下一首")
            if self._state.sources:
                src_menu = menu.addMenu(f"🔀 切换媒体源（当前：{self._state.app_label}）")
                src_menu.setStyleSheet(MENU_QSS)
                a_auto = src_menu.addAction("✨ 自动选择（优先音乐播放器）")
                a_auto.setCheckable(True)
                a_auto.setChecked(not self._state.pinned_app_id)
                source_actions[a_auto] = ""
                src_menu.addSeparator()
                for aid, lbl, playing in self._state.sources:
                    dot = "▶ " if playing else "⏸ "
                    a_src = src_menu.addAction(f"{dot}{lbl}")
                    a_src.setCheckable(True)
                    a_src.setChecked(self._state.pinned_app_id == aid)
                    source_actions[a_src] = aid
            menu.addSeparator()
        act_close = menu.addAction("关闭媒体播放胶囊（可在主控台/托盘随时重开）")

        chosen = menu.exec(event.globalPos())
        self.set_menu_open(False)
        if chosen is not None:
            if chosen == act_toggle:
                self._smtc.send_command("toggle")
            elif chosen == act_prev:
                self._smtc.send_command("prev")
            elif chosen == act_next:
                self._smtc.send_command("next")
            elif chosen in source_actions:
                self._smtc.set_pinned_source(source_actions[chosen])
            elif chosen == act_close:
                self.closeMediaRequested.emit()

    # ------------------------------------------------------------- painting
    def _draw_transport_icon(self, painter: QPainter, rect: QRectF, kind: str, alpha: float, is_hovered: bool, is_pressed: bool):
        cx, cy = rect.center().x(), rect.center().y()
        scale = 0.90 if is_pressed else 1.0

        painter.save()
        painter.translate(cx, cy)
        painter.scale(scale, scale)

        if kind == "play":
            bg_a = int((95 if is_hovered else 55) * alpha)
            bg = QColor(self._aura_c1)
            bg.setAlpha(bg_a)
            border = QColor(self._aura_c1).lighter(125)
            border.setAlpha(int((200 if is_hovered else 135) * alpha))
            painter.setBrush(bg)
            painter.setPen(QPen(border, 1.1))
            painter.drawEllipse(QPointF(0, 0), 15.0, 15.0)
        elif is_hovered:
            painter.setBrush(QColor(255, 255, 255, int(34 * alpha)))
            painter.setPen(QPen(QColor(255, 255, 255, int(55 * alpha)), 1.0))
            painter.drawEllipse(QPointF(0, 0), 12.5, 12.5)

        fg = QColor(255, 255, 255, int((250 if is_hovered or kind == "play" else 205) * alpha))
        painter.setBrush(fg)
        painter.setPen(Qt.NoPen)

        if kind == "play":
            if self._state.is_playing:
                painter.drawRoundedRect(QRectF(-4.8, -5.5, 3.2, 11.0), 1.2, 1.2)
                painter.drawRoundedRect(QRectF(1.6, -5.5, 3.2, 11.0), 1.2, 1.2)
            else:
                tri = QPolygonF([QPointF(-3.2, -5.8), QPointF(6.0, 0.0), QPointF(-3.2, 5.8)])
                painter.drawPolygon(tri)
        elif kind == "prev":
            painter.drawRoundedRect(QRectF(-6.0, -4.8, 2.0, 9.6), 0.8, 0.8)
            tri = QPolygonF([QPointF(5.0, -4.8), QPointF(-3.2, 0.0), QPointF(5.0, 4.8)])
            painter.drawPolygon(tri)
        elif kind == "next":
            painter.drawRoundedRect(QRectF(4.0, -4.8, 2.0, 9.6), 0.8, 0.8)
            tri = QPolygonF([QPointF(-5.0, -4.8), QPointF(3.2, 0.0), QPointF(-5.0, 4.8)])
            painter.drawPolygon(tri)

        painter.restore()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing)

        rect = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        clip_path = QPainterPath()
        clip_path.addRoundedRect(rect, self.RADIUS, self.RADIUS)
        painter.setClipPath(clip_path)

        a1 = self._aura_c1
        a2 = self._aura_c2

        # 1. Album-cover adaptive aurora backlight glow + subtle dark readability scrim
        if self._state.has_session:
            glow_l = QRadialGradient(QPointF(42.0, self.height() / 2.0), 175.0)
            g1 = QColor(a1); g1.setAlpha(78 if self._state.is_playing else 46)
            g2 = QColor(a2); g2.setAlpha(30 if self._state.is_playing else 16)
            g3 = QColor(a2); g3.setAlpha(0)
            glow_l.setColorAt(0.0, g1)
            glow_l.setColorAt(0.55, g2)
            glow_l.setColorAt(1.0, g3)
            painter.fillPath(clip_path, glow_l)

            # Subtle dark glass scrim behind text so typography stays crisp over any cover/wallpaper
            scrim = QLinearGradient(62.0, 0.0, float(self.width()), 0.0)
            scrim.setColorAt(0.0, QColor(6, 10, 22, 62))
            scrim.setColorAt(1.0, QColor(6, 10, 22, 92))
            painter.fillPath(clip_path, scrim)

            # Tinted adaptive accent rim over base border
            rim = QLinearGradient(rect.topLeft(), rect.bottomRight())
            r1 = QColor(a1); r1.setAlpha(int(120 + 95 * self._border_glow))
            r2 = QColor(a2); r2.setAlpha(int(95 + 85 * self._border_glow))
            rim.setColorAt(0.0, r1)
            rim.setColorAt(1.0, r2)
            painter.setPen(QPen(QBrush(rim), 1.15))
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(clip_path)

        # 2. Left Album Cover Art (50x50 rounded square)
        art_rect = QRectF(12.0, (self.height() - 50.0) / 2.0, 50.0, 50.0)
        art_path = QPainterPath()
        art_path.addRoundedRect(art_rect, 11.0, 11.0)

        if not self._cover_pm.isNull():
            # Soft ambient halo behind cover
            halo_c = QColor(a1); halo_c.setAlpha(65)
            painter.setPen(QPen(halo_c, 3.0))
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(art_path)

            painter.save()
            painter.setClipPath(art_path)
            scaled = self._cover_pm.scaled(
                int(art_rect.width() * 2),
                int(art_rect.height() * 2),
                Qt.KeepAspectRatioByExpanding,
                Qt.SmoothTransformation,
            )
            sx = (scaled.width() - art_rect.width() * 2) / 2.0
            sy = (scaled.height() - art_rect.height() * 2) / 2.0
            src = QRectF(max(0.0, sx), max(0.0, sy), art_rect.width() * 2, art_rect.height() * 2)
            painter.drawPixmap(art_rect, scaled, src)
            painter.restore()
            painter.setPen(QPen(QColor(255, 255, 255, 55), 1.0))
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(art_path)
        else:
            # Sleek placeholder music badge
            bg = QLinearGradient(art_rect.topLeft(), art_rect.bottomRight())
            p1 = QColor(a1); p1.setAlpha(60)
            p2 = QColor(a2); p2.setAlpha(48)
            bg.setColorAt(0.0, p1)
            bg.setColorAt(1.0, p2)
            painter.fillPath(art_path, bg)
            painter.setPen(QPen(QColor(255, 255, 255, 42), 1.0))
            painter.drawPath(art_path)
            painter.setFont(make_apple_font(20, QFont.Medium))
            painter.setPen(QColor(255, 255, 255, 210 if self._state.has_session else 135))
            painter.drawText(art_rect, Qt.AlignCenter, "♫")

        # 3. Track Title & Artist/App Subtitle (crisp high-contrast Apple-style hierarchy)
        # Smoothly narrow text column as hover transport buttons fade in
        right_reserved = 46.0 + 74.0 * self._ctrl_alpha if self._state.has_session else 18.0
        text_x = 74.0
        text_w = max(80.0, self.width() - text_x - right_reserved)

        title_font = make_apple_font(14, QFont.Bold, 0.15)
        sub_font = make_apple_font(12, QFont.Medium, 0.05)

        if self._state.has_session:
            title_txt = self._state.title or "正在播放"
            src_hint = self._state.app_label
            if len(self._state.sources) > 1:
                src_hint = f"{src_hint} ({len(self._state.sources)}源)"
            sub_parts = [p for p in (self._state.artist, src_hint) if p]
            sub_txt = "  ·  ".join(sub_parts) if sub_parts else "Windows 媒体控制"
            title_alpha = 255
            sub_alpha = 238
        else:
            title_txt = "等待媒体播放"
            sub_txt = "支持 网易云 / Apple Music / Spotify / 浏览器"
            title_alpha = 232
            sub_alpha = 188

        fm_t = QFontMetrics(title_font)
        fm_s = QFontMetrics(sub_font)
        elided_t = fm_t.elidedText(title_txt, Qt.ElideRight, int(text_w))
        elided_s = fm_s.elidedText(sub_txt, Qt.ElideRight, int(text_w))

        t_rect = QRectF(text_x, 14.0, text_w, 23.0)
        s_rect = QRectF(text_x, 38.0, text_w, 20.0)

        painter.setFont(title_font)
        painter.setPen(QColor(0, 0, 0, 185))
        painter.drawText(t_rect.translated(0, 1.2), Qt.AlignLeft | Qt.AlignVCenter, elided_t)
        painter.setPen(QColor(255, 255, 255, title_alpha))
        painter.drawText(t_rect, Qt.AlignLeft | Qt.AlignVCenter, elided_t)

        painter.setFont(sub_font)
        painter.setPen(QColor(0, 0, 0, 165))
        painter.drawText(s_rect.translated(0, 1.0), Qt.AlignLeft | Qt.AlignVCenter, elided_s)
        painter.setPen(QColor(238, 246, 255, sub_alpha))
        painter.drawText(s_rect, Qt.AlignLeft | Qt.AlignVCenter, elided_s)

        # 4. Right side: Ambient Equalizer (unhovered) <-> Transport Controls (hovered)
        if self._state.has_session:
            viz_alpha = max(0.0, 1.0 - self._ctrl_alpha * 1.4)
            if viz_alpha > 0.02:
                bar_x0 = self.width() - 34.0
                base_y = self.height() / 2.0 + 9.0
                for idx in range(4):
                    if self._state.is_playing:
                        wave = 0.5 + 0.5 * math.sin(self._viz_phase + idx * 1.35)
                        bh = 5.0 + wave * 13.0
                    else:
                        bh = 5.0 + (idx % 2) * 2.5
                    bx = bar_x0 + idx * 5.2
                    bar_col = QColor(a1 if idx % 2 == 0 else a2)
                    bar_col.setAlpha(int((215 if self._state.is_playing else 120) * viz_alpha))
                    painter.setBrush(bar_col)
                    painter.setPen(Qt.NoPen)
                    painter.drawRoundedRect(QRectF(bx, base_y - bh, 2.8, bh), 1.4, 1.4)

            if self._ctrl_alpha > 0.02:
                self._draw_transport_icon(
                    painter, self._btn_prev, "prev", self._ctrl_alpha,
                    self._hover_btn == "prev", self._pressed_btn == "prev",
                )
                self._draw_transport_icon(
                    painter, self._btn_play, "play", self._ctrl_alpha,
                    self._hover_btn == "play", self._pressed_btn == "play",
                )
                self._draw_transport_icon(
                    painter, self._btn_next, "next", self._ctrl_alpha,
                    self._hover_btn == "next", self._pressed_btn == "next",
                )

            # 5. Subtle 2px bottom playback progress hairline
            if self._state.progress >= 0.0:
                px1 = 14.0
                pw = (self.width() - 28.0) * self._state.progress
                py = float(self.height() - 3.0)
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(255, 255, 255, 24))
                painter.drawRoundedRect(QRectF(px1, py, self.width() - 28.0, 2.0), 1.0, 1.0)
                if pw > 1.0:
                    pgrad = QLinearGradient(px1, py, px1 + max(20.0, pw), py)
                    pgrad.setColorAt(0.0, a1)
                    pgrad.setColorAt(1.0, a2)
                    painter.setBrush(pgrad)
                    painter.drawRoundedRect(QRectF(px1, py, pw, 2.0), 1.0, 1.0)
