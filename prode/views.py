import re

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.cache import cache
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .forms import RegisterForm, TournamentForm
from .models import Match, Prediction, Team, Tournament


class ThrottledLoginView(auth_views.LoginView):
    """Tras 3 intentos fallidos (por usuario+IP) bloquea el login 5 minutos."""

    template_name = "prode/login.html"
    max_attempts = 3
    lockout_seconds = 300

    def _key(self):
        username = (self.request.POST.get("username") or "").strip().lower()
        ip = (
            self.request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
            or self.request.META.get("REMOTE_ADDR", "")
        )
        return f"login-fails:{username}:{ip}"

    def post(self, request, *args, **kwargs):
        if cache.get(self._key(), 0) >= self.max_attempts:
            return self.render_to_response(
                self.get_context_data(form=self.get_form(), locked=True)
            )
        return super().post(request, *args, **kwargs)

    def form_invalid(self, form):
        key = self._key()
        try:
            cache.incr(key)
        except ValueError:
            cache.set(key, 1, self.lockout_seconds)
        return super().form_invalid(form)

    def form_valid(self, form):
        cache.delete(self._key())
        return super().form_valid(form)


@login_required
def fixture(request):
    # El agrupado por día se hace en el navegador con la zona horaria del
    # visitante; acá solo va la lista ordenada por kickoff.
    matches = list(Match.objects.select_related("home_team", "away_team"))
    preds = {p.match_id: p for p in Prediction.objects.filter(user=request.user)}
    for m in matches:
        pred = preds.get(m.id)
        if pred:
            pred.match = m
        m.user_prediction = pred
    return render(request, "prode/fixture.html", {
        "matches": matches,
        "lock_minutes": settings.PRODE_LOCK_MINUTES,
        "points_exact": settings.PRODE_POINTS_EXACT,
    })


@login_required
@require_POST
def save_prediction(request, number):
    match = get_object_or_404(Match, number=number)
    if not match.is_open:
        return _save_response(request, match, ok=False, msg="This match is locked.")
    try:
        home = int(request.POST["home_score"])
        away = int(request.POST["away_score"])
        if not (0 <= home <= 99 and 0 <= away <= 99):
            raise ValueError
    except (KeyError, ValueError):
        return _save_response(request, match, ok=False, msg="Enter a valid score.")
    Prediction.objects.update_or_create(
        user=request.user, match=match,
        defaults={"home_score": home, "away_score": away},
    )
    return _save_response(request, match, ok=True, msg="Saved ✓")


def _save_response(request, match, ok, msg):
    if request.headers.get("x-requested-with") == "fetch":
        return JsonResponse({"ok": ok, "msg": msg})
    (messages.success if ok else messages.error)(request, f"Match {match.number}: {msg}")
    return redirect(f"/#m{match.number}")


@login_required
def match_detail(request, number):
    match = get_object_or_404(
        Match.objects.select_related("home_team", "away_team"), number=number
    )
    # Solo se ven los pronósticos de gente con la que compartís algún torneo
    # (más el propio): los grupos no se enteran unos de otros.
    mates = User.objects.filter(tournaments__in=request.user.tournaments.all())
    predictions = list(
        match.predictions.filter(Q(user__in=mates) | Q(user=request.user))
        .select_related("user").order_by("user__first_name", "user__username")
    )
    for p in predictions:
        p.match = match
    # Anti-copia: los pronósticos ajenos recién se revelan cuando el partido
    # cierra. Antes solo se ve quién ya pronosticó.
    return render(request, "prode/match_detail.html", {
        "match": match,
        "predictions": predictions,
        "show_picks": not match.is_open,
    })


@login_required
def groups(request):
    teams = Team.objects.exclude(group="")
    rows = {
        t.id: {"team": t, "pj": 0, "g": 0, "e": 0, "p": 0, "gf": 0, "gc": 0, "dif": 0, "pts": 0}
        for t in teams
    }
    played = Match.objects.filter(
        stage=Match.Stage.GROUP,
        home_score__isnull=False, away_score__isnull=False,
    ).select_related("home_team", "away_team")
    for m in played:
        home, away = rows.get(m.home_team_id), rows.get(m.away_team_id)
        if not (home and away):
            continue
        for side, mine, theirs in ((home, m.home_score, m.away_score),
                                   (away, m.away_score, m.home_score)):
            side["pj"] += 1
            side["gf"] += mine
            side["gc"] += theirs
            side["dif"] = side["gf"] - side["gc"]
            if mine > theirs:
                side["g"] += 1
                side["pts"] += 3
            elif mine == theirs:
                side["e"] += 1
                side["pts"] += 1
            else:
                side["p"] += 1
    group_tables = []
    for letter in "ABCDEFGHIJKL":
        items = [r for r in rows.values() if r["team"].group == letter]
        if not items:
            continue
        # Criterio FIFA: puntos, diferencia de gol, goles a favor
        items.sort(key=lambda r: (-r["pts"], -r["dif"], -r["gf"], r["team"].name))
        group_tables.append({"letter": letter, "rows": items})
    return render(request, "prode/groups.html", {"group_tables": group_tables})


