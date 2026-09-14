from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import DeliveryAddress

User = get_user_model()


def _address_payload(**overrides):
    payload = {
        "address_label": DeliveryAddress.LABEL_HOME,
        "full_name": "Alice Customer",
        "phone": "+919100000005",
        "address_line_1": "123 Main St",
        "address_line_2": "",
        "building": "",
        "apartment": "",
        "floor": "",
        "street": "",
        "area": "Downtown",
        "city": "Metropolis",
        "state": "State",
        "country": "India",
        "postal_code": "560001",
        "delivery_instructions": "",
        "latitude": "",
        "longitude": "",
        "google_place_id": "",
        "formatted_address": "",
    }
    payload.update(overrides)
    return payload


class DeliveryAddressOwnershipTests(TestCase):
    """Covers add/edit/delete/set-default plus the ownership boundary
    between two different customers' addresses."""

    def setUp(self):
        self.alice = User.objects.create_user("alice", password="pw12345!")
        self.bob = User.objects.create_user("bob", password="pw12345!")
        self.address = DeliveryAddress.objects.create(
            user=self.alice, full_name="Alice", phone="+919100000005",
            address_line_1="123 Main St", city="Metropolis", state="State",
            postal_code="560001", is_default=True,
        )

    def test_add_address_creates_it_for_the_logged_in_user(self):
        self.client.force_login(self.bob)
        resp = self.client.post(reverse("address_add"), _address_payload(full_name="Bob"))
        self.assertRedirects(resp, reverse("address_list"))
        address = DeliveryAddress.objects.get(user=self.bob)
        self.assertEqual(address.full_name, "Bob")
        # A customer's very first address is auto-defaulted.
        self.assertTrue(address.is_default)

    def test_address_list_only_shows_own_addresses(self):
        DeliveryAddress.objects.create(
            user=self.bob, full_name="Bob", phone="+919100000018",
            address_line_1="456 Side St", city="Gotham", state="State", postal_code="100001",
        )
        self.client.force_login(self.alice)
        resp = self.client.get(reverse("address_list"))
        self.assertContains(resp, "Alice")
        self.assertNotContains(resp, "456 Side St")

    def test_customer_cannot_edit_another_customers_address(self):
        self.client.force_login(self.bob)
        resp = self.client.get(reverse("address_edit", args=[self.address.id]))
        self.assertEqual(resp.status_code, 404)

    def test_customer_cannot_delete_another_customers_address(self):
        self.client.force_login(self.bob)
        resp = self.client.post(reverse("address_delete", args=[self.address.id]))
        self.assertEqual(resp.status_code, 404)
        self.assertTrue(DeliveryAddress.objects.filter(pk=self.address.id).exists())

    def test_customer_cannot_set_another_customers_address_as_default(self):
        self.client.force_login(self.bob)
        resp = self.client.post(reverse("address_set_default", args=[self.address.id]))
        self.assertEqual(resp.status_code, 404)

    def test_edit_own_address_updates_it(self):
        self.client.force_login(self.alice)
        resp = self.client.post(
            reverse("address_edit", args=[self.address.id]),
            _address_payload(full_name="Alice Updated", city="New City"),
        )
        self.assertRedirects(resp, reverse("address_list"))
        self.address.refresh_from_db()
        self.assertEqual(self.address.full_name, "Alice Updated")
        self.assertEqual(self.address.city, "New City")

    def test_setting_new_default_unsets_previous_default(self):
        second = DeliveryAddress.objects.create(
            user=self.alice, full_name="Alice Work", phone="+919100000005",
            address_line_1="Office Rd", city="Metropolis", state="State", postal_code="560002",
        )
        self.client.force_login(self.alice)
        self.client.post(reverse("address_set_default", args=[second.id]))
        self.address.refresh_from_db()
        second.refresh_from_db()
        self.assertFalse(self.address.is_default)
        self.assertTrue(second.is_default)

    def test_deleting_default_address_promotes_another(self):
        second = DeliveryAddress.objects.create(
            user=self.alice, full_name="Alice Work", phone="+919100000005",
            address_line_1="Office Rd", city="Metropolis", state="State", postal_code="560002",
        )
        self.client.force_login(self.alice)
        self.client.post(reverse("address_delete", args=[self.address.id]))
        second.refresh_from_db()
        self.assertTrue(second.is_default)

    def test_invalid_phone_rejected(self):
        self.client.force_login(self.bob)
        resp = self.client.post(reverse("address_add"), _address_payload(phone="not-a-number"))
        self.assertEqual(resp.status_code, 200)  # re-rendered with errors
        self.assertFalse(DeliveryAddress.objects.filter(user=self.bob).exists())

    def test_lone_latitude_without_longitude_rejected(self):
        self.client.force_login(self.bob)
        resp = self.client.post(reverse("address_add"), _address_payload(latitude="12.9716"))
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(DeliveryAddress.objects.filter(user=self.bob).exists())

    def test_anonymous_user_redirected_to_login(self):
        resp = self.client.get(reverse("address_list"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login/", resp.url)

    def test_address_label_renders_as_radio_buttons_not_dropdown(self):
        """
        Regression test: address_label previously fell back to Django's
        default Select widget (a dropdown) because the form never set
        widget=RadioSelect explicitly, which produced garbled duplicate
        text when the template looped over it expecting radio inputs.
        """
        self.client.force_login(self.bob)
        resp = self.client.get(reverse("address_add"))
        self.assertContains(resp, 'type="radio"')
        self.assertNotContains(resp, "<select", msg_prefix="address_label must not render as a dropdown")

    def test_address_saves_successfully_with_no_map_data(self):
        """
        Regression test: saving an address with every map-related field
        left blank (latitude/longitude/place_id/formatted_address) must
        succeed -- these are optional, not a prerequisite for saving.
        """
        self.client.force_login(self.bob)
        resp = self.client.post(reverse("address_add"), _address_payload())
        self.assertRedirects(resp, reverse("address_list"))
        address = DeliveryAddress.objects.get(user=self.bob)
        self.assertIsNone(address.latitude)
        self.assertIsNone(address.longitude)
