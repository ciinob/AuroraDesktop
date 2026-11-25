import ctypes
from ctypes import wintypes
import hashlib
import os
from pathlib import Path
import win32com.client
from PySide6.QtCore import QFileInfo, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QFileIconProvider

from paths import CACHE_DIR

user32 = ctypes.windll.user32
shell32 = ctypes.windll.shell32

user32.PrivateExtractIconsW.argtypes = [
    wintypes.LPCWSTR, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    ctypes.POINTER(wintypes.HICON), ctypes.POINTER(wintypes.UINT),
    wintypes.UINT, wintypes.UINT,
]
user32.PrivateExtractIconsW.restype = wintypes.UINT

user32.DestroyIcon.argtypes = [wintypes.HICON]
user32.DestroyIcon.restype = wintypes.BOOL


class SHFILEINFOW(ctypes.Structure):
    _fields_ = [
        ("hIcon", wintypes.HICON),
        ("iIcon", ctypes.c_int),
        ("dwAttributes", wintypes.DWORD),
        ("szDisplayName", wintypes.WCHAR * 260),
        ("szTypeName", wintypes.WCHAR * 80),
    ]


shell32.SHGetFileInfoW.argtypes = [
    wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(SHFILEINFOW),
    wintypes.UINT, wintypes.UINT,
]
shell32.SHGetFileInfoW.restype = ctypes.c_size_t

SHGFI_ICON = 0x000000100
SHGFI_LARGEICON = 0x000000000

# Clean concise display name aliases for long desktop shortcut names
CLEAN_NAME_MAP = {
    "plain craft launcher 2 - 快捷方式": "PCL 2",
    "plain craft launcher 2": "PCL 2",
    "deepseek harness": "DeepSeek",
    "visual studio code": "VS Code",
    "rockstar games launcher": "Rockstar",
    "matlab r2025b": "MATLAB",
    "microsoft edge": "Edge",
    "logitech g hub": "G HUB",
    "inzone hub": "INZONE",
    "wps office": "WPS",
    "clash verge": "Clash Verge",
    "aria2 下载器": "Aria2",
    "libretv 影视站": "LibreTV",
    "完美世界竞技平台": "完美竞技",
    "外星仔加速器": "外星仔加速",
    "外星仔联机助手": "外星仔联机",
    "火绒安全软件": "火绒安全",
    "剪映专业版": "剪映",
}


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}


