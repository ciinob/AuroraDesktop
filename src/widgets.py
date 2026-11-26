import ctypes
from ctypes import wintypes
import math
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
import win32com.client

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QMimeData,
    QPoint,
    QPointF,
    QRectF,
    QSize,
    Qt,
    QTimer,
    QUrl,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QCursor,
    QDrag,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
    QRegion,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from animator import HighRefreshAnimation
from icon_extractor import ShortcutIconLoader, format_display_name, is_recycle_bin_item, query_recycle_bin_state
from paths import DATA_ROOT
from win32_utils import (
    ASFW_ANY,
    HWND_BOTTOM,
    MA_NOACTIVATE,
    SC_MINIMIZE,
    WM_MOUSEACTIVATE,
    WM_SYSCOMMAND,
    apply_acrylic_and_rounded_corners,
    pin_window_to_desktop_bottom,
    send_to_bottom,
    user32,
)

shell32 = ctypes.windll.shell32
shell32.ShellExecuteW.argtypes = [
    wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR,
    wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_int,
]
shell32.ShellExecuteW.restype = wintypes.HINSTANCE
shell32.SHEmptyRecycleBinW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.DWORD]
shell32.SHEmptyRecycleBinW.restype = ctypes.c_long

AURORA_MIME_TYPE = "application/x-aurora-shortcut-item"
SHELL_IDLIST_MIME = 'application/x-qt-windows-mime;value="Shell IDList Array"'

# Built-in Windows virtual Shell items (This PC, Recycle Bin, Control Panel, Network, Downloads, User Folder)
SYSTEM_SHELL_ITEMS: dict[str, dict] = {
    "this_pc": {
        "label": "🖥️ 此电脑 (This PC)",
        "name": "此电脑",
        "target": r"C:\Windows\explorer.exe",
        "args": "::{20D04FE0-3AEA-1069-A2D8-08002B30309D}",
        "icon": r"C:\Windows\System32\imageres.dll,-109",
        "clsids": ["20d04fe0-3aea-1069-a2d8-08002b30309d"],
    },
    "recycle_bin": {
        "label": "🗑️ 回收站 (Recycle Bin)",
        "name": "回收站",
        "target": r"C:\Windows\explorer.exe",
        "args": "::{645FF040-5081-101B-9F08-00AA002F954E}",
        "icon": r"C:\Windows\System32\imageres.dll,-54",
        "clsids": ["645ff040-5081-101b-9f08-00aa002f954e"],
    },
    "downloads": {
        "label": "📥 下载文件夹 (Downloads)",
        "name": "下载",
        "target": r"C:\Windows\explorer.exe",
        "args": "shell:Downloads",
        "icon": r"C:\Windows\System32\imageres.dll,-184",
        "clsids": ["374de290-123f-4565-9164-39c4925e467b", "088e3905-0323-4b02-9826-5d99428e115f"],
    },
    "user_files": {
        "label": "👤 个人主目录 (User Folder)",
        "name": "个人文件夹",
        "target": r"C:\Windows\explorer.exe",
        "args": "shell:UsersFilesFolder",
        "icon": r"C:\Windows\System32\imageres.dll,-123",
        "clsids": ["59031a47-3f72-44a7-89c5-5595fe6b30ee"],
    },
    "control_panel": {
        "label": "🎛️ 控制面板 (Control Panel)",
        "name": "控制面板",
        "target": r"C:\Windows\explorer.exe",
        "args": "shell:ControlPanelFolder",
        "icon": r"C:\Windows\System32\imageres.dll,-27",
        "clsids": ["26ee0668-a00a-44d7-9371-beb064c98683", "5399e694-6ce5-4d6c-8fce-1d8870fdcba0"],
    },
    "network": {
        "label": "🌐 网络邻居 (Network)",
        "name": "网络",
        "target": r"C:\Windows\explorer.exe",
        "args": "::{F02C1A0D-BE21-4350-88B0-7367FC96EF3C}",
        "icon": r"C:\Windows\System32\imageres.dll,-25",
        "clsids": ["f02c1a0d-be21-4350-88b0-7367fc96ef3c", "208d2c60-3aea-1069-a2d7-08002b30309d"],
    },
}


def create_system_shell_shortcut(item_key: str, dest_folder: Path) -> Path | None:
    """Create a crisp native Windows 11 shortcut for virtual desktop icons like This PC or Recycle Bin."""
    spec = SYSTEM_SHELL_ITEMS.get(item_key)
    if not spec:
        return None
    dest_folder.mkdir(parents=True, exist_ok=True)
    lnk_path = dest_folder / f"{spec['name']}.lnk"
    shell = win32com.client.Dispatch("WScript.Shell")
    sc = shell.CreateShortcut(str(lnk_path))
    sc.TargetPath = spec["target"]
    sc.Arguments = spec["args"]
    sc.IconLocation = spec["icon"]
    sc.Description = spec["label"]
    sc.Save()
    return lnk_path


def has_shell_idlist_mime(mime_data: QMimeData) -> bool:
    return mime_data.hasFormat(SHELL_IDLIST_MIME) or any(
        "Shell IDList Array" in fmt for fmt in mime_data.formats()
    )


def import_shell_idlist_drop(mime_data: QMimeData, dest_folder: Path) -> bool:
    """Detect virtual Windows Desktop icons (This PC, Recycle Bin, etc.) dragged from Explorer via CIDA PIDL GUIDs."""
    fmt = SHELL_IDLIST_MIME
    if not mime_data.hasFormat(fmt):
        fmt = next((f for f in mime_data.formats() if "Shell IDList Array" in f), "")
    if not fmt:
        return False
    raw = bytes(mime_data.data(fmt))
    if not raw:
        return False

    imported = False
    for item_key, spec in SYSTEM_SHELL_ITEMS.items():
        for clsid_str in spec["clsids"]:
            if uuid.UUID(clsid_str).bytes_le in raw:
                if create_system_shell_shortcut(item_key, dest_folder):
                    imported = True
                break
    return imported


def is_recycle_bin_shortcut(item_path: Path) -> bool:
    return is_recycle_bin_item(item_path)

# Aurora color palettes: (Primary, Mid, Secondary, Display Label)
AURORA_THEMES: dict[str, tuple[QColor, QColor, QColor, str]] = {
    "aurora": (QColor("#2dd4bf"), QColor("#38bdf8"), QColor("#a855f7"), "🌌 北极光翠紫 (默认)"),
    "glacier": (QColor("#38bdf8"), QColor("#60a5fa"), QColor("#818cf8"), "🧊 冰川极昼蓝"),
    "nebula": (QColor("#f472b6"), QColor("#c084fc"), QColor("#818cf8"), "🌸 星云流光粉"),
    "vision": (QColor("#f8fafc"), QColor("#cbd5e1"), QColor("#94a3b8"), "❄️ VisionOS 纯白霜玻璃"),
}

GLASS_OPACITY_LEVELS: dict[str, tuple[int, str]] = {
    "airy": (102, "极致高透 (Airy)"),
    "standard": (135, "标准极光 (Default)"),
    "deep": (176, "深邃暗夜 (Deep)"),
}

PRIORITY_ORDER = {
    "AI_CAPSULE": ["gemini", "claude", "chatgpt", "deepseek", "grok"],
    "RESEARCH_DEV": [
        "matlab", "zotero", "visual studio code", "vscode", "antigravity",
        "数学知识图谱", "cc-switch", "workbuddy", "workdaddy",
        "word", "excel", "powerpoint", "wps", "腾讯会议",
    ],
    "PLAY_SOCIAL": [
        "steam", "rockstar", "plain craft launcher", "pcl", "暴雪战网", "wegame", "完美",
        "kook", "oopz", "qq", "微信", "telegram",
        "网易云音乐", "libretv", "短剧", "leagueakari", "pavise", "外星仔",
    ],
    "TOOLS_NET": [
        "clash verge", "proxyswitch", "cutecloud", "aria2", "夸克网盘", "edge",
        "剪映", "logitech", "inzone", "g-menu", "火绒", "图吧", "rainmeter", "translucenttb",
    ],
}

MENU_QSS = """
QMenu {
    background-color: rgba(14, 20, 36, 245);
    color: rgba(248, 250, 255, 244);
    border: 1px solid rgba(255, 255, 255, 38);
    border-radius: 11px;
    padding: 6px 5px;
    font-family: "Inter", "Noto Sans SC", "Microsoft YaHei UI";
    font-size: 12px;
    font-weight: 500;
}
QMenu::item {
    padding: 6px 22px 6px 14px;
    border-radius: 7px;
    margin: 1px 4px;
}
QMenu::item:selected {
    background-color: rgba(45, 212, 191, 58);
    color: #ffffff;
}
QMenu::separator {
    height: 1px;
    background: rgba(255, 255, 255, 22);
    margin: 5px 10px;
}
"""

DIALOG_QSS = """
QDialog, QMessageBox, QInputDialog {
    background-color: #101728;
    color: #f1f5f9;
    font-family: "Inter", "Noto Sans SC", "Microsoft YaHei UI";
    font-size: 13px;
}
QLabel {
    color: #e2e8f0;
    font-weight: 500;
}
QLineEdit, QComboBox {
    background-color: #1a243b;
    color: #ffffff;
    border: 1px solid rgba(45, 212, 191, 110);
    border-radius: 8px;
    padding: 7px 10px;
    font-family: "Inter", "Noto Sans SC", "Microsoft YaHei UI";
    font-size: 13px;
}
QComboBox::drop-down {
    border: none;
    width: 24px;
}
QComboBox QAbstractItemView {
    background-color: #162036;
    color: #f8fafc;
    selection-background-color: rgba(45, 212, 191, 70);
    border: 1px solid rgba(45, 212, 191, 100);
}
QPushButton {
    background-color: #1e293b;
    color: #e2e8f0;
    border: 1px solid rgba(255, 255, 255, 35);
    border-radius: 8px;
    padding: 6px 16px;
    font-weight: 500;
}
QPushButton:hover {
    background-color: #28354d;
}
QPushButton#primaryBtn {
    background-color: #14b8a6;
    color: #04131a;
    border: none;
    font-weight: 600;
}
QPushButton#primaryBtn:hover {
    background-color: #2dd4bf;
}
"""


