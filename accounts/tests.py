from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import CustomerProfile

User = get_user_model()


class SignupTests(TestCase):
    def _signup_payload(self, **overrides):
        payload = {
            "full_name": "Test Customer",
            "mobile_number": "+15551234567",
            "email": "test.customer@example.com",
            "password": "SupErStrongPW123",
            "confirm_password": "SupErStrongPW123",
        }
        payload.update(overrides)
        return payload

    def test_signup_creates_customer_only_account(self):
        resp = self.client.post(reverse("signup"), self._signup_payload(), follow=True)
        self.assertEqual(resp.redirect_chain[-1][0], reverse("home"))

        user = User.objects.get(email="test.customer@example.com")
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

        profile = CustomerProfile.objects.get(user=user)
        self.assertEqual(profile.role, CustomerProfile.ROLE_CUSTOMER)
        self.assertEqual(profile.mobile_number, "+15551234567")

        # Signing up logs the customer straight into the website.
        self.assertTrue(resp.context["user"].is_authenticated) if hasattr(resp, "context") else None

    def test_duplicate_email_rejected(self):
        self.client.post(reverse("signup"), self._signup_payload())
        self.client.get(reverse("logout"))
        resp = self.client.post(
            reverse("signup"),
            self._signup_payload(mobile_number="+15559999999"),
        )
        self.assertContains(resp, "An account with this email address already exists.")

    def test_duplicate_mobile_rejected(self):
        self.client.post(reverse("signup"), self._signup_payload())
        self.client.get(reverse("logout"))
        resp = self.client.post(
            reverse("signup"),
            self._signup_payload(email="someone.else@example.com"),
        )
        self.assertContains(resp, "An account with this mobile number already exists.")

    def test_password_mismatch_rejected(self):
        resp = self.client.post(
            reverse("signup"),
            self._signup_payload(confirm_password="Different123"),
        )
        self.assertContains(resp, "Passwords do not match.")

    def test_invalid_mobile_rejected(self):
        resp = self.client.post(
            reverse("signup"),
            self._signup_payload(mobile_number="not-a-number"),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(User.objects.filter(email="test.customer@example.com").exists())


class CustomerAdminAccessTests(TestCase):
    def setUp(self):
        self.client.post(
            reverse("signup"),
            {
                "full_name": "Test Customer",
                "mobile_number": "+15551234567",
                "email": "test.customer@example.com",
                "password": "SupErStrongPW123",
                "confirm_password": "SupErStrongPW123",
            },
        )

    def test_customer_cannot_reach_admin(self):
        resp = self.client.get("/admin/")
        self.assertNotEqual(resp.status_code, 200)

    def test_customer_cannot_escalate_privileges_via_account_form(self):
        user = User.objects.get(email="test.customer@example.com")
        profile = CustomerProfile.objects.get(user=user)

        self.client.post(
            reverse("account"),
            {
                "full_name": "Test Customer",
                "mobile_number": "+15551234567",
                "email": "test.customer@example.com",
                "is_staff": "true",
                "is_superuser": "true",
                "role": "admin",
            },
        )

        user.refresh_from_db()
        profile.refresh_from_db()
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertEqual(profile.role, CustomerProfile.ROLE_CUSTOMER)

    def test_customer_cannot_access_another_customers_profile_data(self):
        self.client.get(reverse("logout"))
        self.client.post(
            reverse("signup"),
            {
                "full_name": "Second Customer",
                "mobile_number": "+15559998888",
                "email": "second.customer@example.com",
                "password": "AnotherStrongPW123",
                "confirm_password": "AnotherStrongPW123",
            },
        )
        # Now logged in as the second customer; the account page must only
        # ever show/save their own data, never the first customer's.
        resp = self.client.get(reverse("account"))
        self.assertNotContains(resp, "test.customer@example.com")
        self.assertContains(resp, "second.customer@example.com")


class AdminStaffAccessTests(TestCase):
    def test_admin_access_still_works(self):
        User.objects.create_superuser("siteadmin", "admin@example.com", "AdminPW12345")
        self.client.login(username="siteadmin", password="AdminPW12345")
        resp = self.client.get("/admin/")
        self.assertEqual(resp.status_code, 200)

    def test_staff_access_still_works(self):
        User.objects.create_user(
            "sitestaff", "staff@example.com", "StaffPW12345", is_staff=True
        )
        self.client.login(username="sitestaff", password="StaffPW12345")
        resp = self.client.get("/admin/")
        self.assertEqual(resp.status_code, 200)
