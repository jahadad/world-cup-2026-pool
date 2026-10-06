import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


def _tournament_code():
    # Sin 0/O/1/I para que se pueda dictar por teléfono sin confusiones.
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(6))


class Team(models.Model):
    code = models.CharField("código FIFA", max_length=3, unique=True)
    name = models.CharField("nombre", max_length=50)
    flag = models.CharField("bandera", max_length=8, blank=True)
    group = models.CharField("grupo", max_length=1, blank=True)

    class Meta:
        ordering = ["group", "name"]
        verbose_name = "equipo"

    def __str__(self):
        return self.name


class Match(models.Model):
    class Stage(models.TextChoices):
        GROUP = "GROUP", "Group stage"
        R32 = "R32", "Round of 32"
        R16 = "R16", "Round of 16"
        QF = "QF", "Quarter-finals"
        SF = "SF", "Semi-finals"
        THIRD = "THIRD", "Third place"
        FINAL = "FINAL", "Final"

    number = models.PositiveIntegerField("partido N°", unique=True)
    stage = models.CharField("fase", max_length=8, choices=Stage.choices)
    group = models.CharField("grupo", max_length=1, blank=True)
    kickoff = models.DateTimeField("inicio")
    venue = models.CharField("estadio", max_length=80, blank=True)
    city = models.CharField("ciudad", max_length=80, blank=True)
    home_team = models.ForeignKey(
        Team, null=True, blank=True, on_delete=models.PROTECT, related_name="+",
        verbose_name="local",
    )
    away_team = models.ForeignKey(
        Team, null=True, blank=True, on_delete=models.PROTECT, related_name="+",
        verbose_name="visitante",
    )
    # Para llaves de eliminación con equipos aún no definidos ("1° Grupo A", "Ganador P74")
    home_placeholder = models.CharField(max_length=40, blank=True)
    away_placeholder = models.CharField(max_length=40, blank=True)
    home_score = models.PositiveSmallIntegerField("goles local", null=True, blank=True)
    away_score = models.PositiveSmallIntegerField("goles visitante", null=True, blank=True)

    class Meta:
        ordering = ["kickoff", "number"]
        verbose_name = "partido"

    def __str__(self):
        return f"P{self.number}: {self.home_label} vs {self.away_label}"

    @property
    def teams_defined(self):
        return self.home_team_id is not None and self.away_team_id is not None

    @property
    def lock_time(self):
        return self.kickoff - timedelta(minutes=settings.PRODE_LOCK_MINUTES)

    @property
    def is_open(self):
        return self.teams_defined and timezone.now() < self.lock_time

    @property
    def has_result(self):
        return self.home_score is not None and self.away_score is not None

    @property
    def home_label(self):
        return self.home_team.name if self.home_team else (self.home_placeholder or "TBD")

    @property
    def away_label(self):
        return self.away_team.name if self.away_team else (self.away_placeholder or "TBD")

    @property
    def home_flag(self):
        return self.home_team.flag if self.home_team else "❔"

    @property
    def away_flag(self):
        return self.away_team.flag if self.away_team else "❔"

    @property
    def stage_label(self):
        if self.stage == self.Stage.GROUP:
            return f"Group {self.group}"
        return self.get_stage_display()


class Tournament(models.Model):
    name = models.CharField("nombre", max_length=40)
    code = models.CharField("código", max_length=8, unique=True, default=_tournament_code)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="owned_tournaments", verbose_name="creador",
    )
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL, related_name="tournaments", blank=True,
        verbose_name="participantes",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "torneo"

    def __str__(self):
        return f"{self.name} ({self.code})"


class Prediction(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="predictions",
        verbose_name="participante",
    )
    match = models.ForeignKey(
        Match, on_delete=models.CASCADE, related_name="predictions", verbose_name="partido"
    )
    home_score = models.PositiveSmallIntegerField("goles local")
    away_score = models.PositiveSmallIntegerField("goles visitante")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "match"], name="unique_user_match"),
        ]
        verbose_name = "pronóstico"

    def __str__(self):
        return f"{self.user.username} P{self.match.number}: {self.home_score}-{self.away_score}"

    @property
    def points(self):
        m = self.match
        if not m.has_result:
            return None
        if self.home_score == m.home_score and self.away_score == m.away_score:
            return settings.PRODE_POINTS_EXACT
        pred_sign = (self.home_score > self.away_score) - (self.home_score < self.away_score)
        real_sign = (m.home_score > m.away_score) - (m.home_score < m.away_score)
        if pred_sign == real_sign:
            return settings.PRODE_POINTS_OUTCOME
        return 0
