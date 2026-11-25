# -*- coding: utf-8 -*-
"""Lightweight GitHub release check for the tray menu.

Uses only the standard library: QtNetwork is deliberately excluded from the
PyInstaller build, and the request runs on a worker thread so the UI never
blocks. Signals are delivered to the main thread via Qt's auto connection.
"""
import json
import re
import threading
import urllib.request

from PySide6.QtCore import QObject, Signal


RELEASES_API = "https://api.github.com/repos/ciinob/AuroraDesktop/releases/latest"
RELEASES_PAGE = "https://github.com/ciinob/AuroraDesktop/releases/latest"

_VERSION_RE = re.compile(r"^\s*v?(\d+)\.(\d+)(?:\.(\d+))?(?:-([0-9A-Za-z.-]+))?")


def parse_version(tag: str) -> tuple[int, int, int, int, tuple]:
    """Parse a release tag into a sortable tuple.

    Supports ``v1.2``, ``v1.2.3``, and prerelease suffixes like ``v1.2.3-beta.1``.
    A final release sorts higher than a prerelease of the same version number.
    """
    m = _VERSION_RE.match(tag or "")
    if not m:
        return (0, 0, 0, 0, ())
    major = int(m.group(1))
    minor = int(m.group(2))
    patch = int(m.group(3) or 0)
    pre = m.group(4)
    if not pre:
        return (major, minor, patch, 1, ())
    pre_parts = tuple((0, int(p)) if p.isdigit() else (1, p.lower()) for p in pre.split("."))
    return (major, minor, patch, 0, pre_parts)


class UpdateChecker(QObject):
    checkStarted = Signal()
    checkFinished = Signal()
    updateFound = Signal(str, str)  # tag, release page url
    upToDate = Signal()
    checkFailed = Signal(str)

    def __init__(self, current_version: str, parent=None):
        super().__init__(parent)
        self.current_version = current_version
        self._lock = threading.Lock()
        self._checking = False

    def check(self):
        with self._lock:
            if self._checking:
                return
            self._checking = True
        self.checkStarted.emit()
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self):
        try:
            req = urllib.request.Request(
                RELEASES_API,
                headers={"User-Agent": "AuroraDesktop", "Accept": "application/vnd.github+json"},
            )
            with urllib.request.urlopen(req, timeout=6) as resp:
                data = json.load(resp)
            tag = data.get("tag_name", "")
            url = data.get("html_url") or RELEASES_PAGE
            if parse_version(tag) > parse_version(self.current_version):
                self.updateFound.emit(tag, url)
            else:
                self.upToDate.emit()
        except Exception as exc:  # network errors must never disturb the desktop
            self.checkFailed.emit(str(exc))
        finally:
            with self._lock:
                self._checking = False
            self.checkFinished.emit()
