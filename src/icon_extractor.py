import ctypes
from ctypes import wintypes
import hashlib
import os
from pathlib import Path
import win32com.client
from PySide6.QtCore import QFileInfo, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QFileIconProvider

from paths import CACHE_DIR, CUSTOM_ICONS_DIR, GROUPS_DIR

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


class SHQUERYRBINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("i64Size", ctypes.c_int64),
        ("i64NumItems", ctypes.c_int64),
    ]


shell32.SHQueryRecycleBinW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(SHQUERYRBINFO)]
shell32.SHQueryRecycleBinW.restype = ctypes.c_long


def query_recycle_bin_state() -> tuple[bool, int, int]:
    """Return (has_items, item_count, total_bytes) for the Windows Recycle Bin."""
    info = SHQUERYRBINFO()
    info.cbSize = ctypes.sizeof(SHQUERYRBINFO)
    hr = shell32.SHQueryRecycleBinW(None, ctypes.byref(info))
    if hr == 0:
        cnt = max(0, int(info.i64NumItems))
        sz = max(0, int(info.i64Size))
        return (cnt > 0 or sz > 0), cnt, sz
    return False, 0, 0


def is_recycle_bin_item(item_path: Path) -> bool:
    if item_path.stem.lower() in ("回收站", "recycle bin"):
        return True
    if item_path.suffix.lower() == ".lnk":
        try:
            shell = win32com.client.Dispatch("WScript.Shell")
            sc = shell.CreateShortcut(str(item_path))
            if "645ff040-5081-101b-9f08-00aa002f954e" in (sc.Arguments or "").lower():
                return True
        except Exception:
            pass
    return False

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


def item_rel_key(item_path: Path) -> str:
    """Normalized relative key under GROUPS_DIR (e.g. '01_ai_capsule/claude.lnk')."""
    try:
        rel = item_path.resolve().relative_to(GROUPS_DIR.resolve())
        return rel.as_posix().lower()
    except Exception:
        return item_path.name.lower()


