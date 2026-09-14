"""
Pre-order reminder logic.

Shared by two entry points that both just call `send_due_preorder_reminders()`:

  1. The in-process APScheduler job (orders/scheduler.py), which runs
     automatically every minute while `runserver`/the app server is up --
     nothing extra to run locally.
  2. The `send_preorder_reminders` management command, for production
     setups that prefer an external cron/systemd-timer trigger instead
     of (or alongside) the in-process scheduler.

Keeping the logic in one place means both entry points share the exact
same duplicate-prevention and "due" definition.
"""
import logging

from django.utils import timezone

logger = logging.getLogger(__name__)


def send_due_preorder_reminders():
    """
    Find pre-orders whose fulfillment time is within the next hour and
    haven't already had a reminder created, create an AdminNotification
    for each, and mark them so they're never reminded twice.

    Returns the number of reminders created (mainly useful for the
    management command's console output / tests).
    """
    from .models import AdminNotification, Order

    now = timezone.now()
    reminder_window_end = now + timezone.timedelta(hours=1)

    # "Due for a reminder" = pre-order, not yet reminded, and its
    # fulfillment time falls at-or-before (now + 1 hour). Orders whose
    # fulfillment time has already passed still get a (late) reminder
    # rather than silently never notifying anyone, since a missed run
    # (e.g. server down for 10 minutes) shouldn't mean the kitchen never
    # finds out at all.
    due_orders = Order.objects.filter(
        is_preorder=True,
        preorder_reminder_sent=False,
        preorder_datetime__isnull=False,
        preorder_datetime__lte=reminder_window_end,
    ).exclude(status=Order.STATUS_CANCELLED)

    created = 0
    for order in due_orders:
        # select_for_update-style safety isn't needed here: this task
        # runs on a single schedule, but we still guard against a
        # duplicate by re-checking preorder_reminder_sent right before
        # writing, in case two runs somehow overlapped.
        updated = Order.objects.filter(
            pk=order.pk, preorder_reminder_sent=False
        ).update(preorder_reminder_sent=True)
        if not updated:
            continue  # another run already handled this order

        message = f"Pre-order #ORD{order.id:05d} is due in 1 hour."
        AdminNotification.objects.create(
            notification_type=AdminNotification.TYPE_PREORDER_REMINDER,
            message=message,
            order=order,
        )
        logger.info("Pre-order reminder created for order #%s", order.id)
        created += 1

    return created
