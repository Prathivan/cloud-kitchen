from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from menu.models import Category, CustomerReview, MenuItem, RunningOffer


class HomeMenuCartRenderTests(TestCase):
    def setUp(self):
        cat = Category.objects.create(name="Mains")
        self.item1 = MenuItem.objects.create(
            category=cat, name="Chicken Biryani", price="199.00",
            is_chef_special=True, is_popular=True, food_type="non_veg",
            has_offer=True, offer_price="149.00",
        )
        self.item2 = MenuItem.objects.create(
            category=cat, name="Veg Thali", price="179.00",
            is_chef_special=True, food_type="veg",
        )
        self.item3 = MenuItem.objects.create(
            category=cat, name="Oreo Shake", price="99.00",
            is_popular=True, food_type="veg",
        )
        RunningOffer.objects.create(
            title="Weekend Offer", description="20% off all orders",
            is_active=True, button_text="Order Now", button_link="https://example.com",
        )
        RunningOffer.objects.create(title="Combo Deal", description="Buy 2 Get 1", is_active=True)
        CustomerReview.objects.create(customer_name="Asha", review_text="Fresh food!", rating=5)
        CustomerReview.objects.create(customer_name="Ravi", review_text="Loved it.", rating=4)
        self.user = User.objects.create_user("tester", password="pw12345!")

    def test_home_renders_with_full_data(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Homemade Goodness")
        self.assertContains(response, "Chicken Biryani")
        self.assertContains(response, "Weekend Offer")
        self.assertContains(response, "Asha")

    def test_home_renders_with_no_optional_data(self):
        MenuItem.objects.all().delete()
        RunningOffer.objects.all().delete()
        CustomerReview.objects.all().delete()
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Today's Chef Special")
        self.assertNotContains(response, "Running Offers")

    def test_home_renders_with_single_chef_special_no_slider_controls(self):
        self.item2.is_chef_special = False
        self.item2.save()
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Chicken Biryani")
        self.assertNotContains(response, "Veg Thali")

    def test_menu_renders_offer_price_and_dot(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("menu"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "price-offer")
        self.assertContains(response, "food-type-dot")

    def test_cart_renders_effective_price(self):
        self.client.force_login(self.user)
        self.client.post(reverse("add_to_cart", args=[self.item1.id]))
        response = self.client.get(reverse("cart"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "149")

    def test_add_to_cart_ajax_returns_cart_count(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("add_to_cart", args=[self.item1.id]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        data = response.json()
        self.assertEqual(data["cart_count"], 1)

        response2 = self.client.post(
            reverse("add_to_cart", args=[self.item3.id]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        data2 = response2.json()
        self.assertEqual(data2["cart_count"], 2)

    def test_offer_price_validation_rejects_invalid(self):
        from django.core.exceptions import ValidationError
        bad_item = MenuItem(
            category=self.item1.category,
            name="Bad Offer",
            price="100.00",
            has_offer=True,
            offer_price="150.00",  # >= price, invalid
        )
        with self.assertRaises(ValidationError):
            bad_item.full_clean()

    def test_effective_price_used_at_checkout(self):
        self.client.force_login(self.user)
        self.client.post(reverse("add_to_cart", args=[self.item1.id]))
        self.client.post(reverse("checkout"))
        from orders.models import OrderItem
        order_item = OrderItem.objects.get(menu_item=self.item1)
        self.assertEqual(str(order_item.price), "149.00")