class ShortcutIconLoader:
    """High-DPI crisp shortcut icon extractor with custom icon overrides and persistent PNG cache."""

    def __init__(self, custom_icons: dict[str, str] | None = None):
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        CUSTOM_ICONS_DIR.mkdir(parents=True, exist_ok=True)
        self._provider = QFileIconProvider()
        try:
            self._shell = win32com.client.Dispatch("WScript.Shell")
        except Exception:
            self._shell = None
        self._mem_cache: dict[str, QPixmap] = {}
        self._custom_icons: dict[str, str] = {k.lower(): v for k, v in (custom_icons or {}).items()}

    def set_custom_icons(self, custom_icons: dict[str, str]):
        self._custom_icons = {k.lower(): v for k, v in (custom_icons or {}).items()}
        self._mem_cache.clear()

    def has_custom_icon(self, item_path: Path) -> bool:
        rel = item_rel_key(item_path)
        fname = self._custom_icons.get(rel)
        return bool(fname and (CUSTOM_ICONS_DIR / fname).exists())

    def import_custom_icon(self, src_file: Path) -> str | None:
        """Convert any image (.png/.ico/.jpg/.webp/.bmp/.svg) or binary (.exe/.dll) into a 128px PNG in CUSTOM_ICONS_DIR."""
        if not src_file.exists():
            return None
        CUSTOM_ICONS_DIR.mkdir(parents=True, exist_ok=True)
        ext = src_file.suffix.lower()
        pm = QPixmap()

        if ext in (".exe", ".dll"):
            pm = _extract_hicon_to_pixmap(str(src_file), 0, 128)
            if pm.isNull():
                pm = _shgetfileinfo_pixmap(str(src_file))
        elif ext == ".ico":
            pm = _extract_hicon_to_pixmap(str(src_file), 0, 128)
            if pm.isNull():
                pm = QIcon(str(src_file)).pixmap(128, 128)
        elif ext == ".lnk":
            pm = self._extract_fresh(src_file)
        else:
            img = QImage(str(src_file))
            if not img.isNull():
                # Keep alpha if transparent icon; gently round corners if full-bleed opaque photo
                if not img.hasAlphaChannel() and ext in (".jpg", ".jpeg", ".bmp"):
                    pm = _render_rounded_image_thumbnail(str(src_file), 128)
                else:
                    canvas = QPixmap(128, 128)
                    canvas.fill(Qt.transparent)
                    scaled = QPixmap.fromImage(img).scaled(120, 120, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    painter = QPainter(canvas)
                    painter.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
                    painter.drawPixmap((128 - scaled.width()) // 2, (128 - scaled.height()) // 2, scaled)
                    painter.end()
                    pm = canvas
            else:
                pm = QIcon(str(src_file)).pixmap(128, 128)

        if pm.isNull():
            return None

        try:
            mtime = int(src_file.stat().st_mtime_ns)
        except OSError:
            mtime = 0
        digest = hashlib.md5(f"{src_file}:{mtime}".encode("utf-8")).hexdigest()[:14]
        out_name = f"custom_{digest}.png"
        out_path = CUSTOM_ICONS_DIR / out_name
        if not pm.save(str(out_path), "PNG"):
            return None
        return out_name

    def invalidate(self, item_path: Path | None = None, clear_disk_cache: bool = False):
        if item_path is not None:
            prefix = f"{str(item_path).lower()}:"
            for k in [k for k in self._mem_cache if k.startswith(prefix)]:
                self._mem_cache.pop(k, None)
        else:
            self._mem_cache.clear()
        if clear_disk_cache and CACHE_DIR.exists():
            for f in CACHE_DIR.glob("*.png"):
                try:
                    f.unlink()
                except OSError:
                    pass

    def get_icon_pixmap(self, item_path: Path, size: int = 64) -> QPixmap:
        rel = item_rel_key(item_path)
        custom_fname = self._custom_icons.get(rel, "")
        custom_path = (CUSTOM_ICONS_DIR / custom_fname) if custom_fname else None
        has_custom = bool(custom_path and custom_path.exists())

        cache_key = f"{str(item_path).lower()}:{size}:{custom_fname if has_custom else ''}"
        if cache_key in self._mem_cache:
            return self._mem_cache[cache_key]

        if has_custom and custom_path is not None:
            pm = QPixmap(str(custom_path))
            if not pm.isNull():
                scaled = pm.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self._mem_cache[cache_key] = scaled
                return scaled

        # Live empty / full icon state for Recycle Bin shortcuts (unless user set a custom icon)
        if is_recycle_bin_item(item_path):
            has_items, _, _ = query_recycle_bin_state()
            rb_key = f"__recycle_bin__:{'full' if has_items else 'empty'}:{size}"
            if rb_key in self._mem_cache:
                return self._mem_cache[rb_key]
            res_id = -54 if has_items else -55
            pm = _extract_hicon_to_pixmap(r"C:\Windows\System32\imageres.dll", res_id, 128)
            if not pm.isNull():
                scaled = pm.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self._mem_cache[rb_key] = scaled
                return scaled

        try:
            mtime = int(item_path.stat().st_mtime)
        except OSError:
            mtime = 0

        digest = hashlib.md5(f"{str(item_path).lower()}:{mtime}".encode("utf-8")).hexdigest()[:16]
        cache_file = CACHE_DIR / f"{digest}.png"

        if cache_file.exists():
            pm = QPixmap(str(cache_file))
            if not pm.isNull():
                scaled = pm.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self._mem_cache[cache_key] = scaled
                return scaled

        pm = self._extract_fresh(item_path)
        if not pm.isNull():
            pm.save(str(cache_file), "PNG")
            scaled = pm.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self._mem_cache[cache_key] = scaled
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
