# -*- coding: utf-8 -*-
"""Render all clock styles offscreen to PNGs for visual review."""
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QFontDatabase, QGuiApplication, QImage, QLinearGradient, QPainter
from PySide6.QtWidgets import QApplication

app = QGuiApplication.instance() or QApplication(sys.argv)

FONTS = ROOT / "assets" / "fonts"
for fp in sorted(FONTS.glob("*.ttf")):
    fid = QFontDatabase.addApplicationFont(str(fp))
    fams = QFontDatabase.applicationFontFamilies(fid)
    print(fp.name, "->", fams)

from clock_widget import AuroraClockWidget, CLOCK_STYLES  # noqa: E402


def theme():
    return QColor("#2dd4bf"), QColor("#38bdf8"), QColor("#a855f7")


OUT = ROOT / "_clock_preview"
OUT.mkdir(exist_ok=True)

SCALE = 1.3
for style in CLOCK_STYLES:
    cfg = {"style": style, "scale": SCALE, "use_24h": True, "show_seconds": False}
    w = AuroraClockWidget(cfg, theme_provider=theme)
    img = QImage(w.width(), w.height(), QImage.Format_ARGB32_Premultiplied)
    for bg_name in ("dark", "light"):
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        # fake wallpaper gradient
        g = QLinearGradient(0, 0, img.width(), img.height())
        if bg_name == "dark":
            g.setColorAt(0.0, QColor(12, 20, 38))
            g.setColorAt(1.0, QColor(30, 14, 50))
        else:
            g.setColorAt(0.0, QColor(200, 215, 235))
            g.setColorAt(1.0, QColor(235, 220, 210))
        p.fillRect(img.rect(), g)
        w.render(p, QPoint(0, 0))
        p.end()
        img.save(str(OUT / f"{style}_{bg_name}.png"))
    print("rendered", style, w.width(), w.height())

# contact sheet: dark versions stacked
imgs = []
from PySide6.QtGui import QPixmap
for style in CLOCK_STYLES:
    imgs.append((style, QPixmap(str(OUT / f"{style}_dark.png"))))
W = max(i.width() for _, i in imgs)
H = sum(i.height() + 28 for _, i in imgs) + 8
sheet = QImage(W, H, QImage.Format_ARGB32_Premultiplied)
sheet.fill(Qt.transparent)
p = QPainter(sheet)
p.setRenderHint(QPainter.Antialiasing)
g = QLinearGradient(0, 0, W, H)
g.setColorAt(0.0, QColor(12, 20, 38))
g.setColorAt(1.0, QColor(30, 14, 50))
p.fillRect(sheet.rect(), g)
y = 4
p.setPen(QColor(255, 255, 255, 180))
fnt = p.font(); fnt.setPixelSize(13); p.setFont(fnt)
for style, pm in imgs:
    p.drawText(6, y + 14, style)
    p.drawPixmap(0, y + 22, pm)
    y += pm.height() + 28
p.end()
sheet.save(str(OUT / "sheet_dark.png"))

sheet2 = QImage(W, H, QImage.Format_ARGB32_Premultiplied)
sheet2.fill(Qt.transparent)
p = QPainter(sheet2)
g = QLinearGradient(0, 0, W, H)
g.setColorAt(0.0, QColor(205, 218, 238))
g.setColorAt(1.0, QColor(238, 222, 212))
p.fillRect(sheet2.rect(), g)
y = 4
p.setPen(QColor(30, 30, 40, 200))
for style in CLOCK_STYLES:
    pm = QPixmap(str(OUT / f"{style}_light.png"))
    p.drawText(6, y + 14, style)
    p.drawPixmap(0, y + 22, pm)
    y += pm.height() + 28
p.end()
sheet2.save(str(OUT / "sheet_light.png"))
print("done ->", OUT)
