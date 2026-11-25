# -*- coding: utf-8 -*-
"""Lightweight GitHub release check with zero-rate-limit fallback.

Tries the GitHub REST API first, and if rate-limited (HTTP 403/429 on shared/proxy
IPs) automatically falls back to resolving the HTTP redirect of `/releases/latest`
to `/releases/tag/vX.Y.Z`, which has no API rate limit.
"""
import json
import re
import threading
import urllib.error
import urllib.request

from PySide6.QtCore import QObject, Signal


RELEASES_API = "https://api.github.com/repos/ciinob/AuroraDesktop/releases/latest"
RELEASES_PAGE = "https://github.com/ciinob/AuroraDesktop/releases/latest"

_VERSION_RE = re.compile(r"^\s*v?(\d+)\.(\d+)(?:\.(\d+))?(?:-([0-9A-Za-z.-]+))?")


def parse_version(tag: str) -> tuple[int, int, int, int, tuple]:
    """Parse a release tag into a sortable tuple."""
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


def _fetch_latest_release() -> tuple[str, str]:
    """Return (tag_name, html_url) via GitHub API, falling back to web redirect on 403/429."""
    try:
        req = urllib.request.Request(
            RELEASES_API,
            headers={"User-Agent": "AuroraDesktop", "Accept": "application/vnd.github+json"},
        )
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.load(resp)
        tag = (data.get("tag_name") or "").strip()
        url = (data.get("html_url") or RELEASES_PAGE).strip()
        if tag:
            return tag, url
    except urllib.error.HTTPError as exc:
        if exc.code not in (403, 429):
            raise
    except Exception:
        pass

    # Fallback: GitHub web `/releases/latest` 302-redirects to `/releases/tag/<tag>` without API rate limits
    req_web = urllib.request.Request(
        RELEASES_PAGE,
        headers={"User-Agent": "Mozilla/5.0 AuroraDesktop"},
    )
    with urllib.request.urlopen(req_web, timeout=8) as resp:
        final_url = resp.geturl() or RELEASES_PAGE
    if "/releases/tag/" in final_url:
        tag = final_url.rsplit("/releases/tag/", 1)[1].split("?", 1)[0].strip("/")
        return tag, final_url
    return "", final_url


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
            tag, url = _fetch_latest_release()
            if tag and parse_version(tag) > parse_version(self.current_version):
                self.updateFound.emit(tag, url)
            else:
                self.upToDate.emit()
        except Exception as exc:
            self.checkFailed.emit(str(exc))
        finally:
            with self._lock:
                self._checking = False
            self.checkFinished.emit()
