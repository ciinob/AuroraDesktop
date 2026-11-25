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


def parse_version(tag: str) -> tuple[int, int, int]:
    m = re.match(r"v?(\d+)\.(\d+)\.(\d+)", tag or "")
    return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)


class UpdateChecker(QObject):
    updateFound = Signal(str, str)  # tag, release page url
    upToDate = Signal()
    checkFailed = Signal(str)

    def __init__(self, current_version: str, parent=None):
        super().__init__(parent)
        self.current_version = current_version

    def check(self):
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
