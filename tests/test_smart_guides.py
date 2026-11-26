# -*- coding: utf-8 -*-
"""Unit & headless Qt smoke tests for Smart Guides & Magnetic Snap Preview."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QWidget

from smart_guides import SmartGuideManager, SmartGuideOverlay, clamp_rect_to_screen, compute_smart_snap
from widgets import AuroraBaseWindow


class TestComputeSmartSnap(unittest.TestCase):
    def setUp(self):
        self.screen = QRect(0, 0, 1920, 1040)

    def test_screen_left_and_top_margin_snap(self):
        raw = QRect(29, 19, 368, 66)
        res = compute_smart_snap(raw, self.screen, [])
        self.assertTrue(res.snapped_x)
        self.assertTrue(res.snapped_y)
        self.assertEqual(res.snapped_pos, QPoint(24, 24))
        kinds = {g.kind for g in res.guides}
        self.assertIn("screen_margin", kinds)

    def test_screen_center_snap(self):
        # Clock width 360 -> horizontal center at x = (1920 - 360) / 2 = 780
        raw = QRect(785, 50, 360, 165)
        res = compute_smart_snap(raw, self.screen, [])
        self.assertTrue(res.snapped_x)
        self.assertFalse(res.snapped_y)
        self.assertEqual(res.snapped_pos.x(), 780)
        self.assertTrue(any(g.kind == "screen_center" and g.orientation == "v" for g in res.guides))

    def test_peer_left_edge_and_vertical_card_gap(self):
        peer = QRect(100, 100, 368, 66)  # bottom = 166; +10px gap = 176
        raw = QRect(104, 181, 368, 120)
        res = compute_smart_snap(raw, self.screen, [peer])
        self.assertTrue(res.snapped_x)
        self.assertTrue(res.snapped_y)
        self.assertEqual(res.snapped_pos, QPoint(100, 176))
        self.assertTrue(any(g.kind == "peer" and g.orientation == "v" for g in res.guides))
        self.assertTrue(any(gap.orientation == "v" and gap.label == "10px" for gap in res.gaps))

    def test_peer_horizontal_col_gap(self):
        peer = QRect(24, 100, 368, 180)  # right = 392; +14px col_gap = 406
        raw = QRect(411, 103, 368, 180)
        res = compute_smart_snap(raw, self.screen, [peer])
        self.assertEqual(res.snapped_pos, QPoint(406, 100))
        self.assertTrue(any(gap.orientation == "h" and gap.label == "14px" for gap in res.gaps))

    def test_alt_bypass_disables_snap_and_guides(self):
        raw = QRect(26, 26, 368, 66)
        res = compute_smart_snap(raw, self.screen, [], bypass=True)
        self.assertFalse(res.has_snap)
        self.assertEqual(res.snapped_pos, QPoint(26, 26))
        self.assertEqual(res.guides, [])
        self.assertEqual(res.gaps, [])

    def test_multi_monitor_offset_coordinates(self):
        # Secondary monitor at x=1920..3840
        sec = QRect(1920, 0, 1920, 1040)
        raw = QRect(1920 + 28, 30, 360, 165)
        res = compute_smart_snap(raw, sec, [])
        self.assertEqual(res.snapped_pos, QPoint(1944, 24))

    def test_equal_spacing_vertical_trio(self):
        # Two cards separated by 36px (100..160 and 196..256); third card near 292 (256+36)
        p1 = QRect(100, 100, 368, 60)
        p2 = QRect(100, 196, 368, 60)
        raw = QRect(100, 297, 368, 60)
        res = compute_smart_snap(raw, self.screen, [p1, p2])
        self.assertEqual(res.snapped_pos.y(), 292)
        eq_gaps = [g for g in res.gaps if g.equal and g.orientation == "v"]
        self.assertEqual(len(eq_gaps), 2)
        self.assertTrue(all(g.label == "36px" for g in eq_gaps))

    def test_equal_spacing_centered_between_peers(self):
        # Peers at y=100..150 and y=350..400 (200px inner space); 60px card centered => 70px gaps => y=220
        p1 = QRect(100, 100, 368, 50)
        p2 = QRect(100, 350, 368, 50)
        raw = QRect(100, 224, 368, 60)
        res = compute_smart_snap(raw, self.screen, [p1, p2])
        self.assertEqual(res.snapped_pos.y(), 220)
        eq_gaps = [g for g in res.gaps if g.equal and g.orientation == "v"]
        self.assertEqual(len(eq_gaps), 2)

    def test_bounds_clamping_single_and_multi_monitor(self):
        # Single monitor: negative x/y clamped to (0, 0), bottom-right clamped inside screen
        clamped_tl = clamp_rect_to_screen(QRect(-50, -30, 368, 66), self.screen, [self.screen])
        self.assertEqual(clamped_tl, QPoint(0, 0))
        clamped_br = clamp_rect_to_screen(QRect(1800, 1020, 368, 66), self.screen, [self.screen])
        self.assertEqual(clamped_br, QPoint(1920 - 368, 1040 - 66))

        # Dual monitor side-by-side: right edge of primary is open for crossing, left edge stays clamped
        sec = QRect(1920, 0, 1920, 1040)
        cross = clamp_rect_to_screen(QRect(1800, 50, 368, 66), self.screen, [self.screen, sec])
        self.assertEqual(cross.x(), 1800)
        outer_left = clamp_rect_to_screen(QRect(-40, 50, 368, 66), self.screen, [self.screen, sec])
        self.assertEqual(outer_left.x(), 0)


class TestSmartGuideOverlayAndManager(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_drag_emits_position_changed_only_on_release(self):
        win = AuroraBaseWindow()
        win.setGeometry(50, 50, 368, 66)
        emits = []
        win.positionChangedByUser.connect(lambda: emits.append(1))
        win._begin_smart_drag(QPoint(60, 60))
        for dx in range(1, 20):
            win._move_smart_drag(QPoint(60 + dx * 5, 60 + dx * 2), Qt.NoModifier)
        self.assertEqual(len(emits), 0)
        win._end_smart_drag()
        self.assertEqual(len(emits), 1)
        win.close()

    def test_manager_lifecycle_and_paint(self):
        w1 = QWidget()
        w1.setGeometry(24, 24, 368, 66)
        w2 = QWidget()
        w2.setGeometry(24, 200, 368, 120)

        theme = lambda: (QColor("#2dd4bf"), QColor("#38bdf8"), QColor("#a855f7"))
        mgr = SmartGuideManager(lambda: [w1, w2], theme)
        mgr.begin_drag(w2)
        snapped = mgr.snap_move(w2, QPoint(28, 95), Qt.NoModifier)
        self.assertEqual(snapped.x(), 24)
        # Render overlay to a pixmap to ensure paintEvent executes without error
        pm = mgr._overlay.grab()
        self.assertFalse(pm.isNull())
        # Alt bypass
        raw_pt = QPoint(28, 95)
        bypassed = mgr.snap_move(w2, raw_pt, Qt.AltModifier)
        self.assertEqual(bypassed, raw_pt)
        mgr.end_drag(w2)
        mgr.close()


if __name__ == "__main__":
    unittest.main()
