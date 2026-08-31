from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from cart.models import CartItem
from menu.models import Category, MenuItem


class CartFlowTests(TestCase):
    def setUp(self):
        self.user_a = User.objects.create_user("alice", password="pw12345!")
        self.user_b = User.objects.create_user("bob", password="pw12345!")
        category = Category.objects.create(name="Mains")
        self.item = MenuItem.objects.create(
            category=category,
            name="Paneer Tikka",
            price="180.00",
            is_available=True,
            is_selling_unit_tracking=False,
            available_tracking=False,
        )

    def _login(self, user):
        self.client.force_login(user)

    def test_add_item_creates_cart_row_with_quantity_one(self):
        self._login(self.user_a)
        self.client.post(reverse("add_to_cart", args=[self.item.id]))
        cart_item = CartItem.objects.get(user=self.user_a, menu_item=self.item)
        self.assertEqual(cart_item.quantity, 1)

    def test_add_item_again_increments_existing_row_not_duplicates(self):
        self._login(self.user_a)
        self.client.post(reverse("add_to_cart", args=[self.item.id]))
        self.client.post(reverse("add_to_cart", args=[self.item.id]))
        self.assertEqual(
            CartItem.objects.filter(user=self.user_a, menu_item=self.item).count(), 1
        )
        cart_item = CartItem.objects.get(user=self.user_a, menu_item=self.item)
        self.assertEqual(cart_item.quantity, 2)

    def test_quantity_reaching_zero_removes_item(self):
        self._login(self.user_a)
        cart_item = CartItem.objects.create(user=self.user_a, menu_item=self.item, quantity=1)
        self.client.post(
            reverse("update_cart_quantity", args=[cart_item.id]),
            {"quantity": 0},
        )
        self.assertFalse(CartItem.objects.filter(id=cart_item.id).exists())

    def test_cannot_add_unavailable_item(self):
        self.item.is_available = False
        self.item.save()
        self._login(self.user_a)
        self.client.post(reverse("add_to_cart", args=[self.item.id]))
        self.assertFalse(
            CartItem.objects.filter(user=self.user_a, menu_item=self.item).exists()
        )

    def test_menu_page_only_shows_own_cart_state(self):
        CartItem.objects.create(user=self.user_b, menu_item=self.item, quantity=3)
        self._login(self.user_a)
        response = self.client.get(reverse("menu"))
        page_item = response.context["menu_items"][0]
        # Alice hasn't added anything -- Bob's cart row must not leak in.
        self.assertIsNone(page_item.cart_item)

    def test_cart_page_only_shows_own_items(self):
        CartItem.objects.create(user=self.user_b, menu_item=self.item, quantity=3)
        self._login(self.user_a)
        response = self.client.get(reverse("cart"))
        self.assertEqual(len(response.context["cart_items"]), 0)

    def test_user_cannot_remove_another_users_cart_item(self):
        bob_item = CartItem.objects.create(user=self.user_b, menu_item=self.item, quantity=2)
        self._login(self.user_a)
        self.client.post(reverse("remove_from_cart", args=[bob_item.id]))
        self.assertTrue(CartItem.objects.filter(id=bob_item.id).exists())

    def test_user_cannot_update_another_users_cart_item(self):
        bob_item = CartItem.objects.create(user=self.user_b, menu_item=self.item, quantity=2)
        self._login(self.user_a)
        self.client.post(
            reverse("update_cart_quantity", args=[bob_item.id]),
            {"quantity": 99},
        )
        bob_item.refresh_from_db()
        self.assertEqual(bob_item.quantity, 2)

    def test_ajax_add_returns_json(self):
        self._login(self.user_a)
        response = self.client.post(
            reverse("add_to_cart", args=[self.item.id]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertTrue(data["in_cart"])
        self.assertEqual(data["quantity"], 1)

    def test_increase_capped_at_remaining_selling_units(self):
        self.item.is_selling_unit_tracking = True
        self.item.per_day_selling_units = 5
        self.item.total_selling_units = 3
        self.item.save()

        self._login(self.user_a)
        cart_item = CartItem.objects.create(user=self.user_a, menu_item=self.item, quantity=2)
        response = self.client.post(
            reverse("update_cart_quantity", args=[cart_item.id]),
            {"quantity": 10},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        data = response.json()
        self.assertFalse(data["ok"])
        cart_item.refresh_from_db()
        self.assertEqual(cart_item.quantity, 2)
