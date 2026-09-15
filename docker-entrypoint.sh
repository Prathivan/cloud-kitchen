#!/usr/bin/env bash
# Runs every time the container STARTS (not just once at build time,
# unlike Render's build.sh) -- this is the right place for
# collectstatic/migrate/ensure_superuser on platforms that deploy
# containers, since environment variables like DATABASE_URL and
# SECRET_KEY are typically only available at container runtime, not
# during the earlier `docker build` step.
set -o errexit

python manage.py collectstatic --no-input
python manage.py migrate

# Same Shell-free superuser bootstrap used on Render -- does nothing
# unless DJANGO_SUPERUSER_USERNAME/EMAIL/PASSWORD are set as container
# environment variables. See
# accounts/management/commands/ensure_superuser.py for the full
# explanation.
python manage.py ensure_superuser

exec gunicorn config.wsgi:application --bind "0.0.0.0:${PORT:-8000}"
