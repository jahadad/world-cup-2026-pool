#!/usr/bin/env bash
set -e

python manage.py migrate --noinput
python manage.py createcachetable
python manage.py collectstatic --noinput
# Estos dos no deben tumbar el sitio si fallan: la base ya tiene los datos.
python manage.py loadfixtures || true
python manage.py ensure_admin || true

# Resultados y cruces de eliminación: se actualizan solos cada 5 minutos.
# Ventana de 14 días: una caída larga se autorepara sin backfill manual.
(
  while true; do
    python manage.py fetchresults --days 14 || true
    sleep 300
  done
) &

exec gunicorn config.wsgi:application --bind 0.0.0.0:"$PORT" --workers 3 --access-logfile -