def _render_rounded_image_thumbnail(img_path: str, size: int = 128) -> QPixmap:
    """Render macOS Finder style rounded-square photo thumbnail with subtle glass border."""
    src = QImage(img_path)
    if src.isNull():
        return QPixmap()

    out = QPixmap(size, size)
    out.fill(Qt.transparent)

    margin = 6
    box = size - margin * 2
    scaled = QPixmap.fromImage(src).scaled(box, box, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    # Center crop to square
    sx = max(0, (scaled.width() - box) // 2)
    sy = max(0, (scaled.height() - box) // 2)
    cropped = scaled.copy(sx, sy, box, box)

    painter = QPainter(out)
    painter.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
    rect = QRectF(float(margin), float(margin), float(box), float(box))
    radius = size * 0.18

    clip = QPainterPath()
    clip.addRoundedRect(rect, radius, radius)
    painter.setClipPath(clip)
    painter.drawPixmap(int(margin), int(margin), cropped)

    painter.setClipping(False)
    painter.setPen(QPen(QColor(255, 255, 255, 85), 2.0))
    painter.setBrush(Qt.NoBrush)
    painter.drawRoundedRect(rect, radius, radius)
    painter.end()
    return out


def format_display_name(file_path: Path) -> tuple[str, str]:
    """Return (short_display_name, full_tooltip_name)."""
    if file_path.is_dir():
        return file_path.name, file_path.name

    raw = file_path.name
    for suffix in (".lnk", ".url"):
        if raw.lower().endswith(suffix):
            raw = raw[: -len(suffix)]
            break
    # Strip .exe/.bat/.cmd extension for apps, but keep .pdf/.png/.docx etc. for documents/files!
    for app_ext in (".exe", ".bat", ".cmd"):
        if raw.lower().endswith(app_ext):
            raw = raw[: -len(app_ext)]
            break

    for suffix in (" - 快捷方式", " - Shortcut"):
        if raw.endswith(suffix):
            raw = raw[: -len(suffix)].strip()

    short = CLEAN_NAME_MAP.get(raw.lower(), raw)
    return short, raw


def _extract_hicon_to_pixmap(source_path: str, icon_index: int = 0, desired_size: int = 128) -> QPixmap:
    if not source_path or not os.path.exists(source_path):
        return QPixmap()

    hicon = wintypes.HICON(0)
    icon_id = wintypes.UINT(0)
    count = user32.PrivateExtractIconsW(
        source_path,
        icon_index,
        desired_size,
        desired_size,
        ctypes.byref(hicon),
        ctypes.byref(icon_id),
        1,
        0,
    )
    if count > 0 and hicon.value:
        img = QImage.fromHICON(hicon.value)
        user32.DestroyIcon(hicon)
        if not img.isNull():
            return QPixmap.fromImage(img)
    return QPixmap()


def _shgetfileinfo_pixmap(target_path: str) -> QPixmap:
    if not target_path or not os.path.exists(target_path):
        return QPixmap()
    sfi = SHFILEINFOW()
    res = shell32.SHGetFileInfoW(
        target_path, 0, ctypes.byref(sfi), ctypes.sizeof(sfi), SHGFI_ICON | SHGFI_LARGEICON
    )
    if res and sfi.hIcon:
        img = QImage.fromHICON(sfi.hIcon)
        user32.DestroyIcon(sfi.hIcon)
        if not img.isNull():
            return QPixmap.fromImage(img)
    return QPixmap()


class ShortcutIconLoader:
    """High-DPI crisp shortcut icon extractor with persistent PNG cache and zero shortcut-arrow clutter."""

    def __init__(self):
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self._provider = QFileIconProvider()
        try:
            self._shell = win32com.client.Dispatch("WScript.Shell")
        except Exception:
            self._shell = None
        self._mem_cache: dict[str, QPixmap] = {}

    def get_icon_pixmap(self, item_path: Path, size: int = 64) -> QPixmap:
        key = str(item_path).lower()
        if key in self._mem_cache:
            return self._mem_cache[key]

        try:
            mtime = int(item_path.stat().st_mtime)
        except OSError:
            mtime = 0

        digest = hashlib.md5(f"{key}:{mtime}".encode("utf-8")).hexdigest()[:16]
        cache_file = CACHE_DIR / f"{digest}.png"

        if cache_file.exists():
            pm = QPixmap(str(cache_file))
            if not pm.isNull():
                scaled = pm.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self._mem_cache[key] = scaled
                return scaled

        pm = self._extract_fresh(item_path)
        if not pm.isNull():
            pm.save(str(cache_file), "PNG")
            scaled = pm.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self._mem_cache[key] = scaled
            return scaled

        return QPixmap()

    def resolve_target_path(self, item_path: Path) -> str:
        if item_path.suffix.lower() == ".lnk" and self._shell is not None:
            try:
                sc = self._shell.CreateShortcut(str(item_path))
                if sc.TargetPath:
                    return os.path.expandvars(sc.TargetPath)
            except Exception:
                pass
        return str(item_path)

    def _extract_fresh(self, item_path: Path) -> QPixmap:
        # 0. Direct image file -> render macOS-style rounded photo thumbnail!
        if item_path.is_file() and item_path.suffix.lower() in IMAGE_EXTENSIONS:
            thumb = _render_rounded_image_thumbnail(str(item_path), 128)
            if not thumb.isNull():
                return thumb

        # 1. Inspect .lnk IconLocation and TargetPath to get arrow-free high-res icon or image thumbnail
        if item_path.suffix.lower() == ".lnk" and self._shell is not None:
            try:
                sc = self._shell.CreateShortcut(str(item_path))
                icon_loc = os.path.expandvars(sc.IconLocation or "").strip()
                target = os.path.expandvars(sc.TargetPath or "").strip()

                if target and os.path.exists(target):
                    target_ext = os.path.splitext(target)[1].lower()
                    if target_ext in IMAGE_EXTENSIONS:
                        thumb = _render_rounded_image_thumbnail(target, 128)
                        if not thumb.isNull():
                            return thumb

                if icon_loc and icon_loc != ",0":
                    if "," in icon_loc:
                        loc_path, idx_str = icon_loc.rsplit(",", 1)
                        loc_path = loc_path.strip().strip('"')
                        try:
                            idx = int(idx_str.strip())
                        except ValueError:
                            idx = 0
                    else:
                        loc_path, idx = icon_loc.strip('"'), 0

                    if loc_path and os.path.exists(loc_path):
                        ext = os.path.splitext(loc_path)[1].lower()
                        if ext in (".ico", ".png", ".bmp", ".jpg"):
                            qicon = QIcon(loc_path)
                            pm = qicon.pixmap(128, 128)
                            if not pm.isNull():
                                return pm
                        pm = _extract_hicon_to_pixmap(loc_path, idx, 128)
                        if not pm.isNull():
                            return pm

                if target and os.path.exists(target):
                    pm = _extract_hicon_to_pixmap(target, 0, 128)
                    if not pm.isNull():
                        return pm
                    pm = _shgetfileinfo_pixmap(target)
                    if not pm.isNull():
                        return pm
                    icon = self._provider.icon(QFileInfo(target))
                    pm = icon.pixmap(128, 128)
                    if not pm.isNull():
                        return pm
            except Exception:
                pass

        # 2. Direct file (.pdf, .docx, .txt, .zip, etc.) or folder -> shell / Qt icon provider
        icon = self._provider.icon(QFileInfo(str(item_path)))
        pm = icon.pixmap(128, 128)
        if not pm.isNull():
            return pm

        return _shgetfileinfo_pixmap(str(item_path))
