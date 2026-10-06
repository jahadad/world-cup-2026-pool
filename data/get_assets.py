"""Genera assets: banderas (flagcdn) e iconos PWA. Correr una vez en dev."""
import math
import time
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw

ISO2 = {
    "ALG": "dz", "ARG": "ar", "AUS": "au", "AUT": "at", "BEL": "be", "BIH": "ba",
    "BRA": "br", "CAN": "ca", "CIV": "ci", "COD": "cd", "COL": "co", "CPV": "cv",
    "CRO": "hr", "CUR": "cw", "CZE": "cz", "ECU": "ec", "EGY": "eg", "ENG": "gb-eng",
    "ESP": "es", "FRA": "fr", "GER": "de", "GHA": "gh", "HAI": "ht", "IRN": "ir",
    "IRQ": "iq", "JOR": "jo", "JPN": "jp", "KOR": "kr", "KSA": "sa", "MAR": "ma",
    "MEX": "mx", "NED": "nl", "NOR": "no", "NZL": "nz", "PAN": "pa", "PAR": "py",
    "POR": "pt", "QAT": "qa", "RSA": "za", "SCO": "gb-sct", "SEN": "sn", "SUI": "ch",
    "SWE": "se", "TUN": "tn", "TUR": "tr", "URY": "uy", "USA": "us", "UZB": "uz",
}

flags_dir = Path("prode/static/flags")
flags_dir.mkdir(parents=True, exist_ok=True)
for code, iso in ISO2.items():
    dest = flags_dir / f"{code}.png"
    if dest.exists():
        continue
    url = f"https://flagcdn.com/w160/{iso}.png"
    urllib.request.urlretrieve(url, dest)
    print("flag", code)
    time.sleep(0.2)
print("flags:", len(list(flags_dir.glob('*.png'))))

BLUE = (52, 131, 250, 255)
DARK = (26, 28, 41, 255)

def ball(d, c, br, lw):
    d.ellipse([c - br, c - br, c + br, c + br], fill="white", outline=DARK, width=lw)
    pr = br * 0.42
    pts = [(c + pr * math.sin(2 * math.pi * i / 5), c - pr * math.cos(2 * math.pi * i / 5))
           for i in range(5)]
    d.polygon(pts, fill=DARK)
    for x, y in pts:
        dx, dy = x - c, y - c
        n = math.hypot(dx, dy)
        d.line([x, y, c + dx / n * br, c + dy / n * br], fill=DARK, width=lw)

icons_dir = Path("prode/static/icons")
icons_dir.mkdir(parents=True, exist_ok=True)
for size, rounded, name in [(192, True, "icon-192.png"), (512, True, "icon-512.png"),
                            (180, False, "apple-touch-icon.png")]:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    radius = int(size * 0.22) if rounded else 0
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=BLUE)
    ball(d, size / 2, size * 0.30, max(2, size // 56))
    if not rounded:
        img = img.convert("RGB")
    img.save(icons_dir / name)
    print("icon", name)
