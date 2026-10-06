"""Descarga las fuentes (woff2, subset latin) para servirlas desde la app."""
import re
import urllib.request
from pathlib import Path

CSS_URL = (
    "https://fonts.googleapis.com/css2"
    "?family=Barlow:wght@400;500;600;700"
    "&family=Barlow+Condensed:wght@600;700&display=swap"
)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"

req = urllib.request.Request(CSS_URL, headers={"User-Agent": UA})
css = urllib.request.urlopen(req, timeout=30).read().decode()

out = Path("prode/static/fonts")
out.mkdir(parents=True, exist_ok=True)
faces = []
# Bloques: /* latin */ @font-face { font-family: 'X'; font-weight: N; src: url(...woff2) ... unicode-range: ... }
for block in re.findall(r"/\* (\w+) \*/\s*@font-face\s*\{([^}]+)\}", css):
    subset, body = block
    if subset != "latin":
        continue
    family = re.search(r"font-family: '([^']+)'", body).group(1)
    weight = re.search(r"font-weight: (\d+)", body).group(1)
    url = re.search(r"url\((https://[^)]+\.woff2)\)", body).group(1)
    fname = f"{family.replace(' ', '')}-{weight}.woff2"
    urllib.request.urlretrieve(url, out / fname)
    faces.append((family, weight, fname))
    print("font", fname)

print("\n--- CSS para base.html ---")
for family, weight, fname in faces:
    print(
        f"@font-face {{ font-family: '{family}'; font-style: normal; font-weight: {weight}; "
        f"font-display: swap; src: url({{% static 'fonts/{fname}' %}}) format('woff2'); }}"
    )
