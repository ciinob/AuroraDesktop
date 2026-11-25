import os
import sys
from pathlib import Path


APP_VERSION = "1.1.1"


def get_bundle_dir() -> Path:
    """Directory containing bundled read-only assets (supports PyInstaller _MEIPASS)."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


def _is_writable(directory: Path) -> bool:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / ".aurora_write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def _has_existing_data(directory: Path) -> bool:
    return (directory / "config.json").exists() or (directory / "Groups").is_dir()


def get_data_root() -> Path:
    """Persistent root for Groups, config.json, memo.txt and the icon cache.

    Priority:
      1. Portable install: the exe directory (or repository root in dev mode),
         whenever it already contains data or is writable.
      2. %APPDATA%\\AuroraDesktop -- when the exe directory is read-only
         (e.g. installed under Program Files).
    """
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
    else:
        exe_dir = Path(__file__).resolve().parent.parent

    if _has_existing_data(exe_dir) or _is_writable(exe_dir):
        return exe_dir

    appdata = os.environ.get("APPDATA")
    base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    fallback = base / "AuroraDesktop"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


BUNDLE_DIR = get_bundle_dir()
DATA_ROOT = get_data_root()
GROUPS_DIR = DATA_ROOT / "Groups"
CACHE_DIR = DATA_ROOT / "cache" / "icons"
CUSTOM_ICONS_DIR = DATA_ROOT / "cache" / "custom_icons"
CONFIG_PATH = DATA_ROOT / "config.json"
ASSETS_DIR = BUNDLE_DIR / "assets"
FONTS_DIR = ASSETS_DIR / "fonts"
ICON_ICO_PATH = ASSETS_DIR / "aurora.ico"
ICON_PNG_PATH = ASSETS_DIR / "aurora.png"
