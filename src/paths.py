import sys
from pathlib import Path


def get_bundle_dir() -> Path:
    """Directory containing bundled read-only assets (supports PyInstaller _MEIPASS)."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


def get_data_root() -> Path:
    """Persistent root directory for Groups, config.json, and icon cache."""
    default_root = Path(r"D:\AuroraDesktop")
    if default_root.exists():
        return default_root
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


BUNDLE_DIR = get_bundle_dir()
DATA_ROOT = get_data_root()
GROUPS_DIR = DATA_ROOT / "Groups"
CACHE_DIR = DATA_ROOT / "cache" / "icons"
CONFIG_PATH = DATA_ROOT / "config.json"
ASSETS_DIR = BUNDLE_DIR / "assets"
FONTS_DIR = ASSETS_DIR / "fonts"
ICON_ICO_PATH = ASSETS_DIR / "aurora.ico"
ICON_PNG_PATH = ASSETS_DIR / "aurora.png"
