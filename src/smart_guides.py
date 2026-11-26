# -*- coding: utf-8 -*-
"""Smart Guides & Magnetic Snap Alignment Preview engine for AuroraDesktop.

Provides Figma / VisionOS-inspired alignment guides, magnetic snapping, spacing
callouts, and a glowing snap-target preview frame when dragging any desktop
widget (Capsules, Cards, Memo Card, or Artistic Clock).

Hold Alt while dragging to temporarily bypass magnetic snapping and hide guides.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from PySide6.QtCore import QEasingCurve, QPoint, QPointF, QRect, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetricsF,
    QGuiApplication,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QWidget

from animator import HighRefreshAnimation
from win32_utils import (
    GWL_EXSTYLE,
    WS_EX_LAYERED,
    WS_EX_NOACTIVATE,
    WS_EX_TOOLWINDOW,
    WS_EX_TRANSPARENT,
    user32,
)


@dataclass(frozen=True)
class GuideLine:
    """A single horizontal or vertical smart guide line in global screen coordinates."""
    orientation: str          # "v" (vertical line at x) or "h" (horizontal line at y)
    coord: int                # x if vertical, y if horizontal
    start: int                # y1 if vertical, x1 if horizontal
    end: int                  # y2 if vertical, x2 if horizontal
    kind: str                 # "peer", "screen_center", "screen_margin", "gap"
    label: str = ""
    anchors: tuple[tuple[int, int], ...] = ()


@dataclass(frozen=True)
class GapCallout:
    """Visual spacing measurement between two adjacent widgets (or widget & screen edge)."""
    orientation: str          # "h" (horizontal gap) or "v" (vertical gap)
    p1: tuple[int, int]
    p2: tuple[int, int]
    label: str
    equal: bool = False


@dataclass
class SnapResult:
    """Computed magnetic snap result for a single drag frame."""
    snapped_pos: QPoint
    raw_pos: QPoint
    snapped_x: bool = False
    snapped_y: bool = False
    guides: list[GuideLine] = field(default_factory=list)
    gaps: list[GapCallout] = field(default_factory=list)
    snapped_rect: QRect = field(default_factory=QRect)

    @property
    def has_snap(self) -> bool:
        return self.snapped_x or self.snapped_y


def _ranges_overlap_or_near(a1: int, a2: int, b1: int, b2: int, pad: int = 240) -> bool:
    return (a1 - pad) <= b2 and (b1 - pad) <= a2


def clamp_rect_to_screen(
    rect: QRect,
    screen_avail: QRect,
    all_screens_avail: list[QRect] | None = None,
) -> QPoint:
    """Keep a dragged widget safely on-screen without blocking cross-monitor drags.

    Outer screen edges are clamped so widgets cannot be lost off-screen or behind
    the taskbar; shared borders between adjacent monitors remain open.
    """
    if not screen_avail.isValid():
        return rect.topLeft()

    x = rect.x()
    y = rect.y()
    w = rect.width()
    h = rect.height()

    sc_l = screen_avail.x()
    sc_t = screen_avail.y()
    sc_r = sc_l + screen_avail.width()
    sc_b = sc_t + screen_avail.height()

    has_left = has_right = has_top = has_bottom = False
    if all_screens_avail and len(all_screens_avail) > 1:
        for other in all_screens_avail:
            if other == screen_avail or not other.isValid():
                continue
            ol, ot = other.x(), other.y()
            or_, ob = ol + other.width(), ot + other.height()
            if abs(or_ - sc_l) <= 40 and _ranges_overlap_or_near(sc_t, sc_b, ot, ob, pad=0):
                has_left = True
            if abs(ol - sc_r) <= 40 and _ranges_overlap_or_near(sc_t, sc_b, ot, ob, pad=0):
                has_right = True
            if abs(ob - sc_t) <= 40 and _ranges_overlap_or_near(sc_l, sc_r, ol, or_, pad=0):
                has_top = True
            if abs(ot - sc_b) <= 40 and _ranges_overlap_or_near(sc_l, sc_r, ol, or_, pad=0):
                has_bottom = True

    if not has_left:
        x = max(sc_l, x)
    if not has_right and w <= screen_avail.width():
        x = min(sc_r - w, x)
    if not has_top:
        y = max(sc_t, y)
    if not has_bottom and h <= screen_avail.height():
        y = min(sc_b - h, y)
    return QPoint(x, y)


def _find_equal_spacing_candidates(
    axis: str,
    raw_start: int,
    raw_size: int,
    raw_cross_start: int,
    raw_cross_end: int,
    peer_rects: list[QRect],
    snap_threshold: int,
    min_gap: int = 4,
    max_gap: int = 280,
) -> list[tuple[float, int, int]]:
    """Return (abs_delta, priority, target_start) candidates for Figma-style equal spacing."""
    # Filter peers that overlap or sit close along the cross axis
    relevant: list[tuple[int, int, int, int]] = []
    for pr in peer_rects:
        if not pr.isValid():
            continue
        if axis == "v":
            c1, c2 = pr.x(), pr.x() + pr.width()
            s1, s2 = pr.y(), pr.y() + pr.height()
        else:
            c1, c2 = pr.y(), pr.y() + pr.height()
            s1, s2 = pr.x(), pr.x() + pr.width()
        if _ranges_overlap_or_near(raw_cross_start, raw_cross_end, c1, c2, pad=80):
            relevant.append((s1, s2, c1, c2))

    if len(relevant) < 2:
        return []

    relevant.sort(key=lambda item: item[0])
    out: list[tuple[float, int, int]] = []
    raw_end = raw_start + raw_size

    for i in range(len(relevant) - 1):
        a1, a2, _, _ = relevant[i]
        b1, b2, _, _ = relevant[i + 1]
        gap = b1 - a2
        if min_gap <= gap <= max_gap:
            # 1) Active placed after B with same gap
            t_after = b2 + gap
            if abs(raw_start - t_after) <= snap_threshold:
                out.append((abs(raw_start - t_after), 1, t_after))
            # 2) Active placed before A with same gap
            t_before = a1 - gap - raw_size
            if abs(raw_start - t_before) <= snap_threshold:
                out.append((abs(raw_start - t_before), 1, t_before))
        # 3) Active centered between A and B
        inner_space = b1 - a2 - raw_size
        if inner_space >= min_gap * 2 and inner_space <= max_gap * 2:
            t_mid = a2 + inner_space // 2
            if abs(raw_start - t_mid) <= snap_threshold:
                out.append((abs(raw_start - t_mid), 1, t_mid))

    return out


def _collect_equal_spacing_callouts(
    axis: str,
    final_start: int,
    final_size: int,
    final_cross_start: int,
    final_cross_end: int,
    peer_rects: list[QRect],
    min_gap: int = 4,
    max_gap: int = 280,
) -> list[GapCallout]:
    """Collect paired GapCallouts whenever final_rect forms an equal-spacing trio with peers."""
    relevant: list[tuple[int, int, int, int]] = []
    for pr in peer_rects:
        if not pr.isValid():
            continue
        if axis == "v":
            c1, c2 = pr.x(), pr.x() + pr.width()
            s1, s2 = pr.y(), pr.y() + pr.height()
        else:
            c1, c2 = pr.y(), pr.y() + pr.height()
            s1, s2 = pr.x(), pr.x() + pr.width()
        if _ranges_overlap_or_near(final_cross_start, final_cross_end, c1, c2, pad=80):
            relevant.append((s1, s2, c1, c2))

    if len(relevant) < 2:
        return []

    relevant.sort(key=lambda item: item[0])
    final_end = final_start + final_size
    callouts: list[GapCallout] = []
    seen: set[tuple[str, tuple[int, int], tuple[int, int]]] = set()

    def _mid_cross(c1_a: int, c2_a: int, c1_b: int, c2_b: int) -> int:
        ov1 = max(c1_a, c1_b)
        ov2 = min(c2_a, c2_b)
        if ov2 > ov1:
            return int(round((ov1 + ov2) / 2.0))
        return int(round(((c1_a + c2_a) / 2.0 + (c1_b + c2_b) / 2.0) / 2.0))

    def _push(start_edge: int, end_edge: int, mc: int, gap_val: int):
        if axis == "v":
            p1, p2 = (mc, start_edge), (mc, end_edge)
        else:
            p1, p2 = (start_edge, mc), (end_edge, mc)
        key = (axis, p1, p2)
        if key not in seen:
            seen.add(key)
            callouts.append(GapCallout(axis, p1, p2, f"{gap_val}px", equal=True))

    for i in range(len(relevant) - 1):
        a1, a2, ac1, ac2 = relevant[i]
        b1, b2, bc1, bc2 = relevant[i + 1]
        gap_ab = b1 - a2

        # Case 1: active below/right of B with same gap as A..B
        if min_gap <= gap_ab <= max_gap and final_start == b2 + gap_ab:
            _push(a2, b1, _mid_cross(ac1, ac2, bc1, bc2), gap_ab)
            _push(b2, final_start, _mid_cross(bc1, bc2, final_cross_start, final_cross_end), gap_ab)

        # Case 2: active above/left of A with same gap as A..B
        if min_gap <= gap_ab <= max_gap and final_end == a1 - gap_ab:
            _push(final_end, a1, _mid_cross(final_cross_start, final_cross_end, ac1, ac2), gap_ab)
            _push(a2, b1, _mid_cross(ac1, ac2, bc1, bc2), gap_ab)

        # Case 3: active centered between A and B (allow 1px odd-pixel tolerance)
        gap_1 = final_start - a2
        gap_2 = b1 - final_end
        if min_gap <= gap_1 <= max_gap and min_gap <= gap_2 <= max_gap and abs(gap_1 - gap_2) <= 1:
            _push(a2, final_start, _mid_cross(ac1, ac2, final_cross_start, final_cross_end), gap_1)
            _push(final_end, b1, _mid_cross(final_cross_start, final_cross_end, bc1, bc2), gap_2)

    return callouts


def compute_smart_snap(
    raw_rect: QRect,
    screen_avail: QRect,
    peer_rects: list[QRect],
    *,
    snap_threshold: int = 10,
    margin_x: int = 24,
    margin_y: int = 24,
    card_gap: int = 10,
    col_gap: int = 14,
    bypass: bool = False,
    clamp_bounds: bool = True,
    all_screens_avail: list[QRect] | None = None,
) -> SnapResult:
    """Compute magnetic snap position, smart guide lines, and spacing callouts.

    Pure geometry function (no widget/window state) so it is fast and directly
    unit-testable. All coordinates are in global screen pixels.
    """
    clamped_pos = (
        clamp_rect_to_screen(raw_rect, screen_avail, all_screens_avail)
        if clamp_bounds and screen_avail.isValid()
        else raw_rect.topLeft()
    )
    work_rect = QRect(clamped_pos, raw_rect.size())
    raw_pos = work_rect.topLeft()
    if bypass or not screen_avail.isValid():
        return SnapResult(
            snapped_pos=QPoint(raw_pos),
            raw_pos=QPoint(raw_pos),
            snapped_rect=QRect(work_rect),
        )

    w = work_rect.width()
    h = work_rect.height()
    # Use exclusive right/bottom edges (x + w, y + h) so arithmetic is exact.
    raw_l = work_rect.x()
    raw_r = raw_l + w
    raw_cx = raw_l + w / 2.0

    raw_t = work_rect.y()
    raw_b = raw_t + h
    raw_cy = raw_t + h / 2.0

    sc_l = screen_avail.x()
    sc_t = screen_avail.y()
    sc_r = sc_l + screen_avail.width()
    sc_b = sc_t + screen_avail.height()
    sc_cx = sc_l + screen_avail.width() / 2.0
    sc_cy = sc_t + screen_avail.height() / 2.0

    # Candidate tuple: (abs_delta, priority, target_x_or_y)
    # Lower priority number wins ties when abs_delta is identical.
    x_candidates: list[tuple[float, int, int]] = []
    y_candidates: list[tuple[float, int, int]] = []

    def add_x(delta: float, prio: int, target_x: int):
        ad = abs(delta)
        if ad <= snap_threshold:
            x_candidates.append((ad, prio, int(round(target_x))))

    def add_y(delta: float, prio: int, target_y: int):
        ad = abs(delta)
        if ad <= snap_threshold:
            y_candidates.append((ad, prio, int(round(target_y))))

    # 1. Screen center & safe margin candidates
    add_x(raw_cx - sc_cx, 1, int(round(sc_cx - w / 2.0)))
    add_x(raw_l - (sc_l + margin_x), 2, sc_l + margin_x)
    add_x(raw_r - (sc_r - margin_x), 2, sc_r - margin_x - w)

    add_y(raw_cy - sc_cy, 1, int(round(sc_cy - h / 2.0)))
    add_y(raw_t - (sc_t + margin_y), 2, sc_t + margin_y)
    add_y(raw_b - (sc_b - margin_y), 2, sc_b - margin_y - h)

    # 2. Peer widget alignment & standard spacing candidates
    for pr in peer_rects:
        if not pr.isValid():
            continue
        pl = pr.x()
        pr_r = pl + pr.width()
        pcx = pl + pr.width() / 2.0
        pt = pr.y()
        pb = pt + pr.height()
        pcy = pt + pr.height() / 2.0

        # Vertical guides (X alignment)
        add_x(raw_l - pl, 0, pl)
        add_x(raw_r - pr_r, 0, pr_r - w)
        add_x(raw_cx - pcx, 0, int(round(pcx - w / 2.0)))
        add_x(raw_l - pr_r, 3, pr_r)
        add_x(raw_r - pl, 3, pl - w)

        if _ranges_overlap_or_near(raw_t, raw_b, pt, pb, pad=200):
            add_x(raw_l - (pr_r + col_gap), 2, pr_r + col_gap)
            add_x(raw_r - (pl - col_gap), 2, pl - col_gap - w)

        # Horizontal guides (Y alignment)
        add_y(raw_t - pt, 0, pt)
        add_y(raw_b - pb, 0, pb - h)
        add_y(raw_cy - pcy, 0, int(round(pcy - h / 2.0)))
        add_y(raw_t - pb, 3, pb)
        add_y(raw_b - pt, 3, pt - h)

        if _ranges_overlap_or_near(raw_l, raw_r, pl, pr_r, pad=200):
            add_y(raw_t - (pb + card_gap), 2, pb + card_gap)
            add_y(raw_b - (pt - card_gap), 2, pt - card_gap - h)

    # 2b. Figma-style equal-spacing distribution candidates
    x_candidates.extend(
        _find_equal_spacing_candidates("h", raw_l, w, raw_t, raw_b, peer_rects, snap_threshold)
    )
    y_candidates.extend(
        _find_equal_spacing_candidates("v", raw_t, h, raw_l, raw_r, peer_rects, snap_threshold)
    )

    snapped_x = False
    snapped_y = False
    final_x = raw_l
    final_y = raw_t

    if x_candidates:
        x_candidates.sort(key=lambda item: (item[0], item[1]))
        final_x = x_candidates[0][2]
        snapped_x = True

    if y_candidates:
        y_candidates.sort(key=lambda item: (item[0], item[1]))
        final_y = y_candidates[0][2]
        snapped_y = True

    if clamp_bounds:
        clamped_final = clamp_rect_to_screen(QRect(final_x, final_y, w, h), screen_avail, all_screens_avail)
        final_x, final_y = clamped_final.x(), clamped_final.y()

    snapped_rect = QRect(final_x, final_y, w, h)
    fl = final_x
    fr = final_x + w
    fcx = final_x + w / 2.0
    ft = final_y
    fb = final_y + h
    fcy = final_y + h / 2.0

    guides: list[GuideLine] = []
    gaps: list[GapCallout] = []
    seen_v: set[tuple[int, str]] = set()
    seen_h: set[tuple[int, str]] = set()

    # 3. Collect all active visual guide lines at the final snapped geometry
    if snapped_x:
        if abs(fcx - sc_cx) <= 1.0:
            cx_i = int(round(sc_cx))
            guides.append(GuideLine(
                orientation="v",
                coord=cx_i,
                start=sc_t,
                end=sc_b,
                kind="screen_center",
                label="水平居中",
                anchors=((cx_i, ft), (cx_i, fb)),
            ))
            seen_v.add((cx_i, "screen_center"))

        if fl == sc_l + margin_x:
            guides.append(GuideLine(
                orientation="v",
                coord=fl,
                start=sc_t + 12,
                end=sc_b - 12,
                kind="screen_margin",
                label=f"边距 {margin_x}px",
                anchors=((fl, ft), (fl, fb)),
            ))
            seen_v.add((fl, "screen_margin"))

        if fr == sc_r - margin_x:
            guides.append(GuideLine(
                orientation="v",
                coord=fr,
                start=sc_t + 12,
                end=sc_b - 12,
                kind="screen_margin",
                label=f"边距 {margin_x}px",
                anchors=((fr, ft), (fr, fb)),
            ))
            seen_v.add((fr, "screen_margin"))

        # Peer vertical guides (group by x coord so multiple aligned cards merge cleanly)
        peer_v_spans: dict[int, list[tuple[int, int, tuple[int, int]]]] = {}
        for pr in peer_rects:
            if not pr.isValid():
                continue
            pl = pr.x()
            pr_r = pl + pr.width()
            pcx = pl + pr.width() / 2.0
            pt = pr.y()
            pb = pt + pr.height()

            def _add_peer_v(coord: int, ay1: int, ay2: int):
                peer_v_spans.setdefault(coord, []).append((min(ft, pt), max(fb, pb), (coord, ay1)))
                peer_v_spans[coord].append((min(ft, pt), max(fb, pb), (coord, ay2)))

            if fl == pl:
                _add_peer_v(fl, ft, pt)
            if fr == pr_r:
                _add_peer_v(fr, ft, pt)
            if abs(fcx - pcx) <= 1.0:
                _add_peer_v(int(round(pcx)), int(round(fcy)), int(round((pt + pb) / 2.0)))
            if fl == pr_r:
                _add_peer_v(fl, ft, pt)
            if fr == pl:
                _add_peer_v(fr, ft, pt)

            # Column gap callout
            if _ranges_overlap_or_near(ft, fb, pt, pb, pad=200):
                ov_top = max(ft, pt)
                ov_bot = min(fb, pb)
                mid_y = int(round((ov_top + ov_bot) / 2.0)) if ov_bot > ov_top else int(round((fcy + (pt + pb) / 2.0) / 2.0))
                if fl == pr_r + col_gap:
                    gaps.append(GapCallout("h", (pr_r, mid_y), (fl, mid_y), f"{col_gap}px"))
                elif fr == pl - col_gap:
                    gaps.append(GapCallout("h", (fr, mid_y), (pl, mid_y), f"{col_gap}px"))

        for coord, entries in peer_v_spans.items():
            if (coord, "screen_margin") in seen_v or (coord, "screen_center") in seen_v:
                continue
            y_min = min(e[0] for e in entries) - 18
            y_max = max(e[1] for e in entries) + 18
            anchors = tuple(dict.fromkeys(e[2] for e in entries))
            guides.append(GuideLine(
                orientation="v",
                coord=coord,
                start=max(sc_t, y_min),
                end=min(sc_b, y_max),
                kind="peer",
                anchors=anchors,
            ))

    if snapped_y:
        if abs(fcy - sc_cy) <= 1.0:
            cy_i = int(round(sc_cy))
            guides.append(GuideLine(
                orientation="h",
                coord=cy_i,
                start=sc_l,
                end=sc_r,
                kind="screen_center",
                label="垂直居中",
                anchors=((fl, cy_i), (fr, cy_i)),
            ))
            seen_h.add((cy_i, "screen_center"))

        if ft == sc_t + margin_y:
            guides.append(GuideLine(
                orientation="h",
                coord=ft,
                start=sc_l + 12,
                end=sc_r - 12,
                kind="screen_margin",
                label=f"边距 {margin_y}px",
                anchors=((fl, ft), (fr, ft)),
            ))
            seen_h.add((ft, "screen_margin"))

        if fb == sc_b - margin_y:
            guides.append(GuideLine(
                orientation="h",
                coord=fb,
                start=sc_l + 12,
                end=sc_r - 12,
                kind="screen_margin",
                label=f"边距 {margin_y}px",
                anchors=((fl, fb), (fr, fb)),
            ))
            seen_h.add((fb, "screen_margin"))

        peer_h_spans: dict[int, list[tuple[int, int, tuple[int, int]]]] = {}
        for pr in peer_rects:
            if not pr.isValid():
                continue
            pl = pr.x()
            pr_r = pl + pr.width()
            pt = pr.y()
            pb = pt + pr.height()
            pcy = pt + pr.height() / 2.0

            def _add_peer_h(coord: int, ax1: int, ax2: int):
                peer_h_spans.setdefault(coord, []).append((min(fl, pl), max(fr, pr_r), (ax1, coord)))
                peer_h_spans[coord].append((min(fl, pl), max(fr, pr_r), (ax2, coord)))

            if ft == pt:
                _add_peer_h(ft, fl, pl)
            if fb == pb:
                _add_peer_h(fb, fl, pl)
            if abs(fcy - pcy) <= 1.0:
                _add_peer_h(int(round(pcy)), int(round(fcx)), int(round((pl + pr_r) / 2.0)))
            if ft == pb:
                _add_peer_h(ft, fl, pl)
            if fb == pt:
                _add_peer_h(fb, fl, pl)

            # Vertical stack gap callout
            if _ranges_overlap_or_near(fl, fr, pl, pr_r, pad=200):
                ov_l = max(fl, pl)
                ov_r = min(fr, pr_r)
                mid_x = int(round((ov_l + ov_r) / 2.0)) if ov_r > ov_l else int(round((fcx + (pl + pr_r) / 2.0) / 2.0))
                if ft == pb + card_gap:
                    gaps.append(GapCallout("v", (mid_x, pb), (mid_x, ft), f"{card_gap}px"))
                elif fb == pt - card_gap:
                    gaps.append(GapCallout("v", (mid_x, fb), (mid_x, pt), f"{card_gap}px"))

        for coord, entries in peer_h_spans.items():
            if (coord, "screen_margin") in seen_h or (coord, "screen_center") in seen_h:
                continue
            x_min = min(e[0] for e in entries) - 18
            x_max = max(e[1] for e in entries) + 18
            anchors = tuple(dict.fromkeys(e[2] for e in entries))
            guides.append(GuideLine(
                orientation="h",
                coord=coord,
                start=max(sc_l, x_min),
                end=min(sc_r, x_max),
                kind="peer",
                anchors=anchors,
            ))

    # 3b. Equal-spacing distribution callouts (deduplicated against standard gaps)
    eq_gaps: list[GapCallout] = []
    if snapped_x:
        eq_gaps.extend(_collect_equal_spacing_callouts("h", fl, w, ft, fb, peer_rects))
    if snapped_y:
        eq_gaps.extend(_collect_equal_spacing_callouts("v", ft, h, fl, fr, peer_rects))
    if eq_gaps:
        eq_keys = {(g.orientation, g.p1, g.p2) for g in eq_gaps}
        gaps = [g for g in gaps if (g.orientation, g.p1, g.p2) not in eq_keys]
        gaps.extend(eq_gaps)

    return SnapResult(
        snapped_pos=QPoint(final_x, final_y),
        raw_pos=QPoint(raw_pos),
        snapped_x=snapped_x,
        snapped_y=snapped_y,
        guides=guides,
        gaps=gaps,
        snapped_rect=snapped_rect,
    )


class SmartGuideOverlay(QWidget):
    """Click-through translucent full-screen overlay painting Smart Guides & snap preview."""

    def __init__(self, theme_provider: Callable[[], tuple[QColor, QColor, QColor]], parent=None):
        super().__init__(parent)
        self._theme_provider = theme_provider
        self._result: SnapResult | None = None
        self._preview_radius: float = 14.0
        self._alpha: float = 0.0
        self._win32_styled = False

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.Tool
            | Qt.WindowStaysOnTopHint
            | Qt.WindowTransparentForInput
            | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)

        self._fade_anim = HighRefreshAnimation(self)
        self._fade_anim.setDuration(140)
        self._fade_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._fade_anim.valueChanged.connect(self._on_fade_val)
        self._fade_anim.finished.connect(self._on_fade_finished)
        self._hiding = False

    def _ensure_click_through(self):
        if self._win32_styled:
            return
        hwnd = int(self.winId())
        if not hwnd:
            return
        ex = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongPtrW(
            hwnd,
            GWL_EXSTYLE,
            ex | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_LAYERED | WS_EX_TRANSPARENT,
        )
        self._win32_styled = True

    def _on_fade_val(self, val):
        self._alpha = float(val)
        self.update()

    def _on_fade_finished(self):
        if self._hiding and self._alpha <= 0.01:
            self._result = None
            self.hide()
            self._hiding = False

    def show_snap(self, screen_geom: QRect, result: SnapResult, radius: float = 14.0):
        self._hiding = False
        self._result = result
        self._preview_radius = radius

        if not result.has_snap:
            if self.isVisible():
                self.fade_out()
            return

        if self.geometry() != screen_geom:
            self.setGeometry(screen_geom)

        if not self.isVisible():
            self._alpha = 0.0
            self.show()
            self._ensure_click_through()
            self._fade_anim.stop()
            self._fade_anim.setDuration(90)
            self._fade_anim.setStartValue(self._alpha)
            self._fade_anim.setEndValue(1.0)
            self._fade_anim.start()
        elif self._alpha < 0.99:
            self._fade_anim.stop()
            self._fade_anim.setDuration(90)
            self._fade_anim.setStartValue(self._alpha)
            self._fade_anim.setEndValue(1.0)
            self._fade_anim.start()

        self.update()

    def fade_out(self):
        if not self.isVisible():
            self._result = None
            return
        if self._hiding:
            return
        self._hiding = True
        self._fade_anim.stop()
        self._fade_anim.setDuration(140)
        self._fade_anim.setStartValue(self._alpha)
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.start()

    def _draw_pill(self, painter: QPainter, center: QPointF, text: str, accent: QColor, opacity: float):
        if not text:
            return
        font = QFont()
        font.setFamilies(["Inter", "Noto Sans SC Medium", "Microsoft YaHei UI"])
        font.setPixelSize(10)
        font.setWeight(QFont.DemiBold)
        fm = QFontMetricsF(font)
        tw = fm.horizontalAdvance(text)
        pw = tw + 12.0
        ph = 18.0
        # Clamp pill inside overlay bounds
        cx = max(pw / 2.0 + 6.0, min(self.width() - pw / 2.0 - 6.0, center.x()))
        cy = max(ph / 2.0 + 6.0, min(self.height() - ph / 2.0 - 6.0, center.y()))
        rect = QRectF(cx - pw / 2.0, cy - ph / 2.0, pw, ph)

        path = QPainterPath()
        path.addRoundedRect(rect, 9.0, 9.0)
        painter.fillPath(path, QColor(11, 17, 32, int(218 * opacity)))
        border = QColor(accent)
        border.setAlpha(int(175 * opacity))
        painter.setPen(QPen(border, 1.0))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)

        painter.setFont(font)
        painter.setPen(QColor(248, 250, 255, int(245 * opacity)))
        painter.drawText(rect, Qt.AlignCenter, text)

    def paintEvent(self, event):
        res = self._result
        if res is None or not res.has_snap or self._alpha <= 0.01:
            return

        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)

        ox = self.geometry().x()
        oy = self.geometry().y()
        op = self._alpha
        c1, c_mid, c2 = self._theme_provider()

        # 1. Magnetic Snap Alignment Preview Frame around the snapped target geometry
        sr = res.snapped_rect.translated(-ox, -oy)
        sr_f = QRectF(sr.x() + 0.5, sr.y() + 0.5, sr.width() - 1.0, sr.height() - 1.0)
        frame_path = QPainterPath()
        frame_path.addRoundedRect(sr_f, self._preview_radius, self._preview_radius)

        # Soft outer aurora halo
        halo_col = QColor(c1)
        halo_col.setAlpha(int(58 * op))
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(halo_col, 4.5))
        painter.drawPath(frame_path)

        # Subtle frosted tint fill inside the preview footprint
        fill_grad = QLinearGradient(sr_f.topLeft(), sr_f.bottomRight())
        fc1 = QColor(c1); fc1.setAlpha(int(26 * op))
        fc2 = QColor(c2); fc2.setAlpha(int(18 * op))
        fill_grad.setColorAt(0.0, fc1)
        fill_grad.setColorAt(1.0, fc2)
        painter.fillPath(frame_path, fill_grad)

        # Crisp 1.4px glowing gradient outline
        b_grad = QLinearGradient(sr_f.topLeft(), sr_f.bottomRight())
        bc1 = QColor(c1); bc1.setAlpha(int(235 * op))
        bcm = QColor(c_mid); bcm.setAlpha(int(220 * op))
        bc2 = QColor(c2); bc2.setAlpha(int(235 * op))
        b_grad.setColorAt(0.0, bc1)
        b_grad.setColorAt(0.5, bcm)
        b_grad.setColorAt(1.0, bc2)
        painter.setPen(QPen(QBrush(b_grad), 1.5))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(frame_path)

        # 2. Smart Guide Lines
        for g in res.guides:
            is_center = g.kind == "screen_center"
            is_margin = g.kind == "screen_margin"
            accent = c2 if is_center else c1

            if g.orientation == "v":
                p1 = QPointF(g.coord - ox + 0.5, float(g.start - oy))
                p2 = QPointF(g.coord - ox + 0.5, float(g.end - oy))
            else:
                p1 = QPointF(float(g.start - ox), g.coord - oy + 0.5)
                p2 = QPointF(float(g.end - ox), g.coord - oy + 0.5)

            # Soft glow backing so lines stay legible on bright and dark wallpapers
            glow = QColor(accent)
            glow.setAlpha(int((60 if is_center else 50) * op))
            painter.setPen(QPen(glow, 3.5, Qt.SolidLine, Qt.RoundCap))
            painter.drawLine(p1, p2)

            # Dark contrast hairline + crisp glowing core line
            line_style = Qt.DashLine if (is_center or is_margin) else Qt.SolidLine
            core = QColor(accent).lighter(128)
            core.setAlpha(int((225 if not is_margin else 185) * op))
            pen = QPen(core, 1.15, line_style, Qt.RoundCap)
            if line_style == Qt.DashLine:
                pen.setDashPattern([5.0, 4.0])
            painter.setPen(pen)
            painter.drawLine(p1, p2)

            # Anchor dots at alignment contact points
            dot_col = QColor(255, 255, 255, int(235 * op))
            ring_col = QColor(accent)
            ring_col.setAlpha(int(220 * op))
            painter.setBrush(dot_col)
            painter.setPen(QPen(ring_col, 1.2))
            for ax, ay in g.anchors:
                painter.drawEllipse(QPointF(ax - ox + 0.5, ay - oy + 0.5), 2.6, 2.6)

            # Optional pill label for screen center / safe margin
            if g.label:
                if g.orientation == "v":
                    ly = sr_f.top() - 16.0 if sr_f.top() > 36.0 else sr_f.bottom() + 16.0
                    self._draw_pill(painter, QPointF(g.coord - ox + 0.5, ly), g.label, accent, op)
                else:
                    lx = sr_f.right() + 36.0 if sr_f.right() + 72.0 < self.width() else sr_f.left() - 36.0
                    self._draw_pill(painter, QPointF(lx, g.coord - oy + 0.5), g.label, accent, op)

        # 3. Spacing / Gap Measurement Callouts
        for gap in res.gaps:
            gp1 = QPointF(gap.p1[0] - ox + 0.5, gap.p1[1] - oy + 0.5)
            gp2 = QPointF(gap.p2[0] - ox + 0.5, gap.p2[1] - oy + 0.5)
            base_c = c2 if gap.equal else c_mid
            if gap.equal:
                glow_g = QColor(base_c)
                glow_g.setAlpha(int(75 * op))
                painter.setPen(QPen(glow_g, 4.0, Qt.SolidLine, Qt.RoundCap))
                painter.drawLine(gp1, gp2)
            col = QColor(base_c).lighter(132 if gap.equal else 125)
            col.setAlpha(int(240 * op))
            painter.setPen(QPen(col, 1.35 if gap.equal else 1.25))
            painter.drawLine(gp1, gp2)

            # End-cap ticks
            tick = 5.0 if gap.equal else 4.0
            if gap.orientation == "v":
                painter.drawLine(QPointF(gp1.x() - tick, gp1.y()), QPointF(gp1.x() + tick, gp1.y()))
                painter.drawLine(QPointF(gp2.x() - tick, gp2.y()), QPointF(gp2.x() + tick, gp2.y()))
                pill_pt = QPointF(gp1.x() + 28.0, (gp1.y() + gp2.y()) / 2.0)
            else:
                painter.drawLine(QPointF(gp1.x(), gp1.y() - tick), QPointF(gp1.x(), gp1.y() + tick))
                painter.drawLine(QPointF(gp2.x(), gp2.y() - tick), QPointF(gp2.x(), gp2.y() + tick))
                pill_pt = QPointF((gp1.x() + gp2.x()) / 2.0, gp1.y() - 16.0)

            pill_text = f"≡ {gap.label}" if gap.equal else gap.label
            self._draw_pill(painter, pill_pt, pill_text, base_c, op)


class SmartGuideManager:
    """Coordinates live Smart Guides and magnetic snapping across all desktop widgets."""

    def __init__(
        self,
        widgets_provider: Callable[[], list[QWidget]],
        theme_provider: Callable[[], tuple[QColor, QColor, QColor]],
        enabled_provider: Callable[[], bool] | None = None,
        margin_x: int = 24,
        margin_y: int = 24,
        card_gap: int = 10,
        col_gap: int = 14,
        snap_threshold: int = 10,
    ):
        self._widgets_provider = widgets_provider
        self._theme_provider = theme_provider
        self._enabled_provider = enabled_provider or (lambda: True)
        self.margin_x = margin_x
        self.margin_y = margin_y
        self.card_gap = card_gap
        self.col_gap = col_gap
        self.snap_threshold = snap_threshold

        self._overlay = SmartGuideOverlay(theme_provider=theme_provider)
        self._active_widget: QWidget | None = None
        self._cached_peers: list[QRect] = []

    def begin_drag(self, widget: QWidget):
        self._active_widget = widget
        peers: list[QRect] = []
        for w in self._widgets_provider():
            if w is None or w is widget or not w.isVisible():
                continue
            peers.append(w.frameGeometry())
        self._cached_peers = peers

    def snap_move(
        self,
        widget: QWidget,
        raw_pos: QPoint,
        modifiers: Qt.KeyboardModifiers = Qt.NoModifier,
        preview_radius: float = 14.0,
    ) -> QPoint:
        if not self._enabled_provider():
            self._overlay.fade_out()
            return raw_pos

        if self._active_widget is not widget:
            self.begin_drag(widget)

        bypass = bool(modifiers & Qt.AltModifier)
        raw_rect = QRect(raw_pos, widget.size())
        center = raw_rect.center()
        screen = QGuiApplication.screenAt(center) or QGuiApplication.primaryScreen()
        if not screen:
            return raw_pos

        sc_geom = screen.geometry()
        sc_avail = screen.availableGeometry()
        all_avail = [s.availableGeometry() for s in QGuiApplication.screens()]
        # Only snap against peers on the same screen so multi-monitor drags stay crisp
        local_peers = [pr for pr in self._cached_peers if sc_geom.intersects(pr)]

        res = compute_smart_snap(
            raw_rect=raw_rect,
            screen_avail=sc_avail,
            peer_rects=local_peers,
            snap_threshold=self.snap_threshold,
            margin_x=self.margin_x,
            margin_y=self.margin_y,
            card_gap=self.card_gap,
            col_gap=self.col_gap,
            bypass=bypass,
            clamp_bounds=True,
            all_screens_avail=all_avail,
        )
        self._overlay.show_snap(sc_geom, res, radius=preview_radius)
        return res.snapped_pos

    def end_drag(self, widget: QWidget | None = None, immediate: bool = False):
        if widget is None or self._active_widget is widget:
            self._active_widget = None
            self._cached_peers.clear()
            if immediate:
                self._overlay._fade_anim.stop()
                self._overlay._result = None
                self._overlay._alpha = 0.0
                self._overlay._hiding = False
                self._overlay.hide()
            else:
                self._overlay.fade_out()

    def close(self):
        self._active_widget = None
        self._cached_peers.clear()
        self._overlay.close()
