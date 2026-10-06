"""Traduce fixtures.json a inglés (equipos, ciudades, placeholders). One-shot."""
import json
import re

TEAMS = {
    "México": "Mexico", "Sudáfrica": "South Africa", "Corea del Sur": "South Korea",
    "República Checa": "Czech Republic", "Canadá": "Canada",
    "Bosnia y Herzegovina": "Bosnia and Herzegovina", "Qatar": "Qatar",
    "Suiza": "Switzerland", "Brasil": "Brazil", "Marruecos": "Morocco",
    "Haití": "Haiti", "Escocia": "Scotland", "Estados Unidos": "United States",
    "Paraguay": "Paraguay", "Australia": "Australia", "Turquía": "Türkiye",
    "Alemania": "Germany", "Curazao": "Curaçao", "Costa de Marfil": "Ivory Coast",
    "Ecuador": "Ecuador", "Países Bajos": "Netherlands", "Japón": "Japan",
    "Suecia": "Sweden", "Túnez": "Tunisia", "Bélgica": "Belgium", "Egipto": "Egypt",
    "Irán": "Iran", "Nueva Zelanda": "New Zealand", "España": "Spain",
    "Cabo Verde": "Cape Verde", "Arabia Saudita": "Saudi Arabia", "Uruguay": "Uruguay",
    "Francia": "France", "Senegal": "Senegal", "Irak": "Iraq", "Noruega": "Norway",
    "Argentina": "Argentina", "Argelia": "Algeria", "Austria": "Austria",
    "Jordania": "Jordan", "Portugal": "Portugal", "RD del Congo": "DR Congo",
    "Uzbekistán": "Uzbekistan", "Colombia": "Colombia", "Inglaterra": "England",
    "Croacia": "Croatia", "Ghana": "Ghana", "Panamá": "Panama",
}
CITIES = {
    "Ciudad de México": "Mexico City", "Filadelfia": "Philadelphia",
    "Los Ángeles": "Los Angeles", "Nueva York/Nueva Jersey": "New York/New Jersey",
}


def placeholder(p):
    if not p:
        return p
    p = re.sub(r"^1° Grupo ([A-L])$", r"Group \1 winner", p)
    p = re.sub(r"^2° Grupo ([A-L])$", r"Group \1 runner-up", p)
    p = re.sub(r"^Mejor 3° \(([^)]+)\)$", r"Best 3rd (\1)", p)
    p = re.sub(r"^Mejor 3°(.*)$", r"Best 3rd\1", p)
    p = re.sub(r"^Ganador P(\d+)$", r"Winner M\1", p)
    p = re.sub(r"^Perdedor P(\d+)$", r"Loser M\1", p)
    return p


path = "data/fixtures.json"
d = json.load(open(path, encoding="utf-8"))
for t in d["teams"]:
    t["name"] = TEAMS[t["name"]]
for m in d["matches"]:
    if m.get("city") in CITIES:
        m["city"] = CITIES[m["city"]]
    m["home_placeholder"] = placeholder(m.get("home_placeholder"))
    m["away_placeholder"] = placeholder(m.get("away_placeholder"))
json.dump(d, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

leftover = [t["name"] for t in d["teams"] if any(ch in t["name"] for ch in "áéíóúñ°")]
print("done. leftover non-translated:", leftover or "none")
ph = sorted({p for m in d["matches"] for p in (m["home_placeholder"], m["away_placeholder"]) if p})
print("sample placeholders:", ph[:6], ph[-4:])
