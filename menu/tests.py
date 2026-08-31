import datetime

from django.test import TestCase
from django.utils import timezone

from menu.models import Category, MenuItem


def make_item(**kwargs):
    category = Category.objects.create(name="Mains")
    defaults = dict(
        category=category,
        name="Butter Chicken",
        price="250.00",
        is_available=True,
        is_selling_unit_tracking=False,
        per_day_selling_units=0,
        total_selling_units=0,
        available_tracking=False,
    )
    defaults.update(kwargs)
    return MenuItem.objects.create(**defaults)


class SellingUnitTrackingTests(TestCase):
    def test_total_selling_units_always_tracked_even_when_tracking_disabled(self):
        item = make_item(is_selling_unit_tracking=False)
        item.register_confirmed_sale(5)
        item.register_confirmed_sale(10)
        item.register_confirmed_sale(20)
        item.refresh_from_db()
        self.assertEqual(item.total_selling_units, 35)

    def test_cart_add_remove_does_not_increment_total_selling_units(self):
        # register_confirmed_sale is the only path that increments the
        # counter; cart mutations never call it directly.
        item = make_item()
        self.assertEqual(item.total_selling_units, 0)

    def test_limit_not_enforced_when_tracking_disabled(self):
        item = make_item(
            is_selling_unit_tracking=False,
            per_day_selling_units=100,
            total_selling_units=150,
        )
        self.assertFalse(item.is_selling_limit_reached())
        self.assertIsNone(item.remaining_selling_units())
        self.assertTrue(item.is_currently_orderable())

    def test_limit_enforced_when_tracking_enabled(self):
        item = make_item(
            is_selling_unit_tracking=True,
            per_day_selling_units=100,
            total_selling_units=70,
        )
        self.assertEqual(item.remaining_selling_units(), 30)
        self.assertFalse(item.is_selling_limit_reached())
        self.assertTrue(item.is_currently_orderable())

    def test_limit_reached_makes_item_unorderable(self):
        item = make_item(
            is_selling_unit_tracking=True,
            per_day_selling_units=100,
            total_selling_units=100,
        )
        self.assertTrue(item.is_selling_limit_reached())
        self.assertFalse(item.is_currently_orderable())
        self.assertEqual(item.remaining_selling_units(), 0)


class DailyResetTests(TestCase):
    def test_reset_when_tracked_day_is_stale(self):
        yesterday = timezone.localdate() - datetime.timedelta(days=1)
        item = make_item(
            is_selling_unit_tracking=True,
            per_day_selling_units=100,
            total_selling_units=100,
            selling_units_date=yesterday,
        )
        # Stale day -> treated as 0 sold today, regardless of tracking flag.
        self.assertEqual(item.remaining_selling_units(), 100)
        self.assertFalse(item.is_selling_limit_reached())

    def test_reset_applies_regardless_of_tracking_flag(self):
        yesterday = timezone.localdate() - datetime.timedelta(days=1)
        item = make_item(
            is_selling_unit_tracking=False,
            total_selling_units=42,
            selling_units_date=yesterday,
        )
        item.register_confirmed_sale(3)
        item.refresh_from_db()
        # Old count was wiped by the day rollover before the new sale
        # was added.
        self.assertEqual(item.total_selling_units, 3)

    def test_historical_orders_untouched_by_reset(self):
        # reset only affects the counter field on MenuItem, never the
        # Order/OrderItem history rows themselves.
        yesterday = timezone.localdate() - datetime.timedelta(days=1)
        item = make_item(
            is_selling_unit_tracking=True,
            per_day_selling_units=50,
            total_selling_units=50,
            selling_units_date=yesterday,
        )
        item.reset_units_if_new_day()
        self.assertEqual(item.total_selling_units, 0)
        self.assertEqual(item.selling_units_date, timezone.localdate())


class TimeAvailabilityTests(TestCase):
    def test_time_restriction_ignored_when_tracking_disabled(self):
        item = make_item(
            available_tracking=False,
            is_available_from=datetime.time(11, 0),
            is_available_till=datetime.time(15, 0),
        )
        self.assertTrue(item.is_within_available_time(at=datetime.time(20, 0)))

    def test_time_restriction_enforced_when_tracking_enabled(self):
        item = make_item(
            available_tracking=True,
            is_available_from=datetime.time(11, 0),
            is_available_till=datetime.time(15, 0),
        )
        self.assertTrue(item.is_within_available_time(at=datetime.time(13, 0)))
        self.assertFalse(item.is_within_available_time(at=datetime.time(10, 0)))
        self.assertFalse(item.is_within_available_time(at=datetime.time(20, 0)))


class CombinedAvailabilityTests(TestCase):
    def test_all_conditions_enabled_within_window_and_under_limit(self):
        item = make_item(
            is_available=True,
            is_selling_unit_tracking=True,
            per_day_selling_units=100,
            total_selling_units=70,
            available_tracking=True,
            is_available_from=datetime.time(11, 0),
            is_available_till=datetime.time(15, 0),
        )
        self.assertTrue(item.is_within_available_time(at=datetime.time(13, 0)))
        self.assertFalse(item.is_selling_limit_reached())

    def test_both_tracking_features_disabled_follows_is_available(self):
        item = make_item(
            is_available=True,
            is_selling_unit_tracking=False,
            available_tracking=False,
        )
        self.assertTrue(item.is_currently_orderable())

        item.is_available = False
        item.save()
        self.assertFalse(item.is_currently_orderable())
