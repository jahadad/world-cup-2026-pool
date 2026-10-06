import json
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from prode.models import Match, Team


class Command(BaseCommand):
    help = (
        "Carga/actualiza equipos y partidos desde data/fixtures.json. "
        "Idempotente: nunca pisa resultados ya cargados, y no borra equipos "
        "asignados a mano en partidos de eliminación."
    )

    def add_arguments(self, parser):
        parser.add_argument("--path", default=None, help="Ruta alternativa al JSON")

    def handle(self, *args, **opts):
        path = Path(opts["path"] or settings.BASE_DIR / "data" / "fixtures.json")
        if not path.exists():
            self.stdout.write(self.style.WARNING(f"No existe {path}, no cargo nada."))
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as exc:
            raise CommandError(f"JSON inválido en {path}: {exc}")

        teams = {}
        for t in data.get("teams", []):
            team, _ = Team.objects.update_or_create(
                code=t["code"],
                defaults={
                    "name": t["name"],
                    "flag": t.get("flag") or "",
                    "group": t.get("group") or "",
                },
            )
            teams[t["code"]] = team

        created = updated = 0
        for m in data.get("matches", []):
            kickoff = datetime.fromisoformat(m["kickoff_utc"].replace("Z", "+00:00"))
            fields = {
                "stage": m["stage"],
                "group": m.get("group") or "",
                "kickoff": kickoff,
                "venue": m.get("venue") or "",
                "city": m.get("city") or "",
                "home_placeholder": m.get("home_placeholder") or "",
                "away_placeholder": m.get("away_placeholder") or "",
            }
            # Solo asigno equipos si el JSON los trae: un null no debe pisar
            # un equipo que el admin ya definió en una llave.
            if m.get("home"):
                fields["home_team"] = teams[m["home"]]
            if m.get("away"):
                fields["away_team"] = teams[m["away"]]

            match = Match.objects.filter(number=m["number"]).first()
            if match:
                for k, v in fields.items():
                    setattr(match, k, v)
                match.save()
                updated += 1
            else:
                Match.objects.create(number=m["number"], **fields)
                created += 1

        self.stdout.write(self.style.SUCCESS(
            f"Equipos: {len(teams)}. Partidos: {created} creados, {updated} actualizados."
        ))
