from django.contrib import admin
from django.contrib.auth.models import Group
from django.utils import timezone

from .models import Match, Prediction, Team, Tournament

admin.site.site_header = "Prode Mundial 2026"
admin.site.site_title = "Prode Mundial 2026"
admin.site.index_title = "Administración"

# Los Grupos de permisos de Django no se usan en este proyecto y confunden
# con los torneos; los sacamos del admin.
admin.site.unregister(Group)


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("code", "flag", "name", "group")
    list_filter = ("group",)
    search_fields = ("code", "name")
    ordering = ("group", "name")


@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    list_display = (
        "number", "stage", "group", "matchup", "kickoff_local",
        "home_score", "away_score",
    )
    list_display_links = ("number", "matchup")
    list_editable = ("home_score", "away_score")
    list_filter = ("stage", "group")
    search_fields = ("home_team__name", "away_team__name", "home_placeholder", "away_placeholder")
    autocomplete_fields = ("home_team", "away_team")
    ordering = ("number",)
    list_per_page = 110

    @admin.display(description="Partido")
    def matchup(self, obj):
        return f"{obj.home_label} vs {obj.away_label}"

    @admin.display(description="Kickoff (UTC)", ordering="kickoff")
    def kickoff_local(self, obj):
        return timezone.localtime(obj.kickoff).strftime("%d/%m %H:%M")


@admin.register(Tournament)
class TournamentAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "owner", "member_count", "created_at")
    search_fields = ("name", "code")
    filter_horizontal = ("members",)

    @admin.display(description="Participantes")
    def member_count(self, obj):
        return obj.members.count()


@admin.register(Prediction)
class PredictionAdmin(admin.ModelAdmin):
    list_display = ("user", "match", "home_score", "away_score", "points", "updated_at")
    list_filter = ("match__stage",)
    search_fields = ("user__username", "user__first_name")
    readonly_fields = ("updated_at",)
