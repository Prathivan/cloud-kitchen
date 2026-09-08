import os
import sys

from django.apps import AppConfig


class OrdersConfig(AppConfig):
    name = "orders"

    def ready(self):
        # Only auto-start the in-process scheduler for `runserver`
        # (local development). It's deliberately NOT started for
        # migrate/shell/test/management commands, or when the app is
        # served by gunicorn/uwsgi in production -- see
        # orders/scheduler.py's docstring for why production should use
        # the send_preorder_reminders management command via cron/a
        # systemd timer instead.
        argv = sys.argv
        is_runserver = len(argv) > 1 and argv[1] == "runserver"
        if not is_runserver:
            return

        # runserver's autoreloader loads this app twice: once in a
        # parent "watcher" process (no RUN_MAIN set) and once in the
        # actual child process that serves requests (RUN_MAIN=true).
        # Only the child should start the scheduler. With --noreload
        # there's no watcher process at all, so RUN_MAIN is never set --
        # start immediately in that case.
        autoreload_enabled = "--noreload" not in argv
        if autoreload_enabled and os.environ.get("RUN_MAIN") != "true":
            return

        from . import scheduler
        scheduler.start()
