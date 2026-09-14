"""
Creates a superuser from environment variables, if (and only if) one
doesn't already exist with that username -- safe to run on EVERY
deploy, not just the first one.

This exists specifically for hosts like Render's free/Hobby tier,
which don't give you a Shell tab to run `createsuperuser`
interactively. Set these three env vars once in your host's dashboard,
and this command (already wired into build.sh) creates the account
automatically on the next deploy:

    DJANGO_SUPERUSER_USERNAME=admin
    DJANGO_SUPERUSER_EMAIL=admin@example.com
    DJANGO_SUPERUSER_PASSWORD=a-real-password-not-this-one

If any of the three are missing, this command does nothing (silently)
-- so it's safe to leave in build.sh even for local development, where
you'd normally just run `createsuperuser` yourself instead.

Security note: once your admin account exists and you've confirmed you
can log in, remove DJANGO_SUPERUSER_PASSWORD from your host's
environment variables (leaving USERNAME/EMAIL set is harmless, but
there's no reason to leave a plaintext password sitting in your
dashboard longer than it takes to bootstrap the account).
"""

import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

User = get_user_model()


class Command(BaseCommand):
    help = "Creates a superuser from DJANGO_SUPERUSER_* env vars if one doesn't already exist."

    def handle(self, *args, **options):
        username = os.environ.get("DJANGO_SUPERUSER_USERNAME")
        email = os.environ.get("DJANGO_SUPERUSER_EMAIL")
        password = os.environ.get("DJANGO_SUPERUSER_PASSWORD")

        if not (username and email and password):
            self.stdout.write("DJANGO_SUPERUSER_* env vars not fully set -- skipping.")
            return

        if User.objects.filter(username=username).exists():
            self.stdout.write(f'Superuser "{username}" already exists -- skipping.')
            return

        User.objects.create_superuser(username=username, email=email, password=password)
        self.stdout.write(self.style.SUCCESS(f'Superuser "{username}" created.'))
