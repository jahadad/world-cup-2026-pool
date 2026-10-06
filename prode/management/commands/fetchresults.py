import json
import os
import urllib.request
from datetime import datetime, timedelta

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from prode.models import Match, Team

FD_URL = "https://api.football-data.org/v4/competitions/WC/matches"
ESPN_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard?dates={date}"

# Inconsistencias de códigos entre fuentes (p.ej. Curazao: CUW en algunos
# endpoints, CUR en otros; Uruguay: URU en las APIs, URY en nuestro fixture).
# Normalizamos al código de nuestro fixture.
TLA_ALIASES = {"CUW": "CUR", "URU": "URY"}


def _norm(code):
    return TLA_ALIASES.get(code, code)


# Etapas de eliminación según football-data.org → nuestras etapas
STAGE_MAP = {
    "LAST_32": "R32",
    "LAST_16": "R16",
    "QUARTER_FINALS": "QF",
    "SEMI_FINALS": "SF",
    "THIRD_PLACE": "THIRD",
    "FINAL": "FINAL",
}


class Command(BaseCommand):
    help = (
        "Carga resultados terminados desde ESPN (rápido, fase de grupos) y "
        "football-data.org (respaldo + cruces de eliminación). Nunca pisa un "
        "resultado ya cargado (salvo --force)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=3, help="Mirar los últimos N días")
        parser.add_argument("--force", action="store_true", help="Pisar resultados ya cargados")

    # --- infraestructura ---

    def _fetch(self, url, token=None):
        headers = {"X-Auth-Token": token} if token else {}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as res:
            return json.load(res)

    def _find_match(self, home_code, away_code, kickoff, **filters):
        """Busca el partido por equipos y horario (±6 h), tolerando que la
        fuente liste local y visitante invertidos. Devuelve (match, invertido)."""
        window = (kickoff - timedelta(hours=6), kickoff + timedelta(hours=6))
        match = Match.objects.filter(
            home_team__code=home_code, away_team__code=away_code,
            kickoff__range=window, **filters,
        ).first()
        if match:
            return match, False
        match = Match.objects.filter(
            home_team__code=away_code, away_team__code=home_code,
            kickoff__range=window, **filters,
        ).first()
        if match:
            return match, True
        return None, False

    def _apply_result(self, match, home_score, away_score, source):
        match.home_score = home_score
        match.away_score = away_score
        match.save(update_fields=["home_score", "away_score"])
        self.stdout.write(self.style.SUCCESS(
            f"P{match.number} {match.home_label} {home_score}-{away_score} "
            f"{match.away_label} [{source}]"
        ))

    # --- pasada ESPN: resultados rápidos de fase de grupos ---

    def _espn_pass(self, days, force):
        updated = 0
        for offset in range(days + 1):
            date = (timezone.now() - timedelta(days=offset)).strftime("%Y%m%d")
            try:
                data = self._fetch(ESPN_URL.format(date=date))
            except Exception as exc:
                self.stdout.write(self.style.WARNING(f"ESPN no respondió ({date}): {exc}"))
                continue
            for event in data.get("events", []):
                try:
                    self._espn_event(event, force)
                    updated += 1
                except _Skip:
                    pass
                except Exception as exc:
                    self.stdout.write(self.style.WARNING(f"ESPN evento ilegible: {exc}"))
        return updated

    def _espn_event(self, event, force):
        comp = event["competitions"][0]
        status = comp["status"]["type"]["name"]
        # Partido terminado: en los 90' (STATUS_FULL_TIME) o resuelto en alargue/
        # penales (STATUS_FINAL_*). Sirve para grupos y eliminación por igual: el
        # campo `score` de ESPN es el resultado de los 120' SIN la tanda de penales
        # (esta va aparte en `shootoutScore`), que es justo lo que vale en el prode.
        if status != "STATUS_FULL_TIME" and not status.startswith("STATUS_FINAL"):
            raise _Skip()
        sides = {c.get("homeAway"): c for c in comp.get("competitors", [])}
        home, away = sides.get("home"), sides.get("away")
        if not (home and away):
            raise _Skip()
        home_code = _norm((home.get("team") or {}).get("abbreviation"))
        away_code = _norm((away.get("team") or {}).get("abbreviation"))
        kickoff = datetime.fromisoformat(event["date"].replace("Z", "+00:00"))
        match, flipped = self._find_match(home_code, away_code, kickoff)
        if not match:
            raise _Skip()
        if match.has_result and not force:
            raise _Skip()
        home_score, away_score = int(home["score"]), int(away["score"])
        if flipped:
            home_score, away_score = away_score, home_score
        self._apply_result(match, home_score, away_score, "ESPN")

    # --- pasada football-data: respaldo de resultados + cruces ---

    def handle(self, *args, **opts):
        espn = self._espn_pass(opts["days"], opts["force"])

        token = os.environ.get("FOOTBALL_DATA_TOKEN")
        if not token:
            self.stdout.write(f"Listo: {espn} via ESPN. Sin FOOTBALL_DATA_TOKEN, salteo respaldo.")
            return

        date_to = (timezone.now() + timedelta(days=8)).date()
        date_from = (timezone.now() - timedelta(days=opts["days"])).date()
        try:
            data = self._fetch(f"{FD_URL}?dateFrom={date_from}&dateTo={date_to}", token)
        except Exception as exc:
            self.stdout.write(self.style.WARNING(f"football-data no respondió: {exc}"))
            return

        for fd in data.get("matches", []):
            self._sync_knockout_teams(fd)

        updated = skipped = unmatched = manual = 0
        for fd in data.get("matches", []):
            if fd.get("status") != "FINISHED":
                continue
            home_code = _norm((fd.get("homeTeam") or {}).get("tla"))
            away_code = _norm((fd.get("awayTeam") or {}).get("tla"))
            utc_date = fd.get("utcDate")
            if not (home_code and away_code and utc_date):
                unmatched += 1
                continue

            kickoff = datetime.fromisoformat(utc_date.replace("Z", "+00:00"))
            match, flipped = self._find_match(home_code, away_code, kickoff)
            if not match:
                unmatched += 1
                self.stdout.write(self.style.WARNING(
                    f"Sin match local para {home_code} vs {away_code} ({utc_date})."
                ))
                continue

            if match.has_result and not opts["force"]:
                skipped += 1
                continue

            score = fd.get("score") or {}
            duration = score.get("duration")
            full_time = score.get("fullTime") or {}
            home_score, away_score = full_time.get("home"), full_time.get("away")
            source = "football-data"

            if duration == "PENALTY_SHOOTOUT":
                # Vale el resultado hasta los 120' (con alargue, sin penales).
                # fullTime incluye la tanda de penales: se la restamos.
                pens = score.get("penalties") or {}
                if None in (home_score, away_score, pens.get("home"), pens.get("away")):
                    # Sin desglose de la tanda no cargamos nada: nunca el score con penales.
                    manual += 1
                    self.stdout.write(self.style.WARNING(
                        f"P{match.number} terminó en penales y la API no trae la "
                        "tanda desglosada: cargá a mano el resultado de los 120'."
                    ))
                    continue
                home_score -= pens["home"]
                away_score -= pens["away"]
                source = "football-data 120'"

            if home_score is None or away_score is None:
                unmatched += 1
                continue

            if flipped:
                home_score, away_score = away_score, home_score
            self._apply_result(match, home_score, away_score, source)
            updated += 1

        self.stdout.write(self.style.SUCCESS(
            f"Listo: {espn} via ESPN, {updated} via football-data, {skipped} ya "
            f"cargados, {manual} para carga manual, {unmatched} sin matchear."
        ))

    def _sync_knockout_teams(self, fd):
        """Asigna los equipos de una llave cuando la API ya los publica."""
        stage = STAGE_MAP.get(fd.get("stage"))
        home_code = _norm((fd.get("homeTeam") or {}).get("tla"))
        away_code = _norm((fd.get("awayTeam") or {}).get("tla"))
        utc_date = fd.get("utcDate")
        if not (stage and home_code and away_code and utc_date):
            return
        kickoff = datetime.fromisoformat(utc_date.replace("Z", "+00:00"))
        # Ventana corta: dos llaves de la misma etapa nunca arrancan con menos
        # de una hora de diferencia, así el match es inequívoco.
        candidates = Match.objects.filter(
            stage=stage,
            kickoff__range=(kickoff - timedelta(hours=1), kickoff + timedelta(hours=1)),
        ).filter(Q(home_team__isnull=True) | Q(away_team__isnull=True))
        if candidates.count() != 1:
            if candidates.count() > 1:
                self.stdout.write(self.style.WARNING(
                    f"Llave ambigua para {home_code} vs {away_code} ({utc_date}): "
                    "asignar a mano en el admin."
                ))
            return
        match = candidates.first()
        home = Team.objects.filter(code=home_code).first()
        away = Team.objects.filter(code=away_code).first()
        if not (home and away):
            self.stdout.write(self.style.WARNING(
                f"P{match.number}: no encuentro equipos {home_code}/{away_code} en la base."
            ))
            return
        match.home_team, match.away_team = home, away
        match.save(update_fields=["home_team", "away_team"])
        self.stdout.write(self.style.SUCCESS(
            f"P{match.number} definido: {home.name} vs {away.name}"
        ))


class _Skip(Exception):
    pass