class NewCapsuleDialog(QDialog):
    """Apple-dark styled modal dialog to create a capsule card, compact bar, or live Folder Portal."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("新建极光胶囊分区")
        self.setFixedWidth(430)
        self.setStyleSheet(DIALOG_QSS)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)

        lbl_kind = QLabel("选择胶囊形态：")
        self.combo_kind = QComboBox()
        self.combo_kind.addItem("🧊 可折叠极光卡片（自动卷起为胶囊）", "card")
        self.combo_kind.addItem("💊 横向单行悬浮胶囊栏（类似顶部 AI 栏）", "bar")
        self.combo_kind.addItem("📂 文件夹实时映射胶囊（Folder Portal · 同步最新文件）", "portal")

        lbl_name = QLabel("胶囊分区名称（支持中英文）：")
        self.edit_name = QLineEdit()
        self.edit_name.setPlaceholderText("例如：ACADEMIC / 下载夹 / 近期截图")

        # Portal-specific options container
        self.portal_box = QWidget()
        p_lay = QVBoxLayout(self.portal_box)
        p_lay.setContentsMargins(0, 2, 0, 2)
        p_lay.setSpacing(8)
        p_lay.addWidget(QLabel("选择要实时映射的本地文件夹："))
        path_row = QHBoxLayout()
        path_row.setSpacing(6)
        default_dl = Path.home() / "Downloads"
        self.edit_portal_path = QLineEdit(str(default_dl if default_dl.exists() else Path.home()))
        btn_browse = QPushButton("浏览...")
        btn_browse.clicked.connect(self._browse_portal_dir)
        path_row.addWidget(self.edit_portal_path, 1)
        path_row.addWidget(btn_browse)
        p_lay.addLayout(path_row)

        p_lay.addWidget(QLabel("文件排序方式："))
        self.combo_portal_sort = QComboBox()
        self.combo_portal_sort.addItem("🕒 最新修改优先（推荐下载夹 / 截图夹）", "mtime_desc")
        self.combo_portal_sort.addItem("📁 文件夹优先 + 最新修改", "dirs_first")
        self.combo_portal_sort.addItem("🔤 按名称字母排序", "name_asc")
        p_lay.addWidget(self.combo_portal_sort)
        self.portal_box.setVisible(False)

        self.combo_kind.currentIndexChanged.connect(self._on_kind_changed)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_cancel = QPushButton("取消")
        btn_ok = QPushButton("立即创建")
        btn_ok.setObjectName("primaryBtn")
        btn_ok.setDefault(True)
        btn_cancel.clicked.connect(self.reject)
        btn_ok.clicked.connect(self._on_accept)
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_ok)

        layout.addWidget(lbl_kind)
        layout.addWidget(self.combo_kind)
        layout.addWidget(lbl_name)
        layout.addWidget(self.edit_name)
        layout.addWidget(self.portal_box)
        layout.addStretch(1)
        layout.addLayout(btn_row)
        self.adjustSize()

    def _on_kind_changed(self):
        is_portal = self.combo_kind.currentData() == "portal"
        self.portal_box.setVisible(is_portal)
        if is_portal and not self.edit_name.text().strip():
            p = Path(self.edit_portal_path.text().strip())
            if p.name:
                self.edit_name.setText(p.name)
        self.adjustSize()

    def _browse_portal_dir(self):
        cur = self.edit_portal_path.text().strip() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, "选择要实时映射的文件夹", cur)
        if chosen:
            self.edit_portal_path.setText(chosen)
            if not self.edit_name.text().strip():
                self.edit_name.setText(Path(chosen).name or chosen)

    def _on_accept(self):
        if self.combo_kind.currentData() == "portal":
            p_str = self.edit_portal_path.text().strip()
            if not p_str or not Path(p_str).is_dir():
                self.edit_portal_path.setFocus()
                return
            if not self.edit_name.text().strip():
                self.edit_name.setText(Path(p_str).name or "Folder Portal")
        if not self.edit_name.text().strip():
            self.edit_name.setFocus()
            return
        self.accept()

    def get_result(self) -> tuple[str, str]:
        return self.edit_name.text().strip(), str(self.combo_kind.currentData())

    def get_portal_options(self) -> tuple[str, str, int]:
        return (
            self.edit_portal_path.text().strip(),
            str(self.combo_portal_sort.currentData() or "mtime_desc"),
            15,
        )


def make_apple_font(pixel_size: int, weight: QFont.Weight = QFont.Medium, letter_spacing: float = 0.0) -> QFont:
    """Create Apple SF Pro + PingFang style font stack (Inter + Noto Sans SC)."""
    font = QFont()
    font.setFamilies(["Inter", "Noto Sans SC Medium", "Noto Sans SC", "Microsoft YaHei UI"])
    font.setPixelSize(pixel_size)
    font.setWeight(weight)
    font.setHintingPreference(QFont.PreferNoHinting)
    font.setStyleStrategy(QFont.PreferAntialias)
    if letter_spacing != 0.0:
        font.setLetterSpacing(QFont.AbsoluteSpacing, letter_spacing)
    return font


def extract_vibrant_accent(pm: QPixmap) -> QColor:
    """Sample dominant vibrant color from an app icon for subtle color-adaptive hover aura."""
    if pm.isNull():
        return QColor("#2dd4bf")
    img = pm.scaled(16, 16, Qt.IgnoreAspectRatio, Qt.FastTransformation).toImage()
    r_sum = g_sum = b_sum = w_sum = 0.0
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            if c.alpha() < 80:
                continue
            sat = c.hsvSaturationF()
            val = c.valueF()
            weight = 0.25 + sat * 1.8 + (0.3 if 0.25 < val < 0.95 else 0.0)
            r_sum += c.red() * weight
            g_sum += c.green() * weight
            b_sum += c.blue() * weight
            w_sum += weight
    if w_sum <= 0.01:
        return QColor("#2dd4bf")
    col = QColor(int(r_sum / w_sum), int(g_sum / w_sum), int(b_sum / w_sum))
    # Ensure pleasant brightness & saturation on dark glass
    h, s, l, _ = col.getHsl()
    if h < 0:
        return QColor("#38bdf8")
    col.setHsl(h, max(140, min(235, s)), max(135, min(185, l)))
    return col


def sort_group_items(group_key: str, files: list[Path], custom_order: list[str] | None = None) -> list[Path]:
    order_map = {name.lower(): i for i, name in enumerate(custom_order or [])}
    priorities = PRIORITY_ORDER.get(group_key, [])

    def rank(p: Path):
        low_name = p.name.lower()
        if low_name in order_map:
            return (-1, order_map[low_name], low_name)
        stem = p.stem.lower()
        for idx, kw in enumerate(priorities):
            if kw in stem:
                return (0, idx, stem)
        return (1, 999, stem)

    return sorted(files, key=rank)


def _clean_pyinstaller_env() -> dict[str, str]:
    env = os.environ.copy()
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        meipass_norm = os.path.normcase(os.path.normpath(meipass))
        raw_path = env.get("PATH", "")
        cleaned_parts = [
            p for p in raw_path.split(os.pathsep)
            if p and not os.path.normcase(os.path.normpath(p)).startswith(meipass_norm)
        ]
        env["PATH"] = os.pathsep.join(cleaned_parts)

    for k in ("QT_PLUGIN_PATH", "QML2_IMPORT_PATH", "_MEIPASS2", "PYTHONPATH", "PYTHONHOME"):
        env.pop(k, None)
    return env


def launch_item(path: Path, run_as_admin: bool = False):
    if not path.exists():
        return

    user32.AllowSetForegroundWindow(ASFW_ANY)

    saved_env = {}
    meipass = getattr(sys, "_MEIPASS", None)
    keys_to_strip = ("QT_PLUGIN_PATH", "QML2_IMPORT_PATH", "_MEIPASS2", "PYTHONPATH", "PYTHONHOME")
    for k in keys_to_strip:
        if k in os.environ:
            saved_env[k] = os.environ.pop(k)

    orig_path = os.environ.get("PATH", "")
    if meipass:
        meipass_norm = os.path.normcase(os.path.normpath(meipass))
        os.environ["PATH"] = os.pathsep.join(
            p for p in orig_path.split(os.pathsep)
            if p and not os.path.normcase(os.path.normpath(p)).startswith(meipass_norm)
        )

    try:
        if run_as_admin:
            shell32.ShellExecuteW(None, "runas", str(path), None, str(path.parent), 1)
        else:
            res = shell32.ShellExecuteW(None, None, str(path), None, None, 1)
            if int(res) <= 32:
                os.startfile(str(path))
    except Exception:
        try:
            subprocess.Popen(["explorer.exe", str(path)], env=_clean_pyinstaller_env())
        except Exception:
            pass
    finally:
        os.environ["PATH"] = orig_path
        for k, v in saved_env.items():
            os.environ[k] = v


def open_target_location(path: Path, icon_loader: ShortcutIconLoader):
    target = icon_loader.resolve_target_path(path)
    if target and os.path.exists(target):
        subprocess.Popen(["explorer.exe", f"/select,{target}"])
    else:
        subprocess.Popen(["explorer.exe", f"/select,{path}"])


HIDDEN_SKIP_FILES = {"desktop.ini", "thumbs.db", ".ds_store"}
PORTAL_SKIP_EXTS = {".tmp", ".crdownload", ".part", ".partial", ".opdownload"}
FILE_ATTR_HIDDEN_OR_SYS = 0x02 | 0x04


def list_valid_partition_items(folder_path: Path) -> list[Path]:
    if not folder_path.exists():
        return []
    return [
        p for p in folder_path.iterdir()
        if p.name.lower() not in HIDDEN_SKIP_FILES and not p.name.startswith(".")
    ]


def list_portal_items(folder_path: Path, sort_by: str = "mtime_desc", max_items: int = 15) -> list[Path]:
    """Fast single-pass directory scanner for Folder Portal capsules (safe on 5,000+ file folders)."""
    if not folder_path.is_dir():
        return []
    records: list[tuple[str, bool, float, Path]] = []
    try:
        with os.scandir(folder_path) as it:
            for entry in it:
                name = entry.name
                low = name.lower()
                if low in HIDDEN_SKIP_FILES or name.startswith(".") or name.startswith("~$"):
                    continue
                if any(low.endswith(ext) for ext in PORTAL_SKIP_EXTS):
                    continue
                try:
                    st = entry.stat()
                    if getattr(st, "st_file_attributes", 0) & FILE_ATTR_HIDDEN_OR_SYS:
                        continue
                    is_dir = entry.is_dir(follow_symlinks=False)
                    mtime = float(st.st_mtime)
                except OSError:
                    continue
                records.append((low, is_dir, mtime, Path(entry.path)))
    except OSError:
        return []

    if sort_by == "name_asc":
        records.sort(key=lambda r: r[0])
    elif sort_by == "dirs_first":
        records.sort(key=lambda r: (0 if r[1] else 1, -r[2], r[0]))
    else:
        records.sort(key=lambda r: (-r[2], r[0]))

    limit = max(1, int(max_items or 15))
    return [r[3] for r in records[:limit]]


def import_item_into_group_folder(src_path: Path, dest_folder: Path) -> Path | None:
    if not src_path.exists():
        return None
    dest_folder.mkdir(parents=True, exist_ok=True)
    if src_path.parent.resolve() == dest_folder.resolve():
        return src_path

    ext = src_path.suffix.lower()
    if ext in (".lnk", ".url"):
        dst = dest_folder / src_path.name
        shutil.copy2(str(src_path), str(dst))
        return dst
    else:
        base_label = src_path.stem if ext in (".exe", ".bat", ".cmd") else src_path.name
        lnk_path = dest_folder / f"{base_label}.lnk"
        shell = win32com.client.Dispatch("WScript.Shell")
        sc = shell.CreateShortcut(str(lnk_path))
        sc.TargetPath = str(src_path)
        sc.WorkingDirectory = str(src_path.parent if src_path.is_file() else src_path)
        sc.Save()
        return lnk_path


def safe_remove_shortcut(item_path: Path):
    if not item_path.exists():
        return
    backup_dir = DATA_ROOT / "Removed_Backup"
    backup_dir.mkdir(parents=True, exist_ok=True)
    dest = backup_dir / item_path.name
    if dest.exists():
        if dest.is_dir():
            shutil.rmtree(str(dest), ignore_errors=True)
        else:
            dest.unlink()
    shutil.move(str(item_path), str(dest))


def prompt_add_items_to_folder(parent: QWidget, dest_folder: Path) -> bool:
    files, _ = QFileDialog.getOpenFileNames(
        parent,
        "选择要添加的文件（支持图片、PDF、文档、程序、快捷方式）",
        str(Path.home() / "Desktop"),
        "所有支持文件 (*.*);;图片与 PDF (*.png *.jpg *.jpeg *.webp *.gif *.bmp *.pdf);;办公文档 (*.pdf *.doc *.docx *.xls *.xlsx *.ppt *.pptx *.txt *.md);;程序与快捷方式 (*.lnk *.exe *.url *.bat)",
    )
    if not files:
        return False
    for f in files:
        import_item_into_group_folder(Path(f), dest_folder)
    return True


def prompt_add_directory_to_folder(parent: QWidget, dest_folder: Path) -> bool:
    chosen_dir = QFileDialog.getExistingDirectory(
        parent,
        "选择要添加到此极光分区的文件夹",
        str(Path.home() / "Desktop"),
    )
    if not chosen_dir:
        return False
    import_item_into_group_folder(Path(chosen_dir), dest_folder)
    return True


class AuroraIconTile(QWidget):
    """Minimalist icon tile with adaptive icon-color hover aura, click ripple ring, and drag-to-reorder."""
    moveRequested = Signal(Path, str)
    customizeRequested = Signal(Path)
    hoverNameChanged = Signal(str)

    def __init__(
        self,
        item_path: Path,
        icon_loader: ShortcutIconLoader,
        compact_capsule: bool = False,
        all_groups: dict[str, tuple[str, Path]] | None = None,
        current_group_key: str = "",
        is_portal_item: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self.item_path = item_path
        self.icon_loader = icon_loader
        self.compact_capsule = compact_capsule
        self.all_groups = all_groups or {}
        self.current_group_key = current_group_key
        self.is_portal_item = is_portal_item
        self._is_recycle_bin = (not is_portal_item) and is_recycle_bin_shortcut(item_path)

        self.short_name, self.full_name = format_display_name(item_path)
        self.icon_size = 34 if compact_capsule else 36
        self.pixmap: QPixmap = icon_loader.get_icon_pixmap(item_path, self.icon_size * 2)
        self.accent_color: QColor = extract_vibrant_accent(self.pixmap)

        if compact_capsule:
            self.setFixedSize(54, 52)
        else:
            self.setFixedSize(66, 68)

        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)
        self.setToolTip(self.full_name)

        self._hover_progress = 0.0
        self._press_scale = 1.0
        self._press_origin = QPoint()
        self._last_launch_ts = 0.0
        self._ripple_progress = 0.0
        self._ripple_active = False

        self._anim = HighRefreshAnimation(self)
        self._anim.setDuration(150)
        self._anim.setEasingCurve(QEasingCurve.OutQuart)
        self._anim.valueChanged.connect(self._on_anim_val)

        self._ripple_anim = HighRefreshAnimation(self)
        self._ripple_anim.setDuration(300)
        self._ripple_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._ripple_anim.valueChanged.connect(self._on_ripple_val)
        self._ripple_anim.finished.connect(self._on_ripple_done)

    def _on_anim_val(self, val):
        self._hover_progress = float(val)
        self.update()

    def _on_ripple_val(self, val):
        self._ripple_progress = float(val)
        self.update()

    def _on_ripple_done(self):
        self._ripple_active = False
        self.update()

    def refresh_dynamic_icon(self):
        new_pm = self.icon_loader.get_icon_pixmap(self.item_path, self.icon_size * 2)
        if not new_pm.isNull():
            self.pixmap = new_pm
            self.accent_color = extract_vibrant_accent(self.pixmap)
            self.update()

    def enterEvent(self, event):
        if self._is_recycle_bin:
            has_items, cnt, sz_bytes = query_recycle_bin_state()
            if has_items:
                sz_mb = sz_bytes / (1024 * 1024)
                sz_txt = f"{sz_mb:.1f} MB" if sz_mb >= 0.1 else f"{max(1, sz_bytes // 1024)} KB"
                self.setToolTip(f"回收站 · 共 {cnt} 项 ({sz_txt})")
            else:
                self.setToolTip("回收站 · 空")
            self.refresh_dynamic_icon()
        self._anim.stop()
        self._anim.setStartValue(self._hover_progress)
        self._anim.setEndValue(1.0)
        self._anim.start()
        self.hoverNameChanged.emit(self.full_name)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._anim.stop()
        self._anim.setStartValue(self._hover_progress)
        self._anim.setEndValue(0.0)
        self._anim.start()
        self.hoverNameChanged.emit("")
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._press_scale = 0.90
            self._press_origin = event.position().toPoint()
            self.update()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        # Forward cursor position to parent AuroraBaseWindow for cursor-tracking border spotlight!
        win = self.window()
        if isinstance(win, AuroraBaseWindow):
            win.update_cursor_spotlight(win.mapFromGlobal(event.globalPosition().toPoint()))

        if (event.buttons() & Qt.LeftButton) and not self._press_origin.isNull():
            if (event.position().toPoint() - self._press_origin).manhattanLength() > 8:
                self._press_scale = 1.0
                self._start_tile_drag()
                return
        super().mouseMoveEvent(event)

    def _start_tile_drag(self):
        drag = QDrag(self)
        mime = QMimeData()
        if not self.is_portal_item:
            payload = f"{self.current_group_key}|{self.item_path}".encode("utf-8")
            mime.setData(AURORA_MIME_TYPE, payload)
        mime.setUrls([QUrl.fromLocalFile(str(self.item_path))])
        drag.setMimeData(mime)
        if not self.pixmap.isNull():
            drag_pm = self.pixmap.scaled(40, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            drag.setPixmap(drag_pm)
            drag.setHotSpot(QPoint(20, 20))
        drag.exec(Qt.CopyAction if self.is_portal_item else (Qt.MoveAction | Qt.CopyAction))

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            was_pressed = self._press_scale < 1.0
            self._press_scale = 1.0
            self._press_origin = QPoint()
            self.update()
            if was_pressed and self.rect().contains(event.position().toPoint()):
                now = time.monotonic()
                if now - self._last_launch_ts > 0.6:
                    self._last_launch_ts = now
                    self._ripple_active = True
                    self._ripple_anim.stop()
                    self._ripple_anim.setStartValue(0.0)
                    self._ripple_anim.setEndValue(1.0)
                    self._ripple_anim.start()
                    launch_item(self.item_path)
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event):
        parent_card = self.window()
        if hasattr(parent_card, "set_menu_open"):
            parent_card.set_menu_open(True)

        menu = QMenu(self)
        menu.setStyleSheet(MENU_QSS)

        act_open = menu.addAction(f"打开 {self.short_name}")
        act_empty_bin = None
        if self._is_recycle_bin:
            has_rb, _, _ = query_recycle_bin_state()
            act_empty_bin = menu.addAction("🧹 清空回收站..." if has_rb else "🧹 回收站已是空的")
            act_empty_bin.setEnabled(has_rb)
        act_admin = None
        if not self.is_portal_item or self.item_path.suffix.lower() in (".exe", ".bat", ".cmd", ".lnk"):
            act_admin = menu.addAction("以管理员身份运行")
        act_loc = menu.addAction("在资源管理器中定位")
        act_copy_path = None
        act_custom = None
        move_actions: dict[QAction, str] = {}
        act_remove = None

        if self.is_portal_item:
            act_copy_path = menu.addAction("复制完整文件路径")
        else:
            menu.addSeparator()
            act_custom = menu.addAction("🖼️ 自定义图标 / 重命名...")
            move_menu = menu.addMenu("移至其他极光分区")
            move_menu.setStyleSheet(MENU_QSS)
            for g_key, (g_title, _) in self.all_groups.items():
                if g_key != self.current_group_key:
                    a = move_menu.addAction(g_title)
                    move_actions[a] = g_key
            menu.addSeparator()
            act_remove = menu.addAction("从此分区移除图标")

        chosen = menu.exec(event.globalPos())
        if hasattr(parent_card, "set_menu_open"):
            parent_card.set_menu_open(False)

        if chosen == act_open:
            launch_item(self.item_path)
        elif act_empty_bin is not None and chosen == act_empty_bin:
            shell32.SHEmptyRecycleBinW(None, None, 0)
            QTimer.singleShot(150, self.refresh_dynamic_icon)
        elif act_admin is not None and chosen == act_admin:
            launch_item(self.item_path, run_as_admin=True)
        elif chosen == act_loc:
            open_target_location(self.item_path, self.icon_loader)
        elif act_copy_path is not None and chosen == act_copy_path:
            QApplication.clipboard().setText(str(self.item_path))
        elif act_custom is not None and chosen == act_custom:
            self.customizeRequested.emit(self.item_path)
        elif chosen in move_actions:
            self.moveRequested.emit(self.item_path, move_actions[chosen])
        elif act_remove is not None and chosen == act_remove:
            safe_remove_shortcut(self.item_path)
            if hasattr(parent_card, "reload_items"):
                parent_card.reload_items()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing)

        w, h = self.width(), self.height()
        p = self._hover_progress

        win = self.window()
        c_theme = win.get_theme_colors()[0] if isinstance(win, AuroraBaseWindow) else QColor("#2dd4bf")

        # Color-adaptive hover glass aura (blends icon's vibrant color with Aurora theme!)
        if p > 0.01:
            bg_rect = QRectF(2.0, 2.0, w - 4.0, h - 4.0)
            grad = QLinearGradient(bg_rect.topLeft(), bg_rect.bottomRight())
            ca = QColor(self.accent_color); ca.setAlpha(int(48 * p))
            cb = QColor(c_theme); cb.setAlpha(int(36 * p))
            grad.setColorAt(0.0, ca)
            grad.setColorAt(1.0, cb)
            painter.setBrush(grad)
            stroke = QColor(self.accent_color)
            stroke.setAlpha(int(105 * p))
            painter.setPen(QPen(stroke, 1.0))
            painter.drawRoundedRect(bg_rect, 10.0, 10.0)

        # Click ripple wave animation
        if self._ripple_active:
            rp = self._ripple_progress
            cx, cy = w / 2.0, (h - 14.0) / 2.0
            rad = 10.0 + rp * 24.0
            r_col = QColor(c_theme)
            r_col.setAlpha(int(190 * (1.0 - rp)))
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(r_col, 1.6))
            painter.drawEllipse(QPointF(cx, cy), rad, rad)

        # Crisp icon with 2.5px spring hover lift
        lift = -2.5 * p
        isz = self.icon_size * self._press_scale
        ix = (w - isz) / 2.0
        iy = (4.0 if self.compact_capsule else 6.0) + lift + (self.icon_size - isz) / 2.0

        if not self.pixmap.isNull():
            painter.drawPixmap(QRectF(ix, iy, isz, isz), self.pixmap, QRectF(self.pixmap.rect()))

        # Apple macOS/iOS Medium weight label + 1px dark contrast shadow
        font = make_apple_font(10 if self.compact_capsule else 11, QFont.Medium, -0.1)
        painter.setFont(font)

        fm = QFontMetrics(font)
        max_tw = w - 2
        elided = fm.elidedText(self.short_name, Qt.ElideRight, max_tw)
        ty = h - (15 if self.compact_capsule else 19)
        text_rect = QRectF(1.0, ty, w - 2.0, 16.0)
        shadow_rect = QRectF(1.0, ty + 1.0, w - 2.0, 16.0)

        painter.setPen(QColor(0, 0, 0, 138))
        painter.drawText(shadow_rect, Qt.AlignHCenter | Qt.AlignVCenter, elided)

        text_alpha = int(224 + 31 * p) if self.compact_capsule else int(234 + 21 * p)
        painter.setPen(QColor(255, 255, 255, text_alpha))
        painter.drawText(text_rect, Qt.AlignHCenter | Qt.AlignVCenter, elided)


class AuroraBaseWindow(QWidget):
    """Frameless Windows 11 Acrylic card with cursor-tracking radial Aurora spotlight border."""
    positionChangedByUser = Signal()

    RADIUS = 14.0

    def __init__(self, allow_drag_provider=None, theme_provider=None, opacity_provider=None, snap_manager=None, parent=None):
        super().__init__(parent)
        self._allow_drag_provider = allow_drag_provider or (lambda: True)
        self._theme_provider = theme_provider or (lambda: AURORA_THEMES["aurora"][:3])
        self._opacity_provider = opacity_provider or (lambda: 135)
        self._snap_manager = snap_manager
        self._acrylic_initialized = False
        self._menu_open = False
        self._dragging = False
        self._drag_moved = False
        self._drag_offset = QPoint()
        self._cursor_pos = QPointF(-200.0, -200.0)

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMouseTracking(True)

        self._border_glow = 0.0
        self._glow_anim = HighRefreshAnimation(self)
        self._glow_anim.setDuration(200)
        self._glow_anim.setEasingCurve(QEasingCurve.OutQuart)
        self._glow_anim.valueChanged.connect(self._on_glow_changed)

        self._fade_anim = HighRefreshAnimation(self)
        self._fade_anim.setDuration(200)
        self._fade_anim.setEasingCurve(QEasingCurve.OutQuart)
        self._fade_anim.valueChanged.connect(self._on_fade_val)
        self._fade_anim.finished.connect(self._on_fade_finished)
        self._hiding_after_fade = False

    def get_theme_colors(self) -> tuple[QColor, QColor, QColor]:
        return self._theme_provider()

    def _begin_smart_drag(self, global_pt: QPoint):
        self._dragging = True
        self._drag_moved = False
        self._drag_offset = global_pt - self.frameGeometry().topLeft()
        self.setCursor(Qt.ClosedHandCursor)
        if self._snap_manager is not None:
            self._snap_manager.begin_drag(self)

    def _move_smart_drag(self, global_pt: QPoint, modifiers: Qt.KeyboardModifiers):
        new_pos = global_pt - self._drag_offset
        if self._snap_manager is not None:
            new_pos = self._snap_manager.snap_move(self, new_pos, modifiers, preview_radius=self.RADIUS)
        elif abs(new_pos.x() - 24) <= 12:
            new_pos.setX(24)
        if new_pos != self.pos():
            self._drag_moved = True
            self.move(new_pos)

    def _end_smart_drag(self):
        if self._dragging:
            moved = self._drag_moved
            self._dragging = False
            self._drag_moved = False
            self.unsetCursor()
            if self._snap_manager is not None:
                self._snap_manager.end_drag(self)
            if moved:
                self.positionChangedByUser.emit()

    def hideEvent(self, event):
        self._end_smart_drag()
        super().hideEvent(event)

    def update_cursor_spotlight(self, local_pt: QPoint):
        self._cursor_pos = QPointF(local_pt)
        if self._border_glow > 0.01:
            self.update()

    def _on_glow_changed(self, val):
        self._border_glow = float(val)
        self.update()

    def _on_fade_val(self, val):
        self.setWindowOpacity(float(val))

    def _on_fade_finished(self):
        if self._hiding_after_fade:
            self.hide()
            self._hiding_after_fade = False
        else:
            send_to_bottom(int(self.winId()))

    def fade_out(self):
        if not self.isVisible():
            return
        self._hiding_after_fade = True
        self._fade_anim.stop()
        self._fade_anim.setStartValue(self.windowOpacity())
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.start()

    def fade_in(self):
        self._hiding_after_fade = False
        if not self.isVisible():
            self.setWindowOpacity(0.0)
            self.show()
            self.ensure_native_desktop_style()
        self._fade_anim.stop()
        self._fade_anim.setStartValue(self.windowOpacity())
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.start()

    def ensure_native_desktop_style(self, reset_surface: bool = False):
        hwnd = int(self.winId())
        apply_acrylic_and_rounded_corners(hwnd, reset_first=reset_surface)
        pin_window_to_desktop_bottom(hwnd)
        self._acrylic_initialized = True

    def showEvent(self, event):
        super().showEvent(event)
        if not self._acrylic_initialized:
            QTimer.singleShot(10, self.ensure_native_desktop_style)
        else:
            send_to_bottom(int(self.winId()))

    def enterEvent(self, event):
        self._cursor_pos = QPointF(self.mapFromGlobal(QCursor.pos()))
        self._glow_anim.stop()
        self._glow_anim.setStartValue(self._border_glow)
        self._glow_anim.setEndValue(1.0)
        self._glow_anim.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        if not self._menu_open:
            self._glow_anim.stop()
            self._glow_anim.setStartValue(self._border_glow)
            self._glow_anim.setEndValue(0.0)
            self._glow_anim.start()
        super().leaveEvent(event)

    def mouseMoveEvent(self, event):
        self._cursor_pos = event.position()
        if self._border_glow > 0.01:
            self.update()
        super().mouseMoveEvent(event)

    def set_menu_open(self, is_open: bool):
        self._menu_open = is_open
        if not is_open and not self.underMouse():
            self._glow_anim.stop()
            self._glow_anim.setStartValue(self._border_glow)
            self._glow_anim.setEndValue(0.0)
            self._glow_anim.start()

    def nativeEvent(self, eventType, message):
        if eventType == b"windows_generic_MSG" or eventType == "windows_generic_MSG":
            msg = ctypes.wintypes.MSG.from_address(int(message))
            if msg.message == WM_SYSCOMMAND:
                if (msg.wParam & 0xFFF0) == SC_MINIMIZE:
                    return True, 0
            elif msg.message == WM_MOUSEACTIVATE:
                return True, MA_NOACTIVATE
        return super().nativeEvent(eventType, message)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)

        rect = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        path = QPainterPath()
        path.addRoundedRect(rect, self.RADIUS, self.RADIUS)

        c1, c_mid, c2 = self._theme_provider()
        bg_alpha = self._opacity_provider()
        g = self._border_glow

        # 1. Deep high-transparency glass fill
        painter.fillPath(path, QColor(10, 15, 28, bg_alpha))

        # 2. Top-edge specular frost sheen
        sheen = QLinearGradient(0, 0, 0, min(44.0, self.height()))
        sheen.setColorAt(0.0, QColor(255, 255, 255, int(10 + 10 * g)))
        sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.fillPath(path, sheen)

        # 3. VisionOS / Linear.app cursor-tracking ambient inner spotlight!
        if g > 0.02 and self._cursor_pos.x() > -100:
            inner_spot = QRadialGradient(self._cursor_pos, 145.0)
            sc1 = QColor(c1); sc1.setAlpha(int(22 * g))
            sc2 = QColor(c2); sc2.setAlpha(int(9 * g))
            sc_end = QColor(c1); sc_end.setAlpha(0)
            inner_spot.setColorAt(0.0, sc1)
            inner_spot.setColorAt(0.45, sc2)
            inner_spot.setColorAt(1.0, sc_end)
            painter.fillPath(path, inner_spot)

        # 4. 1px Northern Lights base gradient border
        alpha_main = int(64 + 130 * g)
        alpha_mid = int(42 + 105 * g)
        col_1 = QColor(c1); col_1.setAlpha(alpha_main)
        col_m = QColor(c_mid); col_m.setAlpha(alpha_mid)
        col_2 = QColor(c2); col_2.setAlpha(alpha_main)

        shift = 28.0 * g
        border_grad = QLinearGradient(
            QPointF(rect.left() + shift, rect.top()),
            QPointF(rect.right() - shift, rect.bottom()),
        )
        border_grad.setColorAt(0.0, col_1)
        border_grad.setColorAt(0.5, col_m)
        border_grad.setColorAt(1.0, col_2)

        painter.setPen(QPen(border_grad, 1.0))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)

        # 5. Cursor-tracking bright specular highlight along the 1px border!
        if g > 0.02 and self._cursor_pos.x() > -100:
            edge_spot = QRadialGradient(self._cursor_pos, 115.0)
            es_bright = QColor(255, 255, 255, int(185 * g))
            es_mid = QColor(c1); es_mid.setAlpha(int(150 * g))
            es_zero = QColor(c1); es_zero.setAlpha(0)
            edge_spot.setColorAt(0.0, es_bright)
            edge_spot.setColorAt(0.35, es_mid)
            edge_spot.setColorAt(1.0, es_zero)
            painter.setPen(QPen(edge_spot, 1.3))
            painter.drawPath(path)


class AICapsuleBar(AuroraBaseWindow):
    """Compact horizontal single-row Aurora Capsule Bar + right-side Spotlight search trigger pill."""
    itemMoveRequested = Signal(Path, str)
    orderChanged = Signal(str, list)
    contextActionTriggered = Signal(str)
    renameCapsuleRequested = Signal(str)
    deleteCapsuleRequested = Signal(str)
    openSettingsRequested = Signal(str, object)
    spotlightRequested = Signal()

    CARD_WIDTH = 368
    CARD_HEIGHT = 66

    def __init__(
        self,
        folder_path: Path,
        icon_loader: ShortcutIconLoader,
        header_font_family: str,
        all_groups: dict[str, tuple[str, Path]],
        allow_drag_provider=None,
        theme_provider=None,
        opacity_provider=None,
        custom_order_provider=None,
        group_key: str = "AI_CAPSULE",
        title: str = "AI 悬浮胶囊栏",
        badge_text: str = "AI",
        show_search_pill: bool = True,
        snap_manager=None,
    ):
        super().__init__(
            allow_drag_provider=allow_drag_provider,
            theme_provider=theme_provider,
            opacity_provider=opacity_provider,
            snap_manager=snap_manager,
        )
        self.group_key = group_key
        self.title = title
        self.badge_text = badge_text
        self.show_search_pill = show_search_pill
        self.folder_path = folder_path
        self.icon_loader = icon_loader
        self.header_font_family = header_font_family
        self.all_groups = all_groups
        self._custom_order_provider = custom_order_provider or (lambda _: [])
        self._hover_search = False
        self._hover_settings = False
        self._drop_insert_idx: int | None = None
        self._tile_count = 0
        self._search_rect = QRectF(self.CARD_WIDTH - 68.0, 14.0, 26.0, self.CARD_HEIGHT - 28.0)
        self._settings_rect = QRectF(self.CARD_WIDTH - 36.0, 14.0, 26.0, self.CARD_HEIGHT - 28.0)

        self.setFixedSize(self.CARD_WIDTH, self.CARD_HEIGHT)
        self.setAcceptDrops(True)

        self._row_container = QWidget(self)
        self._row_container.setMouseTracking(True)
        self._row_layout = QHBoxLayout(self._row_container)
        self._row_layout.setContentsMargins(0, 7, 0, 7)
        self._row_layout.setSpacing(1)
        init_right = 74 if show_search_pill else 12
        self._row_container.setGeometry(52, 0, max(10, self.CARD_WIDTH - 52 - init_right), self.CARD_HEIGHT)

        self.reload_items()

    def reload_items(self):
        while self._row_layout.count():
            item = self._row_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        files = list_valid_partition_items(self.folder_path)
        files = sort_group_items(self.group_key, files, self._custom_order_provider(self.group_key))
        self._tile_count = len(files)

        extra_right = 74 if self.show_search_pill else 12
        needed_w = max(self.CARD_WIDTH, 54 + len(files) * 55 + extra_right)
        self.setFixedSize(needed_w, self.CARD_HEIGHT)
        self._row_container.setGeometry(52, 0, max(10, needed_w - 52 - extra_right), self.CARD_HEIGHT)
        self._search_rect = QRectF(needed_w - 68.0, 14.0, 26.0, self.CARD_HEIGHT - 28.0)
        self._settings_rect = QRectF(needed_w - 36.0, 14.0, 26.0, self.CARD_HEIGHT - 28.0)

        for f in files:
            tile = AuroraIconTile(
                f,
                self.icon_loader,
                compact_capsule=True,
                all_groups=self.all_groups,
                current_group_key=self.group_key,
                parent=self._row_container,
            )
            tile.moveRequested.connect(self.itemMoveRequested.emit)
            tile.customizeRequested.connect(lambda p: self.openSettingsRequested.emit("icons", p))
            self._row_layout.addWidget(tile)

        self._row_layout.addStretch(1)
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            pos = event.position()
            if self.show_search_pill and self._search_rect.contains(pos):
                self.spotlightRequested.emit()
                return
            if self.show_search_pill and self._settings_rect.contains(pos):
                self.openSettingsRequested.emit("general", None)
                return
            if pos.x() < 52 and self._allow_drag_provider():
                self._begin_smart_drag(event.globalPosition().toPoint())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        pos = event.position()
        was_hov_s = self._hover_search
        was_hov_g = self._hover_settings
        self._hover_search = self.show_search_pill and self._search_rect.contains(pos)
        self._hover_settings = self.show_search_pill and self._settings_rect.contains(pos)
        if not self._dragging and (self._hover_search != was_hov_s or self._hover_settings != was_hov_g):
            any_pill = self._hover_search or self._hover_settings
            self.setCursor(Qt.PointingHandCursor if any_pill else Qt.ArrowCursor)
            if self._hover_search:
                self.setToolTip("极光全局搜索 (双击 Ctrl / Alt+S)")
            elif self._hover_settings:
                self.setToolTip("打开极光设置中心 (Alt+,)")
            else:
                self.setToolTip("")
            self.update()

        if self._dragging and (event.buttons() & Qt.LeftButton):
            self._move_smart_drag(event.globalPosition().toPoint(), event.modifiers())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._end_smart_drag()
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event):
        self.set_menu_open(True)
        menu = QMenu(self)
        menu.setStyleSheet(MENU_QSS)
        act_add = menu.addAction("➕ 添加应用 / 文件...")
        act_add_dir = menu.addAction("📁 添加文件夹...")
        sys_menu = menu.addMenu("🖥️ 添加系统图标 (此电脑 / 回收站)")
        sys_menu.setStyleSheet(MENU_QSS)
        sys_actions = {sys_menu.addAction(v["label"]): k for k, v in SYSTEM_SHELL_ITEMS.items()}
        act_folder = menu.addAction(f"📂 打开此分区文件夹 ({self.folder_path.name})")
        menu.addSeparator()
        act_settings = menu.addAction("⚙️ 管理此分组 / 打开设置中心...")
        act_hide = menu.addAction("🙈 隐藏全部桌面卡片")

        chosen = menu.exec(event.globalPos())
        self.set_menu_open(False)
        if chosen == act_add:
            if prompt_add_items_to_folder(self, self.folder_path):
                self.reload_items()
        elif chosen == act_add_dir:
            if prompt_add_directory_to_folder(self, self.folder_path):
                self.reload_items()
        elif chosen in sys_actions:
            if create_system_shell_shortcut(sys_actions[chosen], self.folder_path):
                self.reload_items()
        elif chosen == act_folder:
            subprocess.Popen(["explorer.exe", str(self.folder_path)])
        elif chosen == act_settings:
            self.openSettingsRequested.emit("groups", self.group_key)
        elif chosen == act_hide:
            self.contextActionTriggered.emit("toggle_visibility")

    def _calc_drop_index(self, x: float) -> int:
        raw_idx = int(round((x - 52.0) / 55.0))
        return max(0, min(self._tile_count, raw_idx))

    def dragEnterEvent(self, event):
        md = event.mimeData()
        if md.hasFormat(AURORA_MIME_TYPE) or md.hasUrls() or has_shell_idlist_mime(md):
            self._drop_insert_idx = self._calc_drop_index(event.position().x())
            self.update()
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        md = event.mimeData()
        if md.hasFormat(AURORA_MIME_TYPE) or md.hasUrls() or has_shell_idlist_mime(md):
            idx = self._calc_drop_index(event.position().x())
            if idx != self._drop_insert_idx:
                self._drop_insert_idx = idx
                self.update()
            event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        if self._drop_insert_idx is not None:
            self._drop_insert_idx = None
            self.update()
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        drop_x = event.position().x()
        self._drop_insert_idx = None
        self.update()
        md = event.mimeData()
        if md.hasFormat(AURORA_MIME_TYPE):
            raw = bytes(md.data(AURORA_MIME_TYPE)).decode("utf-8", errors="ignore")
            if "|" in raw:
                src_grp, src_path_str = raw.split("|", 1)
                src_path = Path(src_path_str)
                if src_grp == self.group_key:
                    files = sort_group_items(self.group_key, list_valid_partition_items(self.folder_path), self._custom_order_provider(self.group_key))
                    names = [p.name for p in files if p.name != src_path.name]
                    target_idx = max(0, min(len(names), int((drop_x - 52) // 55)))
                    names.insert(target_idx, src_path.name)
                    self.orderChanged.emit(self.group_key, names)
                    self.reload_items()
                    return
                elif src_path.exists():
                    self.itemMoveRequested.emit(src_path, self.group_key)
                    return

        imported_any = False
        for url in md.urls():
            local_str = url.toLocalFile()
            if local_str:
                local = Path(local_str)
                if local.exists():
                    import_item_into_group_folder(local, self.folder_path)
                    imported_any = True
        if not imported_any:
            import_shell_idlist_drop(md, self.folder_path)
        self.reload_items()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)

        c1, _, c2 = self.get_theme_colors()

        # Left aurora badge
        badge_rect = QRectF(10.0, 14.0, 34.0, self.height() - 28.0)
        grad = QLinearGradient(badge_rect.topLeft(), badge_rect.bottomRight())
        bc1 = QColor(c1); bc1.setAlpha(int(48 + 45 * self._border_glow))
        bc2 = QColor(c2); bc2.setAlpha(int(48 + 45 * self._border_glow))
        grad.setColorAt(0.0, bc1)
        grad.setColorAt(1.0, bc2)
        painter.setBrush(grad)
        b_pen = QColor(c1); b_pen.setAlpha(int(95 + 75 * self._border_glow))
        painter.setPen(QPen(b_pen, 1.0))
        painter.drawRoundedRect(badge_rect, 8.0, 8.0)

        disp_badge = self.badge_text[:3]
        font = make_apple_font(11 if len(disp_badge) >= 3 else 12, QFont.DemiBold, 0.3)
        painter.setFont(font)
        painter.setPen(QColor(0, 0, 0, 110))
        painter.drawText(badge_rect.translated(0, 1.0), Qt.AlignCenter, disp_badge)
        painter.setPen(QColor(255, 255, 255, 248))
        painter.drawText(badge_rect, Qt.AlignCenter, disp_badge)

        painter.setPen(QPen(QColor(255, 255, 255, 24), 1.0))
        painter.drawLine(QPointF(49.5, 15.0), QPointF(49.5, self.height() - 15.0))

        # Right-side sleek Spotlight Search & Settings trigger pills
        if self.show_search_pill:
            # 1) Search pill
            sr = self._search_rect
            s_alpha = 46 if self._hover_search else int(16 + 18 * self._border_glow)
            painter.setBrush(QColor(255, 255, 255, s_alpha))
            s_border = QColor(c1) if self._hover_search else QColor(255, 255, 255, 32)
            if self._hover_search:
                s_border.setAlpha(155)
            painter.setPen(QPen(s_border, 1.0))
            painter.drawRoundedRect(sr, 8.0, 8.0)

            cx, cy = sr.center().x() - 1.2, sr.center().y() - 1.2
            icon_col = QColor(255, 255, 255, 245 if self._hover_search else 185)
            pen = QPen(icon_col, 1.6)
            pen.setCapStyle(Qt.RoundCap)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(QPointF(cx, cy), 4.6, 4.6)
            painter.drawLine(QPointF(cx + 3.4, cy + 3.4), QPointF(cx + 6.8, cy + 6.8))

            # 2) Settings gear pill (one-click direct entry on desktop!)
            gr = self._settings_rect
            g_alpha = 46 if self._hover_settings else int(16 + 18 * self._border_glow)
            painter.setBrush(QColor(255, 255, 255, g_alpha))
            g_border = QColor(c1) if self._hover_settings else QColor(255, 255, 255, 32)
            if self._hover_settings:
                g_border.setAlpha(155)
            painter.setPen(QPen(g_border, 1.0))
            painter.drawRoundedRect(gr, 8.0, 8.0)

            gcx, gcy = gr.center().x(), gr.center().y()
            g_col = QColor(255, 255, 255, 245 if self._hover_settings else 185)
            g_pen = QPen(g_col, 1.5)
            g_pen.setCapStyle(Qt.RoundCap)
            painter.setPen(g_pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(QPointF(gcx, gcy), 3.3, 3.3)
            for i in range(6):
                ang = i * (math.pi / 3.0)
                x1 = gcx + math.cos(ang) * 4.2
                y1 = gcy + math.sin(ang) * 4.2
                x2 = gcx + math.cos(ang) * 6.2
                y2 = gcy + math.sin(ang) * 6.2
                painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))

        # Live drag-to-reorder glowing insertion indicator bar
        if self._drop_insert_idx is not None:
            ix = 52.0 + self._drop_insert_idx * 55.0
            max_ix = float(self.width() - (76 if self.show_search_pill else 14))
            ix = max(52.0, min(max_ix, ix))
            y1, y2 = 12.0, float(self.height() - 12.0)
            halo = QColor(c1); halo.setAlpha(90)
            painter.setPen(QPen(halo, 6.0, Qt.SolidLine, Qt.RoundCap))
            painter.drawLine(QPointF(ix, y1), QPointF(ix, y2))
            igrad = QLinearGradient(ix, y1, ix, y2)
            igrad.setColorAt(0.0, c1)
            igrad.setColorAt(1.0, c2)
            painter.setPen(QPen(igrad, 2.4, Qt.SolidLine, Qt.RoundCap))
            painter.drawLine(QPointF(ix, y1), QPointF(ix, y2))
            painter.setBrush(QColor(255, 255, 255, 240))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(QPointF(ix, y1), 2.5, 2.5)
            painter.drawEllipse(QPointF(ix, y2), 2.5, 2.5)


class CollapsibleAuroraCard(AuroraBaseWindow):
    """Collapsible Aurora glass partition card with cursor spotlight, wheel fold, and drag-to-reorder."""
    heightAnimated = Signal()
    pinToggled = Signal(str, bool)
    itemMoveRequested = Signal(Path, str)
    orderChanged = Signal(str, list)
    contextActionTriggered = Signal(str)
    renameCapsuleRequested = Signal(str)
    deleteCapsuleRequested = Signal(str)
    openSettingsRequested = Signal(str, object)
    spotlightRequested = Signal()

    CARD_WIDTH = 368
    HEADER_HEIGHT = 38
    COLS = 5
    TILE_W = 66
    TILE_H = 68
    GRID_PAD_X = 13
    GRID_PAD_BOTTOM = 12
    GRID_SPACING_X = 3
    GRID_SPACING_Y = 4

    def __init__(
        self,
        group_key: str,
        title: str,
        folder_path: Path,
        icon_loader: ShortcutIconLoader,
        header_font_family: str,
        all_groups: dict[str, tuple[str, Path]],
        pinned: bool = False,
        allow_drag_provider=None,
        theme_provider=None,
        opacity_provider=None,
        custom_order_provider=None,
        is_portal: bool = False,
        portal_sort_provider=None,
        portal_max_provider=None,
        snap_manager=None,
    ):
        super().__init__(
            allow_drag_provider=allow_drag_provider,
            theme_provider=theme_provider,
            opacity_provider=opacity_provider,
            snap_manager=snap_manager,
        )
        self.group_key = group_key
        self.title = title
        self.folder_path = folder_path
        self.icon_loader = icon_loader
        self.header_font_family = header_font_family
        self.all_groups = all_groups
        self.pinned = pinned
        self.is_portal = is_portal
        self._custom_order_provider = custom_order_provider or (lambda _: [])
        self._portal_sort_provider = portal_sort_provider or (lambda _: "mtime_desc")
        self._portal_max_provider = portal_max_provider or (lambda _: 15)

        self._expanded = True
        self._item_count = 0
        self._hovered_item_label = ""
        self._expanded_height = 180
        self._target_anim_h = 180
        self._animating_height = False
        self._grid_snapshot: QPixmap | None = None
        self._pin_rect = QRectF(self.CARD_WIDTH - 34, 9, 20, 20)
        self._hover_pin = False
        self._drop_insert_idx: int | None = None

        self.setFixedWidth(self.CARD_WIDTH)
        self.setMinimumHeight(self.HEADER_HEIGHT)
        self.setMaximumHeight(2000)
        self.setAcceptDrops(not self.is_portal)

        self._grid_container = QWidget(self)
        self._grid_container.setAttribute(Qt.WA_TranslucentBackground, True)
        self._grid_container.setAutoFillBackground(False)
        self._grid_container.setStyleSheet("background: transparent;")
        self._grid_container.setMouseTracking(True)

        self._height_anim = HighRefreshAnimation(self)
        self._height_anim.setDuration(195)
        self._height_anim.setEasingCurve(QEasingCurve.OutQuart)
        self._height_anim.valueChanged.connect(self._on_height_val)
        self._height_anim.finished.connect(self._on_height_anim_finished)

        self._collapse_timer = QTimer(self)
        self._collapse_timer.setSingleShot(True)
        self._collapse_timer.setInterval(500)
        self._collapse_timer.timeout.connect(self._on_collapse_timeout)

        self.reload_items()
        self.resize(self.CARD_WIDTH, self._expanded_height)

    def reload_items(self):
        for child in self._grid_container.findChildren(AuroraIconTile):
            child.deleteLater()

        if self.is_portal:
            files = list_portal_items(
                self.folder_path,
                sort_by=self._portal_sort_provider(self.group_key),
                max_items=self._portal_max_provider(self.group_key),
            )
        else:
            files = list_valid_partition_items(self.folder_path)
            files = sort_group_items(self.group_key, files, self._custom_order_provider(self.group_key))
        self._item_count = len(files)

        rows = max(1, math.ceil(len(files) / self.COLS))
        grid_h = rows * self.TILE_H + max(0, rows - 1) * self.GRID_SPACING_Y + self.GRID_PAD_BOTTOM
        self._expanded_height = self.HEADER_HEIGHT + grid_h
        self._grid_container.setGeometry(0, self.HEADER_HEIGHT, self.CARD_WIDTH, grid_h)

        for idx, f in enumerate(files):
            r = idx // self.COLS
            c = idx % self.COLS
            tile = AuroraIconTile(
                f,
                self.icon_loader,
                compact_capsule=False,
                all_groups=self.all_groups,
                current_group_key=self.group_key,
                is_portal_item=self.is_portal,
                parent=self._grid_container,
            )
            x = self.GRID_PAD_X + c * (self.TILE_W + self.GRID_SPACING_X)
            y = r * (self.TILE_H + self.GRID_SPACING_Y)
            tile.move(x, y)
            tile.show()
            tile.moveRequested.connect(self.itemMoveRequested.emit)
            tile.customizeRequested.connect(lambda p: self.openSettingsRequested.emit("icons", p))
            tile.hoverNameChanged.connect(self._on_tile_hovered)

        self._grid_snapshot = None
        if self._expanded and not self._animating_height:
            self.resize(self.CARD_WIDTH, self._expanded_height)
            self._grid_container.setVisible(True)
            self.heightAnimated.emit()
        self.update()

    def _on_tile_hovered(self, full_name: str):
        self._hovered_item_label = full_name
        self.update()

    def _capture_grid_snapshot(self):
        sz = self._grid_container.size()
        if sz.width() <= 0 or sz.height() <= 0:
            return
        if self._grid_snapshot is None or self._grid_snapshot.size() != sz:
            pm = QPixmap(sz)
            pm.fill(Qt.transparent)
            # Render ONLY children onto 100% transparent RGBA buffer (never DrawWindowBackground which flashes white!)
            for child in self._grid_container.findChildren(AuroraIconTile):
                child.render(pm, child.pos(), QRegion(), QWidget.RenderFlag.DrawChildren)
            self._grid_snapshot = pm

    def _on_height_val(self, val):
        new_h = max(self.HEADER_HEIGHT, int(round(val)))
        if new_h == self._target_anim_h and self.height() == new_h:
            return
        self._target_anim_h = new_h
        # Keep Qt's UpdateLayeredWindow RGBA backing store 100% synced (0 child relayout since _grid_container is hidden)
        self.resize(self.CARD_WIDTH, new_h)
        self.heightAnimated.emit()
        self.update()

    def _on_height_anim_finished(self):
        self._animating_height = False
        final_h = self._expanded_height if self._expanded else self.HEADER_HEIGHT
        self._target_anim_h = final_h
        self.resize(self.CARD_WIDTH, final_h)
        self._grid_container.setVisible(self._expanded)
        self.heightAnimated.emit()
        self.update()

    def desired_stack_height(self) -> int:
        return self._target_anim_h if self._animating_height else self.height()

    def expand_card(self):
        self._collapse_timer.stop()
        if self._expanded and not self._animating_height and self.height() == self._expanded_height:
            return
        start_h = self.desired_stack_height()
        self._expanded = True
        self._capture_grid_snapshot()
        self._grid_container.setVisible(False)
        self._animating_height = True
        self._height_anim.stop()
        self._height_anim.setEasingCurve(QEasingCurve.OutQuart)
        self._height_anim.setDuration(185)
        self._height_anim.setStartValue(start_h)
        self._height_anim.setEndValue(self._expanded_height)
        self._height_anim.start()

    def collapse_card(self, force: bool = False):
        if (self.pinned or self._menu_open) and not force:
            return
        if not self._expanded and not self._animating_height and self.height() == self.HEADER_HEIGHT:
            return
        start_h = self.desired_stack_height()
        self._expanded = False
        self._capture_grid_snapshot()
        self._grid_container.setVisible(False)
        self._animating_height = True
        self._height_anim.stop()
        self._height_anim.setEasingCurve(QEasingCurve.OutQuart)
        self._height_anim.setDuration(195)
        self._height_anim.setStartValue(start_h)
        self._height_anim.setEndValue(self.HEADER_HEIGHT)
        self._height_anim.start()

    def _on_collapse_timeout(self):
        if not self.underMouse() and not self._menu_open and not self.pinned:
            self.collapse_card()

    def enterEvent(self, event):
        self._collapse_timer.stop()
        self.expand_card()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover_pin = False
        if not self.pinned and not self._menu_open:
            self._collapse_timer.start(500)
        super().leaveEvent(event)

    def wheelEvent(self, event):
        if event.angleDelta().y() > 0:
            self.expand_card()
        elif event.angleDelta().y() < 0 and event.position().y() <= self.HEADER_HEIGHT + 12:
            self.collapse_card(force=True)
        super().wheelEvent(event)

    def set_menu_open(self, is_open: bool):
        super().set_menu_open(is_open)
        if not is_open and not self.underMouse() and not self.pinned:
            self._collapse_timer.start(500)

    def mouseMoveEvent(self, event):
        pos = event.position()
        was_hover_pin = self._hover_pin
        self._hover_pin = self._pin_rect.contains(pos)
        if not self._dragging and self._hover_pin != was_hover_pin:
            self.setCursor(Qt.PointingHandCursor if self._hover_pin else Qt.ArrowCursor)
            self.update()

        if self._dragging and (event.buttons() & Qt.LeftButton):
            self._move_smart_drag(event.globalPosition().toPoint(), event.modifiers())
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            pos = event.position()
            if self._pin_rect.contains(pos):
                self.pinned = not self.pinned
                self.pinToggled.emit(self.group_key, self.pinned)
                self.update()
                return
            if pos.y() <= self.HEADER_HEIGHT and self._allow_drag_provider():
                self._begin_smart_drag(event.globalPosition().toPoint())
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton and event.position().y() <= self.HEADER_HEIGHT:
            if self._expanded:
                self.pinned = False
                self.pinToggled.emit(self.group_key, False)
                self.collapse_card(force=True)
            else:
                self.expand_card()
        super().mouseDoubleClickEvent(event)

    def mouseReleaseEvent(self, event):
        self._end_smart_drag()
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event):
        self.set_menu_open(True)
        menu = QMenu(self)
        menu.setStyleSheet(MENU_QSS)

        pin_label = "📌 取消常驻展开 (自动卷起)" if self.pinned else "📌 常驻展开此卡片"
        act_pin = menu.addAction(pin_label)
        act_toggle = menu.addAction("立即卷起为胶囊" if self._expanded else "展开卡片")
        menu.addSeparator()

        act_add = None
        act_add_dir = None
        sys_actions: dict[QAction, str] = {}
        act_refresh_portal = None
        if self.is_portal:
            act_folder = menu.addAction(f"📂 打开映射源目录 ({self.folder_path.name})")
            act_refresh_portal = menu.addAction("🔄 立即刷新目录文件")
        else:
            act_add = menu.addAction("➕ 添加应用 / 文件...")
            act_add_dir = menu.addAction("📁 添加文件夹...")
            sys_menu = menu.addMenu("🖥️ 添加系统图标 (此电脑 / 回收站)")
            sys_menu.setStyleSheet(MENU_QSS)
            sys_actions = {sys_menu.addAction(v["label"]): k for k, v in SYSTEM_SHELL_ITEMS.items()}
            act_folder = menu.addAction(f"📂 打开此分区文件夹 ({self.folder_path.name})")
        menu.addSeparator()
        act_settings = menu.addAction("⚙️ 管理此分组 / 打开设置中心...")
        act_hide = menu.addAction("🙈 隐藏全部桌面卡片")

        chosen = menu.exec(event.globalPos())
        self.set_menu_open(False)

        if chosen == act_pin:
            self.pinned = not self.pinned
            self.pinToggled.emit(self.group_key, self.pinned)
            self.update()
        elif chosen == act_toggle:
            if self._expanded:
                self.collapse_card(force=True)
            else:
                self.expand_card()
        elif act_add is not None and chosen == act_add:
            if prompt_add_items_to_folder(self, self.folder_path):
                self.reload_items()
        elif act_add_dir is not None and chosen == act_add_dir:
            if prompt_add_directory_to_folder(self, self.folder_path):
                self.reload_items()
        elif chosen in sys_actions:
            if create_system_shell_shortcut(sys_actions[chosen], self.folder_path):
                self.reload_items()
        elif act_refresh_portal is not None and chosen == act_refresh_portal:
            self.reload_items()
        elif chosen == act_folder:
            subprocess.Popen(["explorer.exe", str(self.folder_path)])
        elif chosen == act_settings:
            self.openSettingsRequested.emit("groups", self.group_key)
        elif chosen == act_hide:
            self.contextActionTriggered.emit("toggle_visibility")

    def _calc_drop_index(self, pos: QPointF) -> int:
        step_x = self.TILE_W + self.GRID_SPACING_X
        step_y = self.TILE_H + self.GRID_SPACING_Y
        col = max(0, min(self.COLS, int(round((pos.x() - self.GRID_PAD_X) / step_x))))
        row = max(0, int((pos.y() - self.HEADER_HEIGHT) // step_y))
        return max(0, min(self._item_count, row * self.COLS + col))

    def dragEnterEvent(self, event):
        md = event.mimeData()
        if md.hasFormat(AURORA_MIME_TYPE) or md.hasUrls() or has_shell_idlist_mime(md):
            self.expand_card()
            self._drop_insert_idx = self._calc_drop_index(event.position())
            self.update()
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        md = event.mimeData()
        if md.hasFormat(AURORA_MIME_TYPE) or md.hasUrls() or has_shell_idlist_mime(md):
            idx = self._calc_drop_index(event.position())
            if idx != self._drop_insert_idx:
                self._drop_insert_idx = idx
                self.update()
            event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        if self._drop_insert_idx is not None:
            self._drop_insert_idx = None
            self.update()
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        pos = event.position()
        self._drop_insert_idx = None
        self.update()
        md = event.mimeData()
        if md.hasFormat(AURORA_MIME_TYPE):
            raw = bytes(md.data(AURORA_MIME_TYPE)).decode("utf-8", errors="ignore")
            if "|" in raw:
                src_grp, src_path_str = raw.split("|", 1)
                src_path = Path(src_path_str)
                if src_grp == self.group_key:
                    files = sort_group_items(self.group_key, list_valid_partition_items(self.folder_path), self._custom_order_provider(self.group_key))
                    names = [p.name for p in files if p.name != src_path.name]
                    col = max(0, min(self.COLS - 1, int((pos.x() - self.GRID_PAD_X) // (self.TILE_W + self.GRID_SPACING_X))))
                    row = max(0, int((pos.y() - self.HEADER_HEIGHT) // (self.TILE_H + self.GRID_SPACING_Y)))
                    target_idx = max(0, min(len(names), row * self.COLS + col))
                    names.insert(target_idx, src_path.name)
                    self.orderChanged.emit(self.group_key, names)
                    self.reload_items()
                    return
                elif src_path.exists():
                    self.itemMoveRequested.emit(src_path, self.group_key)
                    return

        imported_any = False
        for url in md.urls():
            local_str = url.toLocalFile()
            if local_str:
                local = Path(local_str)
                if local.exists():
                    import_item_into_group_folder(local, self.folder_path)
                    imported_any = True
        if not imported_any:
            import_shell_idlist_drop(md, self.folder_path)
        self.reload_items()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)

        c1, _, c2 = self.get_theme_colors()

        # 1. Glowing Aurora indicator on header left (rounded folder badge for Portal, dot for standard card)
        if self.is_portal:
            p_rect = QRectF(12.0, (self.HEADER_HEIGHT - 10.0) / 2.0, 11.0, 9.0)
            painter.setPen(QPen(c1, 1.3))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(p_rect, 2.0, 2.0)
            painter.drawLine(QPointF(13.5, p_rect.top() - 1.5), QPointF(17.5, p_rect.top() - 1.5))
        else:
            dot_rect = QRectF(14.0, (self.HEADER_HEIGHT - 7.0) / 2.0, 7.0, 7.0)
            dot_grad = QLinearGradient(dot_rect.topLeft(), dot_rect.bottomRight())
            dot_grad.setColorAt(0.0, c1)
            dot_grad.setColorAt(1.0, c2)
            painter.setPen(Qt.NoPen)
            painter.setBrush(dot_grad)
            painter.drawEllipse(dot_rect)

        # 2. Apple Widget style crisp SemiBold sans-serif category title
        font = make_apple_font(12, QFont.DemiBold, 0.65)
        painter.setFont(font)

        title_rect = QRectF(28.0, 0.0, 230.0, float(self.HEADER_HEIGHT))
        painter.setPen(QColor(0, 0, 0, 115))
        painter.drawText(title_rect.translated(0, 1.0), Qt.AlignLeft | Qt.AlignVCenter, self.title)

        title_alpha = int(232 + 23 * self._border_glow)
        painter.setPen(QColor(255, 255, 255, title_alpha))
        painter.drawText(title_rect, Qt.AlignLeft | Qt.AlignVCenter, self.title)

        # 3. Instant hover full-name reveal OR item count pill on right
        if self._hovered_item_label and self._expanded:
            hov_font = make_apple_font(11, QFont.Medium, 0.0)
            painter.setFont(hov_font)
            fm = QFontMetrics(hov_font)
            hov_text = fm.elidedText(self._hovered_item_label, Qt.ElideRight, 138)
            hov_rect = QRectF(self.width() - 180.0, 0.0, 140.0, float(self.HEADER_HEIGHT))
            painter.setPen(QColor(0, 0, 0, 110))
            painter.drawText(hov_rect.translated(0, 1.0), Qt.AlignRight | Qt.AlignVCenter, hov_text)
            hov_col = QColor(c1).lighter(135)
            hov_col.setAlpha(245)
            painter.setPen(hov_col)
            painter.drawText(hov_rect, Qt.AlignRight | Qt.AlignVCenter, hov_text)
        else:
            cnt_font = make_apple_font(11, QFont.Medium, 0.0)
            painter.setFont(cnt_font)
            painter.setPen(QColor(220, 232, 248, int(135 + 65 * self._border_glow)))
            cnt_rect = QRectF(self.width() - 66.0, 0.0, 26.0, float(self.HEADER_HEIGHT))
            painter.drawText(cnt_rect, Qt.AlignRight | Qt.AlignVCenter, str(self._item_count))

        # 4. Pin / Auto-collapse indicator button
        if self.pinned or self._border_glow > 0.05:
            cx, cy = self._pin_rect.center().x(), self._pin_rect.center().y()
            if self.pinned:
                p_fill = QColor(c1); p_fill.setAlpha(210)
                p_ring = QColor(c1); p_ring.setAlpha(120)
                painter.setBrush(p_fill)
                painter.setPen(QPen(p_ring, 2.0))
                painter.drawEllipse(QPointF(cx, cy), 4.0, 4.0)
            else:
                alpha = 190 if self._hover_pin else int(95 * self._border_glow)
                painter.setBrush(Qt.NoBrush)
                painter.setPen(QPen(QColor(220, 235, 255, alpha), 1.2))
                painter.drawEllipse(QPointF(cx, cy), 4.0, 4.0)

        # 5. Subtle hairline divider + fast 240Hz cached grid snapshot during roll-up/expand animation!
        cur_h = self.height()
        if cur_h > self.HEADER_HEIGHT + 8:
            div_grad = QLinearGradient(14.0, 0.0, self.width() - 14.0, 0.0)
            dc1 = QColor(c1); dc1.setAlpha(44)
            dc2 = QColor(c2); dc2.setAlpha(38)
            div_grad.setColorAt(0.0, dc1)
            div_grad.setColorAt(0.5, QColor(255, 255, 255, 20))
            div_grad.setColorAt(1.0, dc2)
            painter.setPen(QPen(div_grad, 1.0))
            painter.drawLine(
                QPointF(14.0, float(self.HEADER_HEIGHT)),
                QPointF(self.width() - 14.0, float(self.HEADER_HEIGHT)),
            )

            if self._animating_height and self._grid_snapshot is not None and not self._grid_snapshot.isNull():
                span = max(1.0, float(self._expanded_height - self.HEADER_HEIGHT))
                prog = max(0.0, min(1.0, (cur_h - self.HEADER_HEIGHT) / span))
                painter.save()
                clip_r = QRectF(1.0, float(self.HEADER_HEIGHT + 1), self.width() - 2.0, max(0.0, cur_h - self.HEADER_HEIGHT - 4.0))
                painter.setClipRect(clip_r)
                painter.setOpacity(prog * prog)
                # Subtle 6px vertical glide during unfold
                y_offset = -6.0 * (1.0 - prog)
                painter.drawPixmap(QPointF(0.0, float(self.HEADER_HEIGHT) + y_offset), self._grid_snapshot)
                painter.restore()

        # 6. Live drag-to-reorder glowing insertion indicator bar
        if self._drop_insert_idx is not None and self._expanded and cur_h > self.HEADER_HEIGHT + 20:
            idx = max(0, min(self._item_count, self._drop_insert_idx))
            row = idx // self.COLS
            col = idx % self.COLS
            if idx == self._item_count and self._item_count > 0 and col == 0:
                # Place right after the last tile of the previous full row
                row = (idx - 1) // self.COLS
                col = self.COLS
            step_x = self.TILE_W + self.GRID_SPACING_X
            step_y = self.TILE_H + self.GRID_SPACING_Y
            ix = self.GRID_PAD_X + col * step_x - self.GRID_SPACING_X / 2.0
            y1 = float(self.HEADER_HEIGHT + row * step_y + 8)
            y2 = min(float(cur_h - 10), y1 + self.TILE_H - 16.0)
            if y2 > y1 + 6.0:
                halo = QColor(c1); halo.setAlpha(95)
                painter.setPen(QPen(halo, 6.0, Qt.SolidLine, Qt.RoundCap))
                painter.drawLine(QPointF(ix, y1), QPointF(ix, y2))
                igrad = QLinearGradient(ix, y1, ix, y2)
                igrad.setColorAt(0.0, c1)
                igrad.setColorAt(1.0, c2)
                painter.setPen(QPen(igrad, 2.4, Qt.SolidLine, Qt.RoundCap))
                painter.drawLine(QPointF(ix, y1), QPointF(ix, y2))
                painter.setBrush(QColor(255, 255, 255, 240))
                painter.setPen(Qt.NoPen)
                painter.drawEllipse(QPointF(ix, y1), 2.5, 2.5)
                painter.drawEllipse(QPointF(ix, y2), 2.5, 2.5)
