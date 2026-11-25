import ctypes
import time
from PySide6.QtCore import QEasingCurve, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication

winmm = ctypes.windll.winmm


class _HighRefreshTicker(QObject):
    """Shared VSync-matched high-refresh-rate animation driver (supports 144Hz / 165Hz / 240Hz+ monitors)."""

    def __init__(self):
        super().__init__()
        self._active: list["HighRefreshAnimation"] = []
        self._period_active = False
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.timeout.connect(self._tick)
        self._update_interval()

    def _update_interval(self):
        max_hz = 120.0
        for s in QGuiApplication.screens():
            hz = s.refreshRate()
            if hz > max_hz:
                max_hz = hz
        # e.g. 240Hz -> 4ms PreciseTimer (~250 ticks/sec with exact perf_counter interpolation)
        interval_ms = max(3, int(round(1000.0 / min(max_hz, 260.0))))
        self._timer.setInterval(interval_ms)

    def register(self, anim: "HighRefreshAnimation"):
        if anim not in self._active:
            if not self._active:
                self._update_interval()
                if not self._period_active:
                    winmm.timeBeginPeriod(1)
                    self._period_active = True
                self._timer.start()
            self._active.append(anim)

    def unregister(self, anim: "HighRefreshAnimation"):
        if anim in self._active:
            self._active.remove(anim)
            if not self._active:
                self._timer.stop()
                if self._period_active:
                    winmm.timeEndPeriod(1)
                    self._period_active = False

    def _tick(self):
        now = time.perf_counter()
        for anim in list(self._active):
            anim._step(now)


_GLOBAL_TICKER: _HighRefreshTicker | None = None


def _get_ticker() -> _HighRefreshTicker:
    global _GLOBAL_TICKER
    if _GLOBAL_TICKER is None:
        _GLOBAL_TICKER = _HighRefreshTicker()
    return _GLOBAL_TICKER


class HighRefreshAnimation(QObject):
    """Drop-in 240Hz replacement for QVariantAnimation (bypasses Qt's hardcoded 60Hz 16ms timer cap)."""
    valueChanged = Signal(float)
    finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._duration_sec = 0.20
        self._start_val = 0.0
        self._end_val = 1.0
        self._start_time = 0.0
        self._running = False
        self._easing = QEasingCurve(QEasingCurve.OutQuart)

    def setDuration(self, ms: int):
        self._duration_sec = max(0.016, ms / 1000.0)

    def setEasingCurve(self, curve):
        self._easing = QEasingCurve(curve)

    def setStartValue(self, val: float):
        self._start_val = float(val)

    def setEndValue(self, val: float):
        self._end_val = float(val)

    def isRunning(self) -> bool:
        return self._running

    def start(self):
        self._start_time = time.perf_counter()
        self._running = True
        _get_ticker().register(self)

    def stop(self):
        if self._running:
            self._running = False
            _get_ticker().unregister(self)

    def _step(self, now: float):
        if not self._running:
            return
        t = (now - self._start_time) / self._duration_sec
        if t >= 1.0:
            self.stop()
            self.valueChanged.emit(self._end_val)
            self.finished.emit()
        else:
            eased = self._easing.valueForProgress(max(0.0, t))
            current = self._start_val + (self._end_val - self._start_val) * eased
            self.valueChanged.emit(current)
