from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter

ASSETS_DIR = Path(r"D:\AuroraDesktop\assets")
ASSETS_DIR.mkdir(parents=True, exist_ok=True)


def create_aurora_icon(out_path: Path):
    size = 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Dark glass squircle base
    margin = 16
    draw.rounded_rectangle(
        [margin, margin, size - margin, size - margin],
        radius=56,
        fill=(10, 15, 28, 235),
    )

    # Aurora glow layer
    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow)

    # Emerald (#2dd4bf) to Nebula Purple (#a855f7) diagonal aurora ribbons
    gdraw.ellipse([36, 48, 175, 195], fill=(45, 212, 191, 165))
    gdraw.ellipse([85, 65, 224, 210], fill=(168, 85, 247, 165))
    gdraw.ellipse([65, 35, 195, 145], fill=(56, 189, 248, 130))
    glow = glow.filter(ImageFilter.GaussianBlur(26))

    # Mask glow inside squircle
    mask = Image.new("L", (size, size), 0)
    mdraw = ImageDraw.Draw(mask)
    mdraw.rounded_rectangle([margin, margin, size - margin, size - margin], radius=56, fill=255)
    img = Image.composite(Image.alpha_composite(img, glow), img, mask)

    # Minimalist glass grid cards motif inside icon
    fg = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    fdraw = ImageDraw.Draw(fg)
    # Top AI capsule pill
    fdraw.rounded_rectangle([56, 62, 200, 96], radius=17, fill=(255, 255, 255, 225))
    # Two glass cards below
    fdraw.rounded_rectangle([56, 116, 200, 150], radius=12, fill=(255, 255, 255, 155))
    fdraw.rounded_rectangle([56, 166, 168, 196], radius=12, fill=(45, 212, 191, 190))

    # Crisp border stroke
    for i, col in enumerate([(45, 212, 191, 220), (168, 85, 247, 180)]):
        fdraw.rounded_rectangle(
            [margin + i, margin + i, size - margin - i, size - margin - i],
            radius=56 - i,
            outline=col,
            width=3,
        )

    final = Image.alpha_composite(img, fg)
    final.save(out_path, format="ICO", sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
    final.save(ASSETS_DIR / "aurora.png", format="PNG")
    print(f"Generated icon: {out_path}")


if __name__ == "__main__":
    create_aurora_icon(ASSETS_DIR / "aurora.ico")
