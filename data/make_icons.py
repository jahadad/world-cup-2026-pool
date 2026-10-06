"""Genera iconos PWA y favicon desde el logo oficial. Correr una vez en dev."""
import sys
from pathlib import Path

from PIL import Image

src = Image.open(sys.argv[1]).convert("RGB")

# Recorte del fondo blanco
gray = src.convert("L").point(lambda p: 0 if p > 245 else 255)
bbox = gray.getbbox()
logo = src.crop(bbox)

# Lienzo cuadrado blanco con margen del 12%
side = int(max(logo.size) * 1.24)
canvas = Image.new("RGB", (side, side), "white")
canvas.paste(logo, ((side - logo.width) // 2, (side - logo.height) // 2))

icons_dir = Path("prode/static/icons")
icons_dir.mkdir(parents=True, exist_ok=True)
for size, name in [(512, "icon-512.png"), (192, "icon-192.png"),
                   (180, "apple-touch-icon.png"), (48, "favicon-48.png")]:
    canvas.resize((size, size), Image.LANCZOS).save(icons_dir / name)
    print("icon", name)
