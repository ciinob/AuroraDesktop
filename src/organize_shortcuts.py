import shutil
import sys
from pathlib import Path
import win32com.client

_SRC_DIR = Path(__file__).resolve().parent
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from paths import DATA_ROOT, GROUPS_DIR

BASE_DIR = DATA_ROOT
REMOVED_DIR = DATA_ROOT / "Removed_Backup"

GROUP_FOLDERS = {
    "AI_CAPSULE": GROUPS_DIR / "01_AI_CAPSULE",
    "RESEARCH_DEV": GROUPS_DIR / "02_RESEARCH_DEV",
    "PLAY_SOCIAL": GROUPS_DIR / "03_PLAY_SOCIAL",
    "TOOLS_NET": GROUPS_DIR / "04_TOOLS_NET",
}

AI_KEYWORDS = [
    "gemini", "claude", "chatgpt", "deepseek", "grok", "codex", "openai"
]

RESEARCH_KEYWORDS = [
    "matlab", "zotero", "visual studio code", "vscode", "code.exe",
    "antigravity", "word", "excel", "powerpoint", "wps",
    "数学知识图谱", "math-taxonomy", "cc-switch", "workbuddy", "workdaddy",
    "腾讯会议", "wemeet"
]

PLAY_KEYWORDS = [
    "steam", "rockstar", "plain craft launcher", "pcl", "kook", "oopz",
    "qq", "微信", "weixin", "telegram", "wegame", "暴雪战网", "battle.net",
    "完美世界竞技平台", "perfectworldarena", "leagueakari",
    "外星仔加速器", "etalien", "外星仔联机助手", "xingwailan",
    "网易云音乐", "cloudmusic", "libretv", "短剧播放器", "红果短剧", "pavise"
]

TOOLS_KEYWORDS = [
    "clash verge", "clash-verge", "proxyswitch", "aria2", "剪映", "jianying",
    "logitech", "lghub", "inzone", "g-menu", "gmenu", "cutecloud",
    "microsoft edge", "msedge", "夸克网盘", "quark", "图吧工具箱",
    "火绒", "huorong", "hipsmain", "rainmeter", "translucenttb", "ttb.exe"
]

SYSTEM_SKIP_NAMES = {
    "desktop.ini", "此电脑.lnk", "回收站.lnk", "控制面板.lnk", "网络.lnk",
    "this pc.lnk", "recycle bin.lnk", "control panel.lnk", "network.lnk"
}


def resolve_shortcut_info(lnk_path: Path, shell) -> str:
    try:
        sc = shell.CreateShortcut(str(lnk_path))
        target = sc.TargetPath or ""
        args = sc.Arguments or ""
        desc = sc.Description or ""
        return f"{lnk_path.stem} {target} {args} {desc}".lower()
    except Exception:
        return lnk_path.stem.lower()


def classify_shortcut(lnk_path: Path, info: str) -> str:
    stem_lower = lnk_path.stem.lower()

    for kw in AI_KEYWORDS:
        if kw in stem_lower or kw in info:
            if any(x in stem_lower for x in ["cc-switch", "workbuddy", "workdaddy", "antigravity"]):
                return "RESEARCH_DEV"
            return "AI_CAPSULE"

    for kw in RESEARCH_KEYWORDS:
        if kw in stem_lower or kw in info:
            return "RESEARCH_DEV"

    for kw in PLAY_KEYWORDS:
        if kw in stem_lower or kw in info:
            return "PLAY_SOCIAL"

    for kw in TOOLS_KEYWORDS:
        if kw in stem_lower or kw in info:
            return "TOOLS_NET"

    return "TOOLS_NET"


def scan_and_organize() -> dict:
    for folder in GROUP_FOLDERS.values():
        folder.mkdir(parents=True, exist_ok=True)
    REMOVED_DIR.mkdir(parents=True, exist_ok=True)

    shell = win32com.client.Dispatch("WScript.Shell")
    user_desktop = Path(shell.SpecialFolders("Desktop"))
    public_desktop = Path(shell.SpecialFolders("AllUsersDesktop"))

    already_managed = set()
    for folder in list(GROUP_FOLDERS.values()) + [REMOVED_DIR]:
        if folder.exists():
            for existing in folder.iterdir():
                already_managed.add(existing.name.lower())

    seen_names = set(already_managed)
    summary = {k: [] for k in GROUP_FOLDERS}

    for source_label, desktop_dir in [("USER", user_desktop), ("PUBLIC", public_desktop)]:
        if not desktop_dir.exists():
            continue
        for item in sorted(desktop_dir.iterdir(), key=lambda p: p.name.lower()):
            if item.name.lower() in SYSTEM_SKIP_NAMES:
                continue
            if item.suffix.lower() not in (".lnk", ".url"):
                continue

            dedup_key = item.name.lower()
            if dedup_key in seen_names:
                continue
            seen_names.add(dedup_key)

            info = resolve_shortcut_info(item, shell)
            group_key = classify_shortcut(item, info)
            dest_dir = GROUP_FOLDERS[group_key]
            dest_path = dest_dir / item.name

            shutil.copy2(item, dest_path)
            summary[group_key].append((source_label, item.name))

    return summary


if __name__ == "__main__":
    result = scan_and_organize()
    total = sum(len(items) for items in result.values())
    print(f"TOTAL ORGANIZED SHORTCUTS: {total}")
