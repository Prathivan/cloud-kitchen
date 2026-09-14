from django.core.management.base import BaseCommand

from orders.reminders import send_due_preorder_reminders


class Command(BaseCommand):
    help = (
        "Check for pre-orders due within the next hour and create an admin "
        "notification for each one that hasn't already been reminded. "
        "Intended to be triggered every 1-5 minutes by an external "
        "scheduler (cron, systemd timer, etc.) in production -- see "
        "README.md for setup examples. Safe to run repeatedly: it never "
        "creates a duplicate reminder for the same order."
    )

    def handle(self, *args, **options):
        created = send_due_preorder_reminders()
        if created:
            self.stdout.write(self.style.SUCCESS(f"Created {created} pre-order reminder(s)."))
        else:
            self.stdout.write("No pre-orders due for a reminder right now.")
