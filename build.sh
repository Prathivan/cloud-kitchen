#!/usr/bin/env bash
# Render runs this as the "Build Command" for the web service.
# Exit immediately if any command fails, so a broken build never
# silently deploys.
set -o errexit

pip install -r requirements.txt

# Gathers every app's static files into STATIC_ROOT (see
# config/settings.py) so WhiteNoise can serve them in production.
python manage.py collectstatic --no-input

# Applies any pending migrations on every deploy -- this is what makes
# the database schema "set up automatically": push to GitHub, Render
# rebuilds, and the database is already in sync by the time the new
# code starts serving traffic. Safe to run on every deploy even when
# there's nothing new to apply.
python manage.py migrate

# Creates your first admin login automatically, on hosts (like Render's
# free/Hobby tier) that don't give you a Shell tab to run
# `createsuperuser` interactively. Does nothing unless you've set
# DJANGO_SUPERUSER_USERNAME/EMAIL/PASSWORD as environment variables on
# your host -- see accounts/management/commands/ensure_superuser.py
# for the full explanation. Safe to run on every deploy either way.
python manage.py ensure_superuser
