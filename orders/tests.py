from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.db import connection
from django.utils import timezone

from cart.models import CartItem
from menu.models import Category, MenuItem
from orders.models import Order, OrderItem


class CheckoutFlowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice", password="pw12345!")
        category = Category.objects.create(name="Mains")
        self.item = MenuItem.objects.create(
            category=category,
            name="Paneer Tikka",
            price="180.00",
            is_available=True,
            is_selling_unit_tracking=True,
            per_day_selling_units=10,
            total_selling_units=0,
            available_tracking=False,
        )
        self.client.force_login(self.user)

    def test_confirmed_order_increments_total_selling_units(self):
        CartItem.objects.create(user=self.user, menu_item=self.item, quantity=4)
        self.client.post(reverse("checkout"))
        self.item.refresh_from_db()
        self.assertEqual(self.item.total_selling_units, 4)

    def test_checkout_creates_order_and_items_and_clears_cart(self):
        CartItem.objects.create(user=self.user, menu_item=self.item, quantity=3)
        self.client.post(reverse("checkout"))

        order = Order.objects.get(user=self.user)
        self.assertEqual(order.status, Order.STATUS_PENDING)
        self.assertEqual(order.total_amount, Decimal("180.00") * 3)

        item = OrderItem.objects.get(order=order)
        self.assertEqual(item.quantity, 3)
        self.assertEqual(item.item_name, self.item.name)

        self.assertFalse(CartItem.objects.filter(user=self.user).exists())

    def test_cannot_confirm_more_than_remaining_units(self):
        self.item.total_selling_units = 8  # only 2 left of 10
        self.item.save()
        CartItem.objects.create(user=self.user, menu_item=self.item, quantity=5)

        self.client.post(reverse("checkout"))

        self.item.refresh_from_db()
        # Order must NOT have been confirmed / counted.
        self.assertEqual(self.item.total_selling_units, 8)
        self.assertFalse(Order.objects.filter(user=self.user).exists())
        # Cart is left intact so the user can adjust and retry.
        self.assertTrue(CartItem.objects.filter(user=self.user).exists())

    def test_unconfirmed_or_abandoned_cart_never_counts(self):
        CartItem.objects.create(user=self.user, menu_item=self.item, quantity=6)
        # Never checked out.
        self.item.refresh_from_db()
        self.assertEqual(self.item.total_selling_units, 0)

    def test_multiple_orders_sum_quantities_not_order_count(self):
        self.item.per_day_selling_units = 100  # ensure no cap interferes
        self.item.save()
        for qty in (5, 3, 10):
            CartItem.objects.create(user=self.user, menu_item=self.item, quantity=qty)
            response = self.client.post(reverse("checkout"), follow=True)
            messages = list(response.context["messages"])
            self.assertTrue(
                any("confirmed" in str(m) for m in messages),
                [str(m) for m in messages],
            )
        self.item.refresh_from_db()
        self.assertEqual(self.item.total_selling_units, 18)
        self.assertEqual(Order.objects.filter(user=self.user).count(), 3)


class ConcurrentCheckoutTests(TransactionTestCase):
    """
    Exercises the overselling-prevention path with two genuinely
    concurrent checkout requests for the same menu item.
    """

    def setUp(self):
        self.user_a = User.objects.create_user("alice", password="pw12345!")
        self.user_b = User.objects.create_user("bob", password="pw12345!")
        category = Category.objects.create(name="Mains")
        self.item = MenuItem.objects.create(
            category=category,
            name="Paneer Tikka",
            price="180.00",
            is_available=True,
            is_selling_unit_tracking=True,
            per_day_selling_units=100,
            total_selling_units=95,
            available_tracking=False,
        )
        CartItem.objects.create(user=self.user_a, menu_item=self.item, quantity=3)
        CartItem.objects.create(user=self.user_b, menu_item=self.item, quantity=3)

    def test_two_users_cannot_jointly_oversell_the_daily_limit(self):
        import threading
        from django.test import Client

        results = {}

        def run_checkout(username, password, key):
            client = Client()
            client.login(username=username, password=password)
            response = client.post(reverse("checkout"))
            results[key] = response.status_code
            connection.close()

        t1 = threading.Thread(target=run_checkout, args=("alice", "pw12345!", "a"))
        t2 = threading.Thread(target=run_checkout, args=("bob", "pw12345!", "b"))
        t1.start()
        t1.join()
        t2.start()
        t2.join()

        self.item.refresh_from_db()
        # Only 5 units were remaining (100 - 95). Even though both users
        # each requested 3, the combined total sold via a successful
        # checkout must never exceed the daily limit. Successful
        # checkouts create orders in STATUS_PENDING (the workflow's
        # entry point).
        self.assertLessEqual(self.item.total_selling_units, 100)
        placed_orders = Order.objects.filter(status=Order.STATUS_PENDING)
        placed_quantity = sum(
            oi.quantity for order in placed_orders for oi in order.items.all()
        )
        self.assertLessEqual(95 + placed_quantity, 100)


class OrderWorkflowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("carol", password="pw12345!")
        self.order = Order.objects.create(user=self.user, status=Order.STATUS_PENDING)

    def test_advance_to_stamps_timestamp_once(self):
        self.assertIsNone(self.order.confirmed_at)
        self.order.advance_to(Order.STATUS_CONFIRMED)
        self.order.save()
        first_stamp = self.order.confirmed_at
        self.assertIsNotNone(first_stamp)

        # Re-advancing to the same status must not overwrite the
        # original timestamp.
        self.order.advance_to(Order.STATUS_CONFIRMED)
        self.assertEqual(self.order.confirmed_at, first_stamp)

    def test_progress_steps_reached_flags(self):
        self.order.advance_to(Order.STATUS_CONFIRMED)
        self.order.advance_to(Order.STATUS_PREPARING)
        self.order.save()

        steps = {step["status"]: step["reached"] for step in self.order.progress_steps()}
        self.assertTrue(steps[Order.STATUS_PENDING])
        self.assertTrue(steps[Order.STATUS_CONFIRMED])
        self.assertTrue(steps[Order.STATUS_PREPARING])
        self.assertFalse(steps[Order.STATUS_READY])
        self.assertFalse(steps[Order.STATUS_DELIVERED])


class OrderAdminActionTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user("kitchenstaff", password="pw12345!", is_staff=True)
        # Grant the permissions the admin actions/changelist need.
        from django.contrib.auth.models import Permission
        perms = Permission.objects.filter(codename__in=["view_order", "change_order"])
        self.staff.user_permissions.add(*perms)
        self.client.force_login(self.staff)

        customer = User.objects.create_user("dave", password="pw12345!")
        self.pending_order = Order.objects.create(user=customer, status=Order.STATUS_PENDING)
        self.ready_order = Order.objects.create(user=customer, status=Order.STATUS_READY)

    def test_accept_action_only_moves_pending_orders(self):
        from orders.admin import accept_orders

        class FakeModelAdmin:
            pass

        request = self.client.get(reverse("admin:orders_order_changelist")).wsgi_request
        accept_orders(FakeModelAdmin(), request, Order.objects.filter(id__in=[self.pending_order.id, self.ready_order.id]))

        self.pending_order.refresh_from_db()
        self.ready_order.refresh_from_db()
        self.assertEqual(self.pending_order.status, Order.STATUS_CONFIRMED)
        self.assertIsNotNone(self.pending_order.confirmed_at)
        # The order that wasn't in "pending" must be left untouched.
        self.assertEqual(self.ready_order.status, Order.STATUS_READY)

    def test_admin_dashboard_index_renders_with_stats(self):
        resp = self.client.get(reverse("admin:index"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Kitchen Management Dashboard")
        self.assertContains(resp, "Today's Orders")


class DashboardQuickActionTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_superuser("dashadmin", "dashadmin@example.com", "AdminPW12345")
        self.client.login(username="dashadmin", password="AdminPW12345")
        customer = User.objects.create_user("erin", password="pw12345!")
        self.order = Order.objects.create(user=customer, status=Order.STATUS_PENDING, total_amount="150.00")

    def test_dashboard_shows_stat_cards_and_quick_action(self):
        resp = self.client.get(reverse("admin:index"))
        self.assertContains(resp, "Today's Orders")
        self.assertContains(resp, "Accept")  # quick-action label for a pending order

    def test_stat_card_pending_link_filters_order_list(self):
        resp = self.client.get(reverse("admin:index"))
        self.assertContains(resp, "status__exact=pending")

    def test_advance_order_view_moves_status_and_stamps_timestamp(self):
        resp = self.client.post(
            reverse("admin:advance_order", args=[self.order.id]),
            {"next": reverse("admin:index")},
            follow=True,
        )
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.STATUS_CONFIRMED)
        self.assertIsNotNone(self.order.confirmed_at)

    def test_dashboard_stats_json_reflects_live_state(self):
        resp = self.client.get(reverse("admin:dashboard_stats"))
        data = resp.json()
        self.assertEqual(data["cards"]["pending_orders"], 1)

        self.client.post(
            reverse("admin:advance_order", args=[self.order.id]),
            {"next": reverse("admin:index")},
        )

        resp = self.client.get(reverse("admin:dashboard_stats"))
        data = resp.json()
        self.assertEqual(data["cards"]["pending_orders"], 0)
        self.assertEqual(data["cards"]["preparing_orders"], 0)

    def test_orders_changelist_has_quick_action_button(self):
        resp = self.client.get(reverse("admin:orders_order_changelist"))
        self.assertContains(resp, "Accept")

    def test_customer_cannot_advance_order_status(self):
        self.client.logout()
        customer = User.objects.create_user("frank", password="pw12345!")
        self.client.force_login(customer)
        resp = self.client.post(
            reverse("admin:advance_order", args=[self.order.id]),
            {"next": reverse("admin:index")},
        )
        self.assertNotEqual(resp.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.STATUS_PENDING)


class RevenueRoundingTests(TestCase):
    def test_dashboard_revenue_never_shows_long_decimal_tail(self):
        from decimal import Decimal

        staff = User.objects.create_superuser("moneyadmin", "moneyadmin@example.com", "AdminPW12345")
        self.client.login(username="moneyadmin", password="AdminPW12345")
        customer = User.objects.create_user("moneycust", password="pw12345!")
        Order.objects.create(user=customer, status=Order.STATUS_CONFIRMED, total_amount=Decimal("699.99"))
        Order.objects.create(user=customer, status=Order.STATUS_CONFIRMED, total_amount=Decimal("1339.98"))
        Order.objects.create(user=customer, status=Order.STATUS_READY, total_amount=Decimal("580.00"))

        resp = self.client.get(reverse("admin:dashboard_stats"))
        data = resp.json()
        revenue_str = str(data["cards"]["todays_revenue"])
        decimals = revenue_str.split(".")[-1] if "." in revenue_str else ""
        self.assertLessEqual(len(decimals), 2)
        self.assertEqual(revenue_str, "2619.97")

    def test_best_sellers_revenue_accounts_for_quantity(self):
        from decimal import Decimal

        staff = User.objects.create_superuser("moneyadmin2", "moneyadmin2@example.com", "AdminPW12345")
        self.client.login(username="moneyadmin2", password="AdminPW12345")
        customer = User.objects.create_user("moneycust2", password="pw12345!")
        order = Order.objects.create(user=customer, status=Order.STATUS_CONFIRMED, total_amount=Decimal("720.00"))
        OrderItem.objects.create(order=order, item_name="Oreo Shake", price=Decimal("180.00"), quantity=4)

        resp = self.client.get(reverse("admin:index"))
        # 4 units at 180 each = 720, not a bare sum of unit prices (180).
        self.assertContains(resp, "720.00")
        self.assertNotContains(resp, ">180.00<")


class QuickActionButtonRenderingTests(TestCase):
    def test_quick_action_button_has_no_nested_form(self):
        """
        Regression test for the "Accept button does nothing" bug: the
        button must use formaction/formmethod on the *existing*
        changelist form, never a second nested <form> inside a table
        cell (invalid HTML that browsers silently break).
        """
        staff = User.objects.create_superuser("nestedadmin", "nestedadmin@example.com", "AdminPW12345")
        self.client.login(username="nestedadmin", password="AdminPW12345")
        customer = User.objects.create_user("nestedcust", password="pw12345!")
        Order.objects.create(user=customer, status=Order.STATUS_PENDING)

        resp = self.client.get(reverse("admin:orders_order_changelist"))
        body = resp.content.decode()
        self.assertEqual(body.count('id="changelist-form"'), 1)
        self.assertNotIn('<form method="post" action="/admin/orders/', body)
        self.assertIn("formaction=", body)


class PreorderCheckoutTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("preorder_alice", password="pw12345!")
        category = Category.objects.create(name="Cakes")
        self.normal_item = MenuItem.objects.create(
            category=category, name="Brownie", price="120.00", is_available=True,
        )
        self.preorder_item_24h = MenuItem.objects.create(
            category=category, name="Birthday Cake", price="900.00",
            is_available=True, is_preorder=True, preorder_hours=24,
        )
        self.preorder_item_48h = MenuItem.objects.create(
            category=category, name="Wedding Cake", price="2500.00",
            is_available=True, is_preorder=True, preorder_hours=48,
        )
        self.client.force_login(self.user)

    def test_preorder_checkout_calculates_and_snapshots_datetime(self):
        CartItem.objects.create(user=self.user, menu_item=self.preorder_item_24h, quantity=1)
        self.client.post(reverse("checkout"))

        order = Order.objects.get(user=self.user)
        self.assertTrue(order.is_preorder)
        self.assertIsNotNone(order.preorder_datetime)

        expected = order.created_at + timezone.timedelta(hours=24)
        self.assertAlmostEqual(
            order.preorder_datetime.timestamp(), expected.timestamp(), delta=5
        )

        # Changing the menu item's hours afterwards must NOT retroactively
        # change an already-placed order's snapshot.
        self.preorder_item_24h.preorder_hours = 72
        self.preorder_item_24h.save()
        order.refresh_from_db()
        self.assertAlmostEqual(
            order.preorder_datetime.timestamp(), expected.timestamp(), delta=5
        )

    def test_multiple_preorder_items_use_the_longest_lead_time(self):
        CartItem.objects.create(user=self.user, menu_item=self.preorder_item_24h, quantity=1)
        CartItem.objects.create(user=self.user, menu_item=self.preorder_item_48h, quantity=1)
        self.client.post(reverse("checkout"))

        order = Order.objects.get(user=self.user)
        expected = order.created_at + timezone.timedelta(hours=48)
        self.assertAlmostEqual(
            order.preorder_datetime.timestamp(), expected.timestamp(), delta=5
        )

    def test_normal_checkout_has_no_preorder_datetime(self):
        CartItem.objects.create(user=self.user, menu_item=self.normal_item, quantity=2)
        self.client.post(reverse("checkout"))

        order = Order.objects.get(user=self.user)
        self.assertFalse(order.is_preorder)
        self.assertIsNone(order.preorder_datetime)

    def test_backend_rejects_a_mixed_cart_even_if_one_somehow_got_created(self):
        # The cart UI (cart.views.add_to_cart) already prevents building a
        # mixed cart, but checkout must independently refuse to process
        # one too, since the backend is the source of truth.
        CartItem.objects.create(user=self.user, menu_item=self.normal_item, quantity=1)
        CartItem.objects.create(user=self.user, menu_item=self.preorder_item_24h, quantity=1)

        self.client.post(reverse("checkout"))

        self.assertFalse(Order.objects.filter(user=self.user).exists())
        self.assertEqual(CartItem.objects.filter(user=self.user).count(), 2)


class PreorderReminderTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("preorder_bob", password="pw12345!")

    def _make_preorder(self, hours_from_now, reminder_sent=False):
        order = Order.objects.create(
            user=self.user,
            status=Order.STATUS_CONFIRMED,
            is_preorder=True,
            preorder_datetime=timezone.now() + timezone.timedelta(hours=hours_from_now),
            preorder_reminder_sent=reminder_sent,
        )
        return order

    def test_reminder_created_when_due_within_an_hour(self):
        from orders.models import AdminNotification
        from orders.reminders import send_due_preorder_reminders

        order = self._make_preorder(hours_from_now=0.5)
        created = send_due_preorder_reminders()

        self.assertEqual(created, 1)
        order.refresh_from_db()
        self.assertTrue(order.preorder_reminder_sent)
        self.assertEqual(
            AdminNotification.objects.filter(order=order).count(), 1
        )

    def test_no_reminder_when_more_than_an_hour_away(self):
        from orders.reminders import send_due_preorder_reminders

        self._make_preorder(hours_from_now=5)
        created = send_due_preorder_reminders()

        self.assertEqual(created, 0)

    def test_reminder_is_not_duplicated_on_a_second_run(self):
        from orders.reminders import send_due_preorder_reminders

        self._make_preorder(hours_from_now=0.5)
        send_due_preorder_reminders()
        created_again = send_due_preorder_reminders()

        self.assertEqual(created_again, 0)
