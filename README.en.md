<div align="center">

<img src="assets/aurora.png" width="96" alt="Aurora Desktop Logo"/>

# Aurora Desktop

**A Windows 11 desktop aesthetics suite: frosted-glass organizer · media capsule · global search · artistic clock · fully transparent taskbar**

[![Platform](https://img.shields.io/badge/Platform-Windows%2011-0078D4?logo=windows11&logoColor=white)](https://www.microsoft.com/windows)
[![Release](https://img.shields.io/github/v/release/ciinob/AuroraDesktop?color=2dd4bf&label=Release)](https://github.com/ciinob/AuroraDesktop/releases)
[![Built with](https://img.shields.io/badge/Built%20with-PySide6%20%2B%20C%2B%2B-a855f7)](https://github.com/ciinob/AuroraDesktop)

**[中文文档](README.md)** | English | **[Changelog](CHANGELOG.md)**

Single-file, portable, auto-starts with Windows. Double-click `AuroraDesktop.exe` and your desktop is instantly reborn.

</div>

---

## ✨ What is it

Aurora Desktop is a desktop enhancement suite crafted for dark wallpapers: it sweeps your cluttered desktop icons into **frosted-glass capsule cards**, launches anything in milliseconds with a **Spotlight-style global search**, pins a **haute-couture artistic clock** to your desktop, and gives you a **truly transparent taskbar** that lets the wallpaper shine through.

No bloated framework, no heavyweight background service — one exe does it all.

## 📸 Screenshots

![Aurora Desktop overview: capsules, artistic clock & transparent taskbar](docs/images/hero-desktop.jpg)

![Frosted capsule cards: AI bar & auto-grouped organizer](docs/images/capsule-cards.png)

![Full view: AI / Dev / Play / Tools capsules on the wallpaper](docs/images/capsule-full.jpg)

## 🚀 Five Core Powers

### 🔍 Aurora Spotlight (Global Search)
From anywhere, **double-tap `Ctrl`** (or press `Alt + S`) to summon it instantly:

![Aurora Spotlight: pinyin-initial & fuzzy matching](docs/images/spotlight-search.png)

- **Pinyin-initial fuzzy matching**: type `wx` for WeChat, `wyy` for NetEase Cloud Music, `vsc` for VS Code
- **Full coverage**: apps / PDFs / images / folders inside your capsules, plus everything in the Start Menu
- **Instant calculator**: `128 * 4.5`, `sqrt(2)`, `sin(pi/4)` — press Enter to copy the result
- **System commands**: type `lock` to lock the screen, `ip` to copy your IPv4, or hit Enter on any query to search the web

| Key | Action |
| --- | --- |
| `↑` / `↓` | Select result |
| `Enter` | Open |
| `Ctrl + Enter` | Run as administrator |
| `Alt + Enter` | Open file location |
| `Esc` | Close |

### 🧊 Frosted Capsule Organizer, Smart Guides & Layout Presets
- Desktop icons are auto-grouped into frosted-glass cards (**AI / Dev / Play / Tools / Documents**) with auto roll-up and multi-monitor safe bounds clamping
- **🧲 Smart Guides & Magnetic Snap Preview**: dragging any capsule, card, media bar, or clock reveals live edge/center guides, Figma-style equal-spacing callouts, and a glowing snap-target preview (hold `Alt` to temporarily bypass snapping)
- **📐 Multi-Layout Presets**: switch between built-in **Left Golden / Dual Wings / Zen Minimal** layouts or save/restore unlimited custom desktop layouts
- **📂 Live Folder Portals**: map `Downloads`, screenshots, or active project folders straight onto your desktop — newest files surface automatically and can be dragged right into chat or browser uploads
- **✨ One-click Native Desktop Icon Hiding & Dynamic Recycle Bin**: hide cluttered Windows desktop icons non-destructively (auto-restored on exit), with built-in This PC & live empty/full Recycle Bin tiles
- **Live Drop Indicators & Custom Icons**: drag-to-reorder renders a glowing aurora insertion bar; override any item with PNG / ICO / EXE icons refracting adaptive brand-color halos
- 4 aurora color temperatures × 3 glass opacity levels in the Control Center

### 🎵 Aurora Media Capsule (Windows SMTC)
- Automatically detects active playback from **NetEase Cloud Music / Apple Music / Spotify / QQ Music / Edge / Chrome / Firefox / Bilibili**, prioritizing dedicated music players
- **Album-Cover Adaptive Backlight**: samples dominant artwork hues for a dynamic aurora backlight and accent rim, paired with crisp high-contrast typography and a 2px progress hairline
- **Hover Controls & Source Switching**: reveals Prev / Play-Pause / Next controls on hover; scroll the mouse wheel or right-click to switch between multiple active media sessions

### 🕒 Haute-Couture Desktop Clock
8 hand-tuned typographic styles. Colons and hairlines follow the active aurora theme; ticking is aligned to second/minute boundaries (one repaint per minute when seconds are hidden — zero idle cost):

| Style | Typeface |
| --- | --- |
| ✨ Nordic Modern | Outfit ExtraLight |
| 🌈 Aurora Gradient | Outfit Light (theme gradient fill) |
| 🌌 Aurora Calligraphy | Playfair Display Italic × Great Vibes |
| 🏛️ Editorial Serif | Cormorant Garamond |
| 🕰️ Roman Inscription | Cormorant Italic · Roman numerals |
| 🖌️ Eastern Ink | STXingkai · sexagenary year, solar terms & vermilion seal |
| 🍎 macOS Sonoma | Outfit Light |
| ✍️ Script Layered | Ruthligos |

All 8 styles on a dark wallpaper:

![Clock styles on dark wallpaper](docs/images/clock-styles-dark.png)

Still perfectly legible on bright wallpapers (multi-layer soft halo):

![Clock styles on light wallpaper](docs/images/clock-styles-light.png)

### 🪟 Dynamic Transparent Taskbar Engine & Multi-Monitor Recovery
A custom C++ native engine (`AuroraTaskbarTAP.dll`, combining XAML `BackgroundFill` with Win32 `ACCENT_ENABLE_TRANSPARENTGRADIENT`) makes the taskbar genuinely disappear on the desktop, while **automatically switching to dark frosted acrylic whenever a window is maximized** for crisp legibility against bright apps. Built-in display-topology cooldown prevents DWM gray-screen hangs on monitor disconnect and rescues stranded widgets back onto the active screen.

## 📦 Install

1. Grab `AuroraDesktop.exe` from [**Releases**](https://github.com/ciinob/AuroraDesktop/releases)
2. Double-click `AuroraDesktop.exe` to open the **Aurora Control Center** (while mounting your desktop capsules, clock & transparent taskbar):
   - **Capsule groups**: create, rename, switch card/bar layout, reorder, and delete groups
   - **Custom icons**: override any item with PNG / ICO / EXE icons + live adaptive halo preview
   - **Global hotkeys**: interactive shortcut recorder with conflict detection & **silent auto-start toggle**
   - **Appearance, clock & taskbar**: 4 aurora palettes, 3 glass opacity levels, 8 clock styles & taskbar transparency
3. Closing the Control Center leaves the desktop widgets running in the background; **re-opening the exe, left-clicking the tray icon, clicking the ⚙️ gear button on the top AI bar, or pressing `Alt + ,`** brings the Control Center right back.

> Requirement: Windows 11 (verified on 24H2)
>
> Portable builds keep `config.json`, `Groups/` and `memo.txt` next to the exe; if installed in a read-only directory (e.g. Program Files), data moves to `%APPDATA%\AuroraDesktop`. Use the tray menu "🔄 Check for updates" to see new releases.

## 🛠️ Run from Source

```bash
pip install -r requirements.txt   # PySide6 / pywin32 / pyinstaller / Pillow
python src/main.py                # or scripts\dev_run.bat for debugging
scripts\rebuild_exe.bat           # PyInstaller build + hot-swap exe
```

## 🧱 Tech Stack

- **UI**: Python 3.13 + PySide6 (custom frosted glass, QPainterPath text halos, high-refresh animations)
- **Native layer**: C++ XAML taskbar engine + Win32 API (desktop pinning, click-through, global hotkeys); rebuild the DLL from source via `src/native/CMakeLists.txt`
- **Typography**: Outfit / Cormorant Garamond / Playfair Display / Great Vibes / Ruthligos / STXingkai — all bundled
- **CI**: GitHub Actions builds the exe and publishes a Release with a SHA256 checksum on every version tag

## 📄 License

Application source is [MIT](LICENSE); bundled fonts keep their own licenses — see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

---

<div align="center">
If it makes your desktop a little prettier, a ⭐ Star means a lot
</div>
