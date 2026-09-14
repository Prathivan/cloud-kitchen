"""
Creates a superuser from environment variables, if (and only if) one
doesn't already exist AS AN ADMIN with that username -- safe to run on
EVERY deploy, not just the first one.

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

IMPORTANT -- username collisions with an existing NON-admin account:
if DJANGO_SUPERUSER_USERNAME matches a username that already exists
but ISN'T staff/superuser yet (e.g. you already signed up through the
site's normal signup form using that same name, before setting these
env vars), this command PROMOTES that existing account to
staff+superuser and sets its password to DJANGO_SUPERUSER_PASSWORD,
rather than silently leaving a mismatched, unusable account behind.
This only ever happens ONCE per account: after promotion, the account
already satisfies is_staff+is_superuser, so every later deploy just
skips it like any other already-admin account -- your password is
never silently reset on routine redeploys.

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
    help = "Creates (or promotes) a superuser from DJANGO_SUPERUSER_* env vars."

    def handle(self, *args, **options):
        username = os.environ.get("DJANGO_SUPERUSER_USERNAME")
        email = os.environ.get("DJANGO_SUPERUSER_EMAIL")
        password = os.environ.get("DJANGO_SUPERUSER_PASSWORD")

        if not (username and email and password):
            self.stdout.write("DJANGO_SUPERUSER_* env vars not fully set -- skipping.")
            return

        existing = User.objects.filter(username=username).first()

        if existing is None:
            User.objects.create_superuser(username=username, email=email, password=password)
            self.stdout.write(self.style.SUCCESS(f'Superuser "{username}" created.'))
            return

        if existing.is_staff and existing.is_superuser:
            self.stdout.write(f'Superuser "{username}" already exists -- skipping.')
            return

        # Exists, but as a non-admin account (e.g. a regular customer
        # signup using the same username) -- promote it rather than
        # leaving a same-named account the operator clearly intended
        # to be their admin login stuck non-functional. See the
        # module docstring for why this is safe to do unconditionally.
        existing.is_staff = True
        existing.is_superuser = True
        existing.email = email
        existing.set_password(password)
        existing.save(update_fields=["is_staff", "is_superuser", "email", "password"])
        self.stdout.write(
            self.style.WARNING(
                f'"{username}" already existed as a non-admin account -- promoted it to '
                f"superuser and updated its password/email to match your env vars."
            )
        )
