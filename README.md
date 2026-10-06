# World Cup 2026 Pool

Prediction pool ("prode") for the 2026 World Cup, built to share with friends or coworkers. Django + Postgres on Railway, English UI, every visitor sees kickoff times in their own timezone.


## Rules

- Sign up with an **invite code**, pick a score for every match from your own account.
- Picks can be changed until **5 minutes before kickoff** (configurable, enforced server-side).
- Scoring: **6 pts** exact score, **3 pts** correct outcome (winner or draw). Knockout matches count the **90-minute result**; penalties are never predicted.
- **Anti-copy:** other people's picks stay hidden until the match locks (you only see "Locked in ✓").
- **Private leagues:** anyone can create a league, share a join link/code, and compete on a private leaderboard. Picks are made once and count in every league you join. There is no global leaderboard: you only ever see people you share a league with.

## How results load (automatic)

`start.sh` runs `fetchresults` every 5 minutes alongside gunicorn:

1. **ESPN public scoreboard** (no key, near-realtime): fast path for group-stage results.
2. **football-data.org** (free token): backup source, knockout bracket auto-assignment, and 90-minute vs extra-time detection. Matches that end in extra time/penalties are flagged for manual entry of the 90' score (admin, two clicks).

Results never overwrite a manually entered score. Both sources tolerate reversed home/away listings.

## Deploy (Railway)

One web service + Postgres. The Procfile runs `start.sh`: migrate, collectstatic, load fixture, ensure admin, fetch loop, gunicorn (3 workers). All idempotent.

| Env var | Required | Notes |
|---|---|---|
| `SECRET_KEY` | yes | App refuses to boot on Railway without it |
| `DATABASE_URL` | yes | Reference to the Postgres service |
| `CSRF_TRUSTED_ORIGINS` | yes | `https://<your-domain>` |
| `INVITE_CODE` | recommended | Site-wide signup code (league codes also work) |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | recommended | Superuser for `/admin/` |
| `FOOTBALL_DATA_TOKEN` | recommended | Free at football-data.org |
| `LOCK_MINUTES` | no (5) | Prediction lock window |
| `POINTS_EXACT` / `POINTS_OUTCOME` | no (6/3) | Scoring |

## Development

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python manage.py migrate
.venv\Scripts\python manage.py loadfixtures
.venv\Scripts\python manage.py test
```

`data/fixtures.json` is the source of truth for the 104-match schedule (verified against the API). `loadfixtures` runs on every boot and never touches scores or admin-assigned knockout teams, but it does reset kickoff times from the JSON: schedule changes go in the file, not in the admin.