def _build_table(users):
    scored = Prediction.objects.select_related("user", "match").filter(
        user__in=users,
        match__home_score__isnull=False, match__away_score__isnull=False,
    )
    rows = {}
    for p in scored:
        r = rows.setdefault(
            p.user_id, {"user": p.user, "points": 0, "exact": 0, "outcome": 0, "played": 0}
        )
        pts = p.points
        r["points"] += pts
        r["played"] += 1
        if pts == settings.PRODE_POINTS_EXACT:
            r["exact"] += 1
        elif pts == settings.PRODE_POINTS_OUTCOME:
            r["outcome"] += 1
    for u in users:
        rows.setdefault(u.id, {"user": u, "points": 0, "exact": 0, "outcome": 0, "played": 0})
    return sorted(
        rows.values(),
        key=lambda r: (-r["points"], -r["exact"], (r["user"].first_name or r["user"].username).lower()),
    )


@login_required
def leaderboard(request):
    tournament_tables = [
        {"tournament": t, "table": _build_table(t.members.all())}
        for t in request.user.tournaments.all()
    ]
    return render(request, "prode/leaderboard.html", {
        "tournament_tables": tournament_tables,
        "points_exact": settings.PRODE_POINTS_EXACT,
        "points_outcome": settings.PRODE_POINTS_OUTCOME,
    })


@login_required
def tournaments(request):
    mine = request.user.tournaments.all().prefetch_related("members")
    return render(request, "prode/tournaments.html", {
        "mine": mine,
        "create_form": TournamentForm(),
    })


@login_required
@require_POST
def create_tournament(request):
    form = TournamentForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Give your league a name.")
        return redirect("tournaments")
    tournament = form.save(commit=False)
    tournament.owner = request.user
    tournament.save()
    tournament.members.add(request.user)
    messages.success(request, "League created. Share the invite to get people in.")
    return redirect("tournament_detail", code=tournament.code)


@login_required
@require_POST
def join_tournament_form(request):
    return _join(request, (request.POST.get("code") or "").strip())


def join_tournament(request, code):
    # Un link de invitación lo abre gente sin cuenta: directo al signup con
    # el código pre-llenado. Los que ya tienen cuenta se loguean desde ahí.
    if not request.user.is_authenticated:
        return redirect(f"{reverse('register')}?next={request.path}")
    return _join(request, code)


def _join(request, code):
    tournament = Tournament.objects.filter(code__iexact=code).first()
    if not tournament:
        messages.error(request, "No league with that code.")
        return redirect("tournaments")
    if not tournament.members.filter(id=request.user.id).exists():
        tournament.members.add(request.user)
        messages.success(request, f"You joined “{tournament.name}”.")
    return redirect("tournament_detail", code=tournament.code)


@login_required
def tournament_detail(request, code):
    tournament = get_object_or_404(Tournament, code__iexact=code)
    is_member = tournament.members.filter(id=request.user.id).exists()
    table = _build_table(tournament.members.all()) if is_member else None
    join_url = request.build_absolute_uri(reverse("join_tournament", args=[tournament.code]))
    share_text = (
        f"Join my World Cup 2026 prediction league “{tournament.name}”: {join_url} "
        f"— sign up with invite code {tournament.code}. Pick scores, beat everyone."
    )
    return render(request, "prode/tournament_detail.html", {
        "tournament": tournament,
        "is_member": is_member,
        "table": table,
        "share_text": share_text,
    })


def register(request):
    if request.user.is_authenticated:
        return redirect("fixture")
    next_url = request.POST.get("next") or request.GET.get("next") or ""
    initial = {}
    code_match = re.match(r"^/t/(?P<code>[A-Za-z0-9]+)/?$", next_url)
    if code_match:
        initial["invite_code"] = code_match.group("code").upper()
    form = RegisterForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, "You're in! Start picking your scores.")
        if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
            return redirect(next_url)
        return redirect("fixture")
    return render(request, "prode/register.html", {"form": form, "next": next_url})
