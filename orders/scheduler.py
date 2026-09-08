"""
In-process background scheduler for the pre-order reminder job.

Chosen over Celery+Redis because this project has no message broker or
worker infrastructure set up, and APScheduler needs none: it runs the
job inside the same Python process as the Django app, on a plain
in-memory/DB-backed schedule. That makes it the fastest option to get
working locally (nothing extra to install and run) while still being a
real, production-usable scheduler (django-apscheduler persists job
run history to the database via the DjangoJobStore).

Trade-off to know about: this only works cleanly with a single running
app process. If you deploy behind multiple gunicorn/uwsgi workers (or
multiple server instances), each process would start its own copy of
this scheduler and the job would fire once per process instead of
once overall. Two ways to handle that in production:

  1. Keep exactly one dedicated worker process responsible for
     scheduling (simplest), or
  2. Don't call start() in the web workers at all, and instead trigger
     `python manage.py send_preorder_reminders` from an external cron
     job / systemd timer every 1-5 minutes. That command runs the exact
     same reminder logic and is naturally safe to run from any number
     of places, since duplicate reminders are prevented in the DB.

See README.md for how to configure option 2 in production.
"""
import logging

logger = logging.getLogger(__name__)

_scheduler = None


def start():
    global _scheduler
    if _scheduler is not None:
        return  # already started in this process

    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.interval import IntervalTrigger
    from django_apscheduler.jobstores import DjangoJobStore, register_events

    from .reminders import send_due_preorder_reminders

    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_jobstore(DjangoJobStore(), "default")

    scheduler.add_job(
        send_due_preorder_reminders,
        trigger=IntervalTrigger(minutes=1),
        id="send_preorder_reminders",
        max_instances=1,
        replace_existing=True,
    )
    register_events(scheduler)
    scheduler.start()
    logger.info("Pre-order reminder scheduler started (checks every 1 minute).")
    _scheduler = scheduler
