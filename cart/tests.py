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


class CartMixingPreventionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("mixer", password="pw12345!")
        category = Category.objects.create(name="Mains")
        self.normal_item = MenuItem.objects.create(
            category=category, name="Fried Rice", price="150.00", is_available=True,
        )
        self.preorder_item = MenuItem.objects.create(
            category=category, name="Custom Cake", price="1200.00",
            is_available=True, is_preorder=True, preorder_hours=24,
        )
        self.client.force_login(self.user)

    def test_adding_preorder_item_to_normal_cart_is_blocked(self):
        CartItem.objects.create(user=self.user, menu_item=self.normal_item, quantity=1)
        response = self.client.post(
            reverse("add_to_cart", args=[self.preorder_item.id]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        data = response.json()
        self.assertFalse(data["ok"])
        self.assertTrue(data.get("conflict"))
        self.assertFalse(
            CartItem.objects.filter(user=self.user, menu_item=self.preorder_item).exists()
        )

    def test_adding_normal_item_to_preorder_cart_is_blocked(self):
        CartItem.objects.create(user=self.user, menu_item=self.preorder_item, quantity=1)
        response = self.client.post(
            reverse("add_to_cart", args=[self.normal_item.id]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        data = response.json()
        self.assertFalse(data["ok"])
        self.assertTrue(data.get("conflict"))

    def test_force_clears_cart_and_switches_order_type(self):
        CartItem.objects.create(user=self.user, menu_item=self.normal_item, quantity=1)
        response = self.client.post(
            reverse("add_to_cart", args=[self.preorder_item.id]),
            {"force": "1"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        data = response.json()
        self.assertTrue(data["ok"])
        cart_items = CartItem.objects.filter(user=self.user)
        self.assertEqual(cart_items.count(), 1)
        self.assertEqual(cart_items.first().menu_item, self.preorder_item)

    def test_same_type_items_can_both_be_added(self):
        second_preorder_item = MenuItem.objects.create(
            category=self.preorder_item.category, name="Another Cake", price="900.00",
            is_available=True, is_preorder=True, preorder_hours=48,
        )
        self.client.post(reverse("add_to_cart", args=[self.preorder_item.id]))
        self.client.post(reverse("add_to_cart", args=[second_preorder_item.id]))
        self.assertEqual(CartItem.objects.filter(user=self.user).count(), 2)

    def test_clear_cart_empties_it(self):
        CartItem.objects.create(user=self.user, menu_item=self.normal_item, quantity=1)
        self.client.post(reverse("clear_cart"))
        self.assertEqual(CartItem.objects.filter(user=self.user).count(), 0)


class StaleCartItemHandlingTests(TestCase):
    """
    Covers the reported bug: after a cart is cleared (e.g. via the
    normal/pre-order switch, or the Clear Cart button), a quantity
    +/- form still rendered client-side for the old CartItem id must
    not blow up with an unhandled 404 -- the backend should respond
    gracefully so the frontend can resync instead.
    """

    def setUp(self):
        self.user = User.objects.create_user("staleuser", password="pw12345!")
        category = Category.objects.create(name="Mains")
        self.item = MenuItem.objects.create(
            category=category, name="Fried Rice", price="150.00", is_available=True,
        )
        self.client.force_login(self.user)

    def test_update_quantity_on_deleted_cart_item_returns_ok_json_not_404(self):
        cart_item = CartItem.objects.create(user=self.user, menu_item=self.item, quantity=2)
        stale_id = cart_item.id
        CartItem.objects.filter(id=stale_id).delete()  # simulate a cart clear elsewhere

        response = self.client.post(
            reverse("update_cart_quantity", args=[stale_id]),
            {"quantity": 3},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["ok"])
        self.assertTrue(data.get("stale"))
        self.assertFalse(data["in_cart"])

    def test_update_quantity_on_deleted_cart_item_non_ajax_redirects_cleanly(self):
        cart_item = CartItem.objects.create(user=self.user, menu_item=self.item, quantity=2)
        stale_id = cart_item.id
        CartItem.objects.filter(id=stale_id).delete()

        response = self.client.post(
            reverse("update_cart_quantity", args=[stale_id]),
            {"quantity": 3},
        )
        # A graceful redirect, never an unhandled 404 page.
        self.assertEqual(response.status_code, 302)

    def test_removing_an_already_removed_cart_item_is_idempotent(self):
        cart_item = CartItem.objects.create(user=self.user, menu_item=self.item, quantity=1)
        stale_id = cart_item.id
        CartItem.objects.filter(id=stale_id).delete()

        response = self.client.post(
            reverse("remove_from_cart", args=[stale_id]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertFalse(data["in_cart"])

    def test_new_cart_item_id_works_after_force_switch(self):
        preorder_item = MenuItem.objects.create(
            category=self.item.category, name="Custom Cake", price="900.00",
            is_available=True, is_preorder=True, preorder_hours=24,
        )
        old_cart_item = CartItem.objects.create(user=self.user, menu_item=self.item, quantity=1)

        # Force-switch: clears the normal cart and adds the pre-order item.
        self.client.post(
            reverse("add_to_cart", args=[preorder_item.id]),
            {"force": "1"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertFalse(CartItem.objects.filter(id=old_cart_item.id).exists())

        new_cart_item = CartItem.objects.get(user=self.user, menu_item=preorder_item)
        response = self.client.post(
            reverse("update_cart_quantity", args=[new_cart_item.id]),
            {"quantity": 2},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["quantity"], 2)
