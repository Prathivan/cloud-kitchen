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
        self.assertEqual(order.status, Order.STATUS_CONFIRMED)
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
        # each requested 3, the combined confirmed total must never
        # exceed the daily limit.
        self.assertLessEqual(self.item.total_selling_units, 100)
        confirmed_orders = Order.objects.filter(status=Order.STATUS_CONFIRMED)
        confirmed_quantity = sum(
            oi.quantity for order in confirmed_orders for oi in order.items.all()
        )
        self.assertLessEqual(95 + confirmed_quantity, 100)
