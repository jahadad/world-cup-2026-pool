import os
import random
from datetime import timedelta
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .management.commands import fetchresults
from .models import Match, Prediction, Team, Tournament


def make_match(minutes_from_now=60, with_teams=True, number=1):
    home = away = None
    if with_teams:
        home, _ = Team.objects.get_or_create(code="ARG", defaults={"name": "Argentina", "flag": "🇦🇷", "group": "A"})
        away, _ = Team.objects.get_or_create(code="BRA", defaults={"name": "Brasil", "flag": "🇧🇷", "group": "B"})
    return Match.objects.create(
        number=number, stage=Match.Stage.GROUP, group="A",
        kickoff=timezone.now() + timedelta(minutes=minutes_from_now),
        home_team=home, away_team=away,
    )


class ScoringTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("pepe", password="x")
        self.match = make_match()

    def predict_and_score(self, ph, pa, rh, ra):
        Prediction.objects.filter(user=self.user).delete()
        pred = Prediction.objects.create(user=self.user, match=self.match, home_score=ph, away_score=pa)
        self.match.home_score, self.match.away_score = rh, ra
        self.match.save()
        pred.refresh_from_db()
        return pred.points

    def test_exact_score(self):
        self.assertEqual(self.predict_and_score(2, 1, 2, 1), settings.PRODE_POINTS_EXACT)

    def test_correct_outcome(self):
        self.assertEqual(self.predict_and_score(1, 0, 3, 1), settings.PRODE_POINTS_OUTCOME)

    def test_correct_draw_outcome(self):
        self.assertEqual(self.predict_and_score(0, 0, 2, 2), settings.PRODE_POINTS_OUTCOME)

    def test_miss(self):
        self.assertEqual(self.predict_and_score(2, 0, 0, 1), 0)

    def test_no_result_yet(self):
        pred = Prediction.objects.create(user=self.user, match=self.match, home_score=1, away_score=0)
        self.assertIsNone(pred.points)


class LockTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("pepe", password="x")
        self.client.force_login(self.user)

    def save(self, match, h=2, a=0):
        return self.client.post(
            reverse("save_prediction", args=[match.number]),
            {"home_score": h, "away_score": a},
            headers={"x-requested-with": "fetch"},
        )

    def test_open_match_saves(self):
        match = make_match(minutes_from_now=60)
        res = self.save(match)
        self.assertTrue(res.json()["ok"])
        self.assertEqual(Prediction.objects.count(), 1)

    def test_update_overwrites(self):
        match = make_match(minutes_from_now=60)
        self.save(match, 1, 1)
        self.save(match, 3, 0)
        pred = Prediction.objects.get()
        self.assertEqual((pred.home_score, pred.away_score), (3, 0))

    def test_locked_match_rejects(self):
        match = make_match(minutes_from_now=3)  # lock = 5 min antes
        res = self.save(match)
        self.assertFalse(res.json()["ok"])
        self.assertEqual(Prediction.objects.count(), 0)

    def test_lock_boundary_exact(self):
        # 5 min + 10 seg antes: todavía abierto
        match = make_match(number=50)
        match.kickoff = timezone.now() + timedelta(minutes=5, seconds=10)
        match.save()
        self.assertTrue(self.save(match).json()["ok"])
        # 5 min - 10 seg antes: ya cerrado, y el pronóstico previo no cambia
        match.kickoff = timezone.now() + timedelta(minutes=4, seconds=50)
        match.save()
        res = self.save(match, 7, 7)
        self.assertFalse(res.json()["ok"])
        pred = Prediction.objects.get(user=self.user, match=match)
        self.assertEqual((pred.home_score, pred.away_score), (2, 0))

    def test_tbd_match_rejects(self):
        match = make_match(minutes_from_now=600, with_teams=False)
        res = self.save(match)
        self.assertFalse(res.json()["ok"])

    def test_invalid_score_rejects(self):
        match = make_match(minutes_from_now=60)
        res = self.client.post(
            reverse("save_prediction", args=[match.number]),
            {"home_score": "-1", "away_score": "x"},
            headers={"x-requested-with": "fetch"},
        )
        self.assertFalse(res.json()["ok"])
        self.assertEqual(Prediction.objects.count(), 0)


