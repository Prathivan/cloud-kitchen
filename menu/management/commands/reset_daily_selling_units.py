from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from menu.models import MenuItem


class Command(BaseCommand):
    """
    Resets total_selling_units to 0 for any MenuItem whose tracked day
    (selling_units_date) is not today.

    total_selling_units is also reset lazily whenever a confirmed order is
    processed (see MenuItem.register_confirmed_sale), so correctness does
    not depend on this command running. It exists so the counter is
    visibly reset at midnight even for items nobody orders that day (e.g.
    for admin dashboards), and should be scheduled to run once daily at
    00:00 in the project's configured timezone (this project has no
    scheduler such as Celery/APScheduler installed, so wire this up with
    the OS's own scheduler, e.g. a cron entry or Windows Task Scheduler
    task):

        0 0 * * *  cd /path/to/project && python manage.py reset_daily_selling_units
    """

    help = "Reset total_selling_units to 0 for menu items whose tracked day has passed."

    def handle(self, *args, **options):
        today = timezone.localdate()
        stale_items = MenuItem.objects.exclude(selling_units_date=today)

        updated = 0
        with transaction.atomic():
            for item in stale_items.select_for_update():
                if item.reset_units_if_new_day():
                    item.save(update_fields=["total_selling_units", "selling_units_date"])
                    updated += 1

        self.stdout.write(
            self.style.SUCCESS(f"Reset total_selling_units for {updated} menu item(s).")
        )
