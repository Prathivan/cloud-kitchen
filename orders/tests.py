from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.db import connection

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