class LoginThrottleTests(TestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        User.objects.create_user("pepe", password="correcta123")

    def try_login(self, password):
        return self.client.post(reverse("login"), {"username": "pepe", "password": password})

    def test_locks_after_three_failures_even_with_right_password(self):
        for _ in range(3):
            self.try_login("mala")
        res = self.try_login("correcta123")
        self.assertContains(res, "Too many attempts")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_success_before_limit_resets_counter(self):
        self.try_login("mala")
        self.try_login("mala")
        res = self.try_login("correcta123")
        self.assertEqual(res.status_code, 302)
        self.assertIn("_auth_user_id", self.client.session)


class RegisterTests(TestCase):
    def post_register(self, code):
        return self.client.post(reverse("register"), {
            "username": "amigo",
            "first_name": "Amigo",
            "password1": "prode123",
            "password2": "prode123",
            "invite_code": code,
        })

    def test_wrong_invite_code(self):
        self.post_register("NOPE")
        self.assertFalse(User.objects.filter(username="amigo").exists())

    def test_right_invite_code_registers_and_logs_in(self):
        res = self.post_register("PRODE2026")
        self.assertRedirects(res, reverse("fixture"))
        self.assertTrue(User.objects.filter(username="amigo").exists())

    def test_invite_code_case_insensitive(self):
        self.post_register("prode2026")
        self.assertTrue(User.objects.filter(username="amigo").exists())


class FetchResultsTests(TestCase):
    def api_payload(self, match, home=2, away=1, duration="REGULAR", penalties=None):
        # fullTime en v4 incluye alargue y, si hubo, la tanda de penales.
        score = {"duration": duration, "fullTime": {"home": home, "away": away}}
        if penalties is not None:
            score["penalties"] = {"home": penalties[0], "away": penalties[1]}
        return {"matches": [{
            "status": "FINISHED",
            "homeTeam": {"tla": match.home_team.code},
            "awayTeam": {"tla": match.away_team.code},
            "utcDate": match.kickoff.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "score": score,
        }]}

    def espn_payload(self, match, home=2, away=1, status="STATUS_FULL_TIME", flip=False, shootout=None):
        home_team, away_team = match.home_team, match.away_team
        if flip:
            home_team, away_team = away_team, home_team
        hp = {"homeAway": "home", "score": str(home), "team": {"abbreviation": home_team.code}}
        ap = {"homeAway": "away", "score": str(away), "team": {"abbreviation": away_team.code}}
        if shootout is not None:
            hp["shootoutScore"], ap["shootoutScore"] = shootout[0], shootout[1]
        return {"events": [{
            "date": match.kickoff.strftime("%Y-%m-%dT%H:%MZ"),
            "competitions": [{
                "status": {"type": {"name": status}},
                "competitors": [hp, ap],
            }],
        }]}

    def run_command(self, payload):
        # El mismo mock sirve para las dos pasadas: la de ESPN ignora payloads
        # sin "events" y la de football-data ignora payloads sin "matches".
        with mock.patch.dict(os.environ, {"FOOTBALL_DATA_TOKEN": "test-token"}):
            with mock.patch.object(fetchresults.Command, "_fetch", return_value=payload):
                call_command("fetchresults")

    def test_fills_missing_result(self):
        match = make_match(minutes_from_now=-120)
        self.run_command(self.api_payload(match, 2, 1))
        match.refresh_from_db()
        self.assertEqual((match.home_score, match.away_score), (2, 1))

    def test_does_not_overwrite_manual_result(self):
        match = make_match(minutes_from_now=-120)
        match.home_score, match.away_score = 0, 0
        match.save()
        self.run_command(self.api_payload(match, 2, 1))
        match.refresh_from_db()
        self.assertEqual((match.home_score, match.away_score), (0, 0))

    def test_penalty_shootout_strips_penalties(self):
        # GER-PAR: 1-1 en los 120', definido por penales. fullTime viene con la
        # tanda sumada (4-5); vale el resultado hasta los 120' sin penales (1-1).
        match = make_match(minutes_from_now=-120)
        self.run_command(self.api_payload(
            match, home=4, away=5, duration="PENALTY_SHOOTOUT", penalties=(3, 4)))
        match.refresh_from_db()
        self.assertEqual((match.home_score, match.away_score), (1, 1))

    def test_extra_time_counts_including_extra_time(self):
        # Se define en el alargue sin penales: fullTime ya es el resultado de los
        # 120' y es lo que vale (2-1).
        match = make_match(minutes_from_now=-120)
        self.run_command(self.api_payload(match, 2, 1, duration="EXTRA_TIME"))
        match.refresh_from_db()
        self.assertEqual((match.home_score, match.away_score), (2, 1))

    def test_penalty_without_breakdown_left_for_manual_entry(self):
        # Penales sin la tanda desglosada: no cargamos nada (nunca el score con
        # penales), queda para carga manual.
        match = make_match(minutes_from_now=-120)
        self.run_command(self.api_payload(match, 4, 5, duration="PENALTY_SHOOTOUT"))
        match.refresh_from_db()
        self.assertFalse(match.has_result)

    def test_assigns_knockout_teams_when_published(self):
        arg = Team.objects.create(code="ARG", name="Argentina", flag="🇦🇷", group="A")
        bra = Team.objects.create(code="BRA", name="Brasil", flag="🇧🇷", group="B")
        kickoff = timezone.now() + timedelta(days=2)
        match = Match.objects.create(
            number=80, stage=Match.Stage.R16, kickoff=kickoff,
            home_placeholder="1° Grupo A", away_placeholder="1° Grupo B",
        )
        payload = {"matches": [{
            "status": "TIMED",
            "stage": "LAST_16",
            "homeTeam": {"tla": "ARG"},
            "awayTeam": {"tla": "BRA"},
            "utcDate": kickoff.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "score": {},
        }]}
        self.run_command(payload)
        match.refresh_from_db()
        self.assertEqual(match.home_team, arg)
        self.assertEqual(match.away_team, bra)
        self.assertTrue(match.is_open)

    def test_no_token_still_runs_espn_pass(self):
        match = make_match(minutes_from_now=-120)
        env = {k: v for k, v in os.environ.items() if k != "FOOTBALL_DATA_TOKEN"}
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch.object(
                fetchresults.Command, "_fetch", return_value=self.espn_payload(match, 3, 1)
            ):
                call_command("fetchresults")
        match.refresh_from_db()
        self.assertEqual((match.home_score, match.away_score), (3, 1))

    def test_espn_fills_group_result(self):
        match = make_match(minutes_from_now=-120)
        self.run_command(self.espn_payload(match, 2, 0))
        match.refresh_from_db()
        self.assertEqual((match.home_score, match.away_score), (2, 0))

    def test_espn_reversed_orientation_swaps_scores(self):
        match = make_match(minutes_from_now=-120)
        self.run_command(self.espn_payload(match, 2, 0, flip=True))
        match.refresh_from_db()
        self.assertEqual((match.home_score, match.away_score), (0, 2))

    def test_espn_ignores_in_progress(self):
        match = make_match(minutes_from_now=-120)
        self.run_command(self.espn_payload(match, 2, 0, status="STATUS_IN_PROGRESS"))
        match.refresh_from_db()
        self.assertFalse(match.has_result)

    def test_espn_fills_knockout_result(self):
        ko = make_match(minutes_from_now=-120, number=90)
        ko.stage = Match.Stage.R16
        ko.save()
        self.run_command(self.espn_payload(ko, 2, 0))
        ko.refresh_from_db()
        self.assertEqual((ko.home_score, ko.away_score), (2, 0))

    def test_espn_penalty_uses_120_score_not_shootout(self):
        # GER-PAR: 1-1 en los 120', 3-4 en penales. ESPN trae score=1-1 y la
        # tanda aparte; se carga 1-1 (los penales no cuentan).
        ko = make_match(minutes_from_now=-120, number=91)
        ko.stage = Match.Stage.R16
        ko.save()
        self.run_command(self.espn_payload(
            ko, 1, 1, status="STATUS_FINAL_PEN", shootout=(3, 4)))
        ko.refresh_from_db()
        self.assertEqual((ko.home_score, ko.away_score), (1, 1))

    def test_fd_reversed_orientation_swaps_scores(self):
        match = make_match(minutes_from_now=-120)
        payload = self.api_payload(match, 1, 3)
        fd = payload["matches"][0]
        fd["homeTeam"], fd["awayTeam"] = fd["awayTeam"], fd["homeTeam"]
        self.run_command(payload)
        match.refresh_from_db()
        self.assertEqual((match.home_score, match.away_score), (3, 1))


class KnockoutEndToEndTests(TestCase):
    """Cruce de eliminación: se carga el resultado hasta los 120' (sin penales),
    se muestra bien y los puntos de cada jugador salen correctos."""

    def _fd_payload(self, match, home, away, duration, penalties=None):
        score = {"duration": duration, "fullTime": {"home": home, "away": away}}
        if penalties is not None:
            score["penalties"] = {"home": penalties[0], "away": penalties[1]}
        return {"matches": [{
            "status": "FINISHED",
            "homeTeam": {"tla": match.home_team.code},
            "awayTeam": {"tla": match.away_team.code},
            "utcDate": match.kickoff.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "score": score,
        }]}

    def _load(self, match, home, away, duration, penalties=None):
        payload = self._fd_payload(match, home, away, duration, penalties)
        with mock.patch.dict(os.environ, {"FOOTBALL_DATA_TOKEN": "test-token"}):
            with mock.patch.object(fetchresults.Command, "_fetch", return_value=payload):
                call_command("fetchresults")
        match.refresh_from_db()

    def _points_for(self, match, ph, pa):
        user = User.objects.create_user(f"u{ph}{pa}{match.number}", password="x")
        pred = Prediction.objects.create(user=user, match=match, home_score=ph, away_score=pa)
        pred.refresh_from_db()
        return pred.points

    def test_1_0_decided_in_extra_time(self):
        # 1-0 en los 120' (se define en el alargue, sin penales).
        match = make_match(minutes_from_now=-180, number=90)
        match.stage = Match.Stage.R16
        match.save()
        self._load(match, 1, 0, "EXTRA_TIME")

        # El resultado se guarda y se muestra como 1-0.
        self.assertEqual((match.home_score, match.away_score), (1, 0))
        self.assertTrue(match.has_result)

        # Puntos: 1-0 exacto, 2-0 acierta ganador (local), 0-0 y 0-1 fallan.
        EXACT, OUT = settings.PRODE_POINTS_EXACT, settings.PRODE_POINTS_OUTCOME
        self.assertEqual(self._points_for(match, 1, 0), EXACT)
        self.assertEqual(self._points_for(match, 2, 0), OUT)
        self.assertEqual(self._points_for(match, 0, 0), 0)
        self.assertEqual(self._points_for(match, 0, 1), 0)

    def test_0_0_won_on_penalties_5_4(self):
        # 0-0 en los 120', gana uno 5-4 en la tanda. Vale el 0-0.
        # fullTime en v4 = 0+5 y 0+4 (incluye la tanda); penalties = 5-4.
        match = make_match(minutes_from_now=-180, number=91)
        match.stage = Match.Stage.R16
        match.save()
        self._load(match, 5, 4, "PENALTY_SHOOTOUT", penalties=(5, 4))

        # Se guarda y se muestra como 0-0 (los penales no cuentan).
        self.assertEqual((match.home_score, match.away_score), (0, 0))
        self.assertTrue(match.has_result)

        # Puntos: 0-0 exacto; cualquier empate (1-1) acierta el signo; una
        # victoria (1-0) falla porque el resultado válido es empate.
        EXACT, OUT = settings.PRODE_POINTS_EXACT, settings.PRODE_POINTS_OUTCOME
        self.assertEqual(self._points_for(match, 0, 0), EXACT)
        self.assertEqual(self._points_for(match, 1, 1), OUT)
        self.assertEqual(self._points_for(match, 1, 0), 0)
        self.assertEqual(self._points_for(match, 0, 1), 0)


class GroupStandingsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("pepe", password="x")
        self.client.force_login(self.user)
        self.t = {}
        for i, code in enumerate(["AA1", "AA2", "AA3", "AA4"]):
            self.t[code] = Team.objects.create(code=code, name=f"Equipo {code}", group="A")

    def play(self, number, home, away, hs, as_):
        Match.objects.create(
            number=number, stage=Match.Stage.GROUP, group="A",
            kickoff=timezone.now() - timedelta(hours=3),
            home_team=self.t[home], away_team=self.t[away],
            home_score=hs, away_score=as_,
        )

    def test_standings_computation_and_order(self):
        self.play(1, "AA1", "AA2", 3, 0)
        self.play(2, "AA3", "AA4", 1, 1)
        self.play(3, "AA1", "AA3", 0, 0)
        # Partido sin resultado: no debe contar
        Match.objects.create(
            number=4, stage=Match.Stage.GROUP, group="A",
            kickoff=timezone.now() + timedelta(days=1),
            home_team=self.t["AA2"], away_team=self.t["AA4"],
        )
        res = self.client.get(reverse("groups"))
        g = res.context["group_tables"][0]
        order = [r["team"].code for r in g["rows"]]
        self.assertEqual(order, ["AA1", "AA3", "AA4", "AA2"])
        top = g["rows"][0]
        self.assertEqual((top["pj"], top["g"], top["e"], top["p"]), (2, 1, 1, 0))
        self.assertEqual((top["gf"], top["gc"], top["dif"], top["pts"]), (3, 0, 3, 4))

    def test_goal_difference_tiebreak(self):
        self.play(1, "AA1", "AA2", 4, 0)
        self.play(2, "AA3", "AA4", 1, 0)
        # AA1 y AA3 con 3 pts: gana AA1 por diferencia de gol
        res = self.client.get(reverse("groups"))
        order = [r["team"].code for r in res.context["group_tables"][0]["rows"]]
        self.assertEqual(order[:2], ["AA1", "AA3"])


class PredictionVisibilityTests(TestCase):
    def setUp(self):
        self.u1 = User.objects.create_user("uno", password="x", first_name="Uno")
        self.u2 = User.objects.create_user("dos", password="x", first_name="Dos")
        t = Tournament.objects.create(name="Los Pibes", owner=self.u1)
        t.members.add(self.u1, self.u2)
        self.match = make_match(minutes_from_now=120)
        Prediction.objects.create(user=self.u2, match=self.match, home_score=4, away_score=2)
        self.client.force_login(self.u1)

    def test_open_match_hides_picks_shows_status(self):
        res = self.client.get(reverse("match_detail", args=[self.match.number]))
        self.assertNotContains(res, "4 - 2")
        self.assertContains(res, "Locked in")
        self.assertContains(res, "Dos")

    def test_locked_match_reveals_picks(self):
        self.match.kickoff = timezone.now() + timedelta(minutes=2)  # ya cerrado (lock 5')
        self.match.save()
        res = self.client.get(reverse("match_detail", args=[self.match.number]))
        self.assertContains(res, "4 - 2")
        self.assertNotContains(res, "Locked in")


class NavVisibilityTests(TestCase):
    def test_regular_user_does_not_see_admin_button(self):
        user = User.objects.create_user("amigo", password="x")
        self.client.force_login(user)
        res = self.client.get(reverse("fixture"))
        self.assertNotContains(res, ">Admin<")
        self.assertNotContains(res, "/admin/")

    def test_staff_user_sees_admin_button(self):
        staff = User.objects.create_user("coqui", password="x", is_staff=True)
        self.client.force_login(staff)
        res = self.client.get(reverse("fixture"))
        self.assertContains(res, "/admin/")

    def test_logout_moved_to_header_and_groups_in_nav(self):
        user = User.objects.create_user("amigo", password="x")
        self.client.force_login(user)
        res = self.client.get(reverse("fixture"))
        content = res.content.decode()
        self.assertIn('class="logout-form"', content)
        nav = content.split('class="bottombar"')[1]
        self.assertNotIn("Log out", nav)
        self.assertIn("Groups", nav)
        self.assertIn('href="/groups/"', nav)

    def test_admin_url_blocks_regular_user(self):
        user = User.objects.create_user("amigo", password="x")
        self.client.force_login(user)
        res = self.client.get("/admin/")
        # Django lo manda al login de admin: no entra ni tipeando la URL.
        self.assertEqual(res.status_code, 302)
        self.assertIn("/admin/login/", res.url)


class TournamentTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("pepe", password="x", first_name="Pepe")
        self.client.force_login(self.user)

    def test_create_makes_owner_member(self):
        self.client.post(reverse("create_tournament"), {"name": "Los Pibes"})
        t = Tournament.objects.get()
        self.assertEqual(t.owner, self.user)
        self.assertIn(self.user, t.members.all())
        self.assertEqual(len(t.code), 6)

    def test_join_via_link(self):
        t = Tournament.objects.create(name="Los Pibes", owner=self.user)
        amigo = User.objects.create_user("amigo", password="x")
        self.client.force_login(amigo)
        res = self.client.get(reverse("join_tournament", args=[t.code.lower()]))
        self.assertRedirects(res, reverse("tournament_detail", args=[t.code]))
        self.assertIn(amigo, t.members.all())

    def test_join_link_sends_anonymous_to_signup_with_code_prefilled(self):
        t = Tournament.objects.create(name="Los Pibes", owner=self.user)
        self.client.logout()
        res = self.client.get(reverse("join_tournament", args=[t.code]))
        self.assertEqual(res.status_code, 302)
        self.assertEqual(res.url, f"/signup/?next=/t/{t.code}/")
        signup = self.client.get(res.url)
        self.assertContains(signup, f'value="{t.code}"')

    def test_full_join_flow_from_invite_link(self):
        t = Tournament.objects.create(name="Los Pibes", owner=self.user)
        self.client.logout()
        res = self.client.post(f"/signup/?next=/t/{t.code}/", {
            "username": "nuevo", "first_name": "Nuevo",
            "password1": "prode123", "password2": "prode123",
            "invite_code": t.code,
            "next": f"/t/{t.code}/",
        }, follow=True)
        self.assertTrue(t.members.filter(username="nuevo").exists())
        self.assertEqual(res.status_code, 200)

    def test_tournament_table_only_includes_members(self):
        t = Tournament.objects.create(name="Los Pibes", owner=self.user)
        t.members.add(self.user)
        User.objects.create_user("ajeno", password="x")
        res = self.client.get(reverse("tournament_detail", args=[t.code]))
        users_in_table = [row["user"].username for row in res.context["table"]]
        self.assertEqual(users_in_table, ["pepe"])

    def test_register_accepts_tournament_code_as_invite(self):
        t = Tournament.objects.create(name="Los Pibes", owner=self.user)
        self.client.logout()
        self.client.post(reverse("register"), {
            "username": "nuevo", "first_name": "Nuevo",
            "password1": "prode123", "password2": "prode123",
            "invite_code": t.code.lower(),
        })
        self.assertTrue(User.objects.filter(username="nuevo").exists())


class FullSimulationTests(TestCase):
    """Simulación punta a punta: 20 usuarios reales por HTTP, fixture real,
    pronósticos, resultados, y verificación independiente de las tablas."""

    N_USERS = 20
    N_MATCHES = 20

    @classmethod
    def setUpTestData(cls):
        call_command("loadfixtures", verbosity=0)

    def expected_points(self, pred, match):
        if (pred.home_score, pred.away_score) == (match.home_score, match.away_score):
            return settings.PRODE_POINTS_EXACT
        sign = lambda a, b: (a > b) - (a < b)
        if sign(pred.home_score, pred.away_score) == sign(match.home_score, match.away_score):
            return settings.PRODE_POINTS_OUTCOME
        return 0

    def test_full_tournament_simulation(self):
        rnd = random.Random(42)
        self.assertEqual(Match.objects.count(), 104)
        self.assertEqual(Team.objects.count(), 48)

        # El torneo real avanza: pasada la fase de grupos ya no quedan 20
        # partidos futuros con equipos en el fixture. Para que la simulación
        # no dependa de la fecha de hoy, tomamos los primeros 20 partidos con
        # equipos definidos y los reabrimos moviendo su kickoff al futuro.
        open_matches = list(
            Match.objects.filter(
                home_team__isnull=False, away_team__isnull=False,
            ).order_by("kickoff")[:self.N_MATCHES]
        )
        self.assertEqual(len(open_matches), self.N_MATCHES)
        future = timezone.now() + timedelta(days=1)
        for i, m in enumerate(open_matches):
            m.kickoff = future + timedelta(hours=i)
            m.save()

        # 20 amigos se registran por el endpoint real y pronostican todo
        users = []
        for i in range(self.N_USERS):
            res = self.client.post(reverse("register"), {
                "username": f"amigo{i}", "first_name": f"Amigo {i}",
                "password1": "prode123", "password2": "prode123",
                "invite_code": "prode2026",
            })
            self.assertEqual(res.status_code, 302)
            users.append(User.objects.get(username=f"amigo{i}"))
            for m in open_matches:
                res = self.client.post(
                    reverse("save_prediction", args=[m.number]),
                    {"home_score": rnd.randint(0, 4), "away_score": rnd.randint(0, 4)},
                    headers={"x-requested-with": "fetch"},
                )
                self.assertTrue(res.json()["ok"], f"fallo guardar P{m.number} para amigo{i}")
            self.client.post(reverse("logout"))
        self.assertEqual(Prediction.objects.count(), self.N_USERS * self.N_MATCHES)

        # El primero crea un torneo, todos los demás entran por el link.
        # Un 21° usuario se registra pero NO se une (no debe aparecer en la tabla).
        self.client.force_login(users[0])
        self.client.post(reverse("create_tournament"), {"name": "Piercei Test"})
        t = Tournament.objects.get(name="Piercei Test")
        for u in users[1:]:
            self.client.force_login(u)
            self.client.get(reverse("join_tournament", args=[t.code]))
        self.client.post(reverse("logout"))
        self.client.post(reverse("register"), {
            "username": "ajeno", "first_name": "Ajeno",
            "password1": "prode123", "password2": "prode123",
            "invite_code": t.code,
        })
        self.assertEqual(t.members.count(), self.N_USERS)

        # Terminan 12 partidos (resultado cargado como lo haría fetchresults/admin)
        finished = open_matches[:12]
        for m in finished:
            m.home_score, m.away_score = rnd.randint(0, 4), rnd.randint(0, 4)
            m.save()

        # Cálculo independiente de lo esperado
        expected = {
            u.id: {"points": 0, "exact": 0, "outcome": 0, "played": 0} for u in users
        }
        for p in Prediction.objects.filter(match__in=finished).select_related("match"):
            if p.user_id not in expected:
                continue
            pts = self.expected_points(p, p.match)
            e = expected[p.user_id]
            e["points"] += pts
            e["played"] += 1
            if pts == settings.PRODE_POINTS_EXACT:
                e["exact"] += 1
            elif pts == settings.PRODE_POINTS_OUTCOME:
                e["outcome"] += 1

        # La tabla del torneo coincide exactamente y excluye al no-miembro
        self.client.force_login(users[0])
        res = self.client.get(reverse("tournament_detail", args=[t.code]))
        table = res.context["table"]
        self.assertEqual(len(table), self.N_USERS)
        self.assertNotIn("ajeno", [r["user"].username for r in table])
        for row in table:
            e = expected[row["user"].id]
            for key in ("points", "exact", "outcome", "played"):
                self.assertEqual(row[key], e[key], f"{key} de {row['user'].username}")
        sort_key = [(-r["points"], -r["exact"]) for r in table]
        self.assertEqual(sort_key, sorted(sort_key), "la tabla no está bien ordenada")

        # El detalle de un partido terminado muestra los 20 pronósticos con puntos
        res = self.client.get(reverse("match_detail", args=[finished[0].number]))
        preds = list(res.context["predictions"])
        self.assertEqual(len(preds), self.N_USERS)
        self.assertTrue(all(p.points is not None for p in preds))

        # Privacidad: el "ajeno" (sin torneo en común) no ve nada del grupo
        self.client.force_login(User.objects.get(username="ajeno"))
        res = self.client.get(reverse("leaderboard"))
        self.assertEqual(res.context["tournament_tables"], [])
        res = self.client.get(reverse("match_detail", args=[finished[0].number]))
        self.assertEqual(len(res.context["predictions"]), 0)
        self.client.force_login(users[0])

        # Un partido terminado ya no acepta cambios
        finished[0].kickoff = timezone.now() - timedelta(hours=2)
        finished[0].save()
        before = Prediction.objects.get(user=users[0], match=finished[0])
        res = self.client.post(
            reverse("save_prediction", args=[finished[0].number]),
            {"home_score": 9, "away_score": 9},
            headers={"x-requested-with": "fetch"},
        )
        self.assertFalse(res.json()["ok"])
        after = Prediction.objects.get(user=users[0], match=finished[0])
        self.assertEqual((before.home_score, before.away_score),
                         (after.home_score, after.away_score))


class LeaderboardTournamentTablesTests(TestCase):
    def test_shows_only_user_tournaments_plus_general(self):
        coqui = User.objects.create_user("coqui2", password="x")
        fede = User.objects.create_user("fede", password="x")
        otro = User.objects.create_user("otro", password="x")
        piercei = Tournament.objects.create(name="Piercei", owner=coqui)
        piercei.members.add(coqui, fede)
        caravana = Tournament.objects.create(name="Caravana", owner=coqui)
        caravana.members.add(coqui)
        ajeno = Tournament.objects.create(name="Ajeno", owner=otro)
        ajeno.members.add(otro)

        self.client.force_login(coqui)
        res = self.client.get(reverse("leaderboard"))
        names = [tt["tournament"].name for tt in res.context["tournament_tables"]]
        self.assertEqual(names, ["Piercei", "Caravana"])
        # No existe tabla general: nadie ve usuarios de otros grupos
        self.assertNotContains(res, "Tabla general")
        self.assertNotContains(res, "otro")

        self.client.force_login(fede)
        res = self.client.get(reverse("leaderboard"))
        names = [tt["tournament"].name for tt in res.context["tournament_tables"]]
        self.assertEqual(names, ["Piercei"])

        self.client.force_login(otro)
        res = self.client.get(reverse("leaderboard"))
        members = [r["user"].username for r in res.context["tournament_tables"][0]["table"]]
        self.assertEqual(members, ["otro"])


class LeaderboardTests(TestCase):
    def test_orders_by_points_then_exact(self):
        match = make_match()
        u1 = User.objects.create_user("uno", password="x", first_name="Uno")
        u2 = User.objects.create_user("dos", password="x", first_name="Dos")
        t = Tournament.objects.create(name="Los Pibes", owner=u1)
        t.members.add(u1, u2)
        Prediction.objects.create(user=u1, match=match, home_score=2, away_score=1)  # exacto
        Prediction.objects.create(user=u2, match=match, home_score=1, away_score=0)  # acierto
        match.home_score, match.away_score = 2, 1
        match.save()
        self.client.force_login(u2)
        res = self.client.get(reverse("leaderboard"))
        table = res.context["tournament_tables"][0]["table"]
        self.assertEqual(table[0]["user"], u1)
        self.assertEqual(table[0]["points"], settings.PRODE_POINTS_EXACT)
        self.assertEqual(table[1]["points"], settings.PRODE_POINTS_OUTCOME)
