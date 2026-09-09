from unittest.mock import patch

import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from . import otp_service
from .models import CustomerProfile, OTPVerification
from .views import SESSION_VERIFIED_MOBILE

User = get_user_model()


def set_session_value(client, key, value):
    """
    Test helper: writes a value into `client`'s session and makes sure
    the test client will actually SEND that session back on its next
    request.

    `client.session` + `.save()` alone isn't enough whenever the client
    has no session cookie yet (e.g. right after logout(), which clears
    it) -- .save() creates the row in the DB, but nothing tells the
    test client's cookie jar about the new session_key, so the very
    next request looks anonymous again and the value appears to
    vanish. Setting the cookie explicitly closes that gap.
    """
    session = client.session
    session[key] = value
    session.save()
    client.cookies[settings.SESSION_COOKIE_NAME] = session.session_key


def signup_via_client(client, payload, **post_kwargs):
    """
    Shared test helper for the many tests below that need a customer
    account created through the real signup view but don't care about
    the OTP flow itself (that flow has its own dedicated coverage in
    OTPFlowTests). Marks the payload's mobile number verified in the
    session first -- the same state a real customer's session would be
    in after completing steps 1-2 of the signup form -- then submits
    the actual signup POST.
    """
    set_session_value(client, SESSION_VERIFIED_MOBILE, payload["mobile_number"])
    return client.post(reverse("signup"), payload, **post_kwargs)


class SignupTests(TestCase):
    """
    Mobile numbers must be OTP-verified (see OTPFlowTests below) before
    signup_view will create an account. These tests aren't about the
    OTP flow itself, so they use _verify_mobile() to put the session
    straight into the "already verified" state signup_view checks for,
    the same way a customer would arrive there after actually
    completing steps 1-2 of the form.
    """

    def _verify_mobile(self, mobile_number):
        set_session_value(self.client, SESSION_VERIFIED_MOBILE, mobile_number)

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
        self._verify_mobile("+15551234567")
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

        # The verified-mobile flag is one-time-use: it's cleared from
        # the session once the account it was for has been created.
        self.assertNotIn(SESSION_VERIFIED_MOBILE, self.client.session)

    def test_signup_blocked_without_otp_verification(self):
        # No _verify_mobile() call here -- nothing has verified this
        # mobile number in this session, so signup must be refused
        # even though every other field is valid.
        resp = self.client.post(reverse("signup"), self._signup_payload())
        self.assertContains(resp, "Please verify this mobile number")
        self.assertFalse(User.objects.filter(email="test.customer@example.com").exists())

    def test_signup_blocked_if_verified_number_does_not_match_submitted_number(self):
        self._verify_mobile("+15551234567")
        resp = self.client.post(
            reverse("signup"),
            self._signup_payload(mobile_number="+15550000000"),
        )
        self.assertContains(resp, "Please verify this mobile number")
        self.assertFalse(User.objects.filter(email="test.customer@example.com").exists())

    def test_duplicate_email_rejected(self):
        self._verify_mobile("+15551234567")
        self.client.post(reverse("signup"), self._signup_payload())
        self.client.get(reverse("logout"))
        self._verify_mobile("+15559999999")
        resp = self.client.post(
            reverse("signup"),
            self._signup_payload(mobile_number="+15559999999"),
        )
        self.assertContains(resp, "An account with this email address already exists.")

    def test_duplicate_mobile_rejected(self):
        self._verify_mobile("+15551234567")
        self.client.post(reverse("signup"), self._signup_payload())
        self.client.get(reverse("logout"))
        self._verify_mobile("+15551234567")
        resp = self.client.post(
            reverse("signup"),
            self._signup_payload(email="someone.else@example.com"),
        )
        self.assertContains(resp, "An account with this mobile number already exists.")

    def test_password_mismatch_rejected(self):
        self._verify_mobile("+15551234567")
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


class OTPFlowTests(TestCase):
    """
    Covers the send-code / verify-code endpoints behind signup's mobile
    verification step, independent of the rest of the signup form.
    """

    def _send_otp(self, mobile_number="+15551234567", channel="sms"):
        return self.client.post(
            reverse("send_otp"), {"mobile_number": mobile_number, "channel": channel}
        )

    def _latest_code_for(self, mobile_number):
        # Test-only shortcut: read the actual code the same way
        # otp_service._send_via_console would have printed it, by
        # regenerating from the stored hash isn't possible (it's
        # hashed), so instead we patch create_for's send in each test
        # that needs the real code -- see test_full_verify_success.
        return OTPVerification.objects.filter(mobile_number=mobile_number).latest("created_at")

    def test_send_otp_creates_record_and_calls_send_stub(self):
        with patch("accounts.views.otp_service.send_otp") as mock_send:
            resp = self._send_otp()
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])
        self.assertEqual(OTPVerification.objects.filter(mobile_number="+15551234567").count(), 1)
        mock_send.assert_called_once()
        called_mobile, called_channel, called_code = mock_send.call_args[0]
        self.assertEqual(called_mobile, "+15551234567")
        self.assertEqual(called_channel, "sms")
        self.assertEqual(len(called_code), OTPVerification.CODE_LENGTH)

    def test_send_otp_rejects_invalid_mobile_number(self):
        resp = self._send_otp(mobile_number="not-a-number")
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(resp.json()["ok"])

    def test_send_otp_rejects_invalid_channel(self):
        resp = self._send_otp(channel="carrier-pigeon")
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(resp.json()["ok"])

    def test_send_otp_rejects_already_registered_mobile(self):
        User.objects.create_user(username="existing@example.com", email="existing@example.com", password="x")
        CustomerProfile.objects.create(user=User.objects.get(email="existing@example.com"),
                                        full_name="Existing", mobile_number="+15551234567")
        resp = self._send_otp()
        self.assertEqual(resp.status_code, 400)
        self.assertIn("already exists", resp.json()["error"])

    def test_send_otp_enforces_resend_cooldown(self):
        with patch("accounts.views.otp_service.send_otp"):
            self._send_otp()
            resp = self._send_otp()
        self.assertEqual(resp.status_code, 429)
        self.assertFalse(resp.json()["ok"])
        self.assertGreater(resp.json()["cooldown"], 0)

    def test_send_otp_includes_debug_code_when_debug_true(self):
        with self.settings(DEBUG=True), patch("accounts.views.otp_service.send_otp") as mock_send:
            resp = self._send_otp()
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertIn("debug_code", data)
        otp = self._latest_code_for("+15551234567")
        self.assertTrue(otp.check_code(data["debug_code"]))

    def test_send_otp_hides_debug_code_when_debug_false(self):
        with self.settings(DEBUG=False), patch("accounts.views.otp_service.send_otp"):
            resp = self._send_otp()
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertNotIn("debug_code", data)

    def test_full_verify_success_sets_session(self):
        captured = {}

        def fake_send(mobile_number, channel, code):
            captured["code"] = code
            return True

        with patch("accounts.views.otp_service.send_otp", side_effect=fake_send):
            self._send_otp()

        resp = self.client.post(
            reverse("verify_otp"), {"mobile_number": "+15551234567", "code": captured["code"]}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])
        self.assertEqual(self.client.session[SESSION_VERIFIED_MOBILE], "+15551234567")

        otp = self._latest_code_for("+15551234567")
        self.assertTrue(otp.is_verified)
        self.assertIsNotNone(otp.verified_at)

    def test_verify_with_wrong_code_increments_attempts_and_fails(self):
        with patch("accounts.views.otp_service.send_otp"):
            self._send_otp()

        resp = self.client.post(
            reverse("verify_otp"), {"mobile_number": "+15551234567", "code": "000000"}
        )
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(resp.json()["ok"])
        self.assertNotIn(SESSION_VERIFIED_MOBILE, self.client.session)

        otp = self._latest_code_for("+15551234567")
        self.assertEqual(otp.attempts, 1)

    def test_verify_locks_out_after_max_attempts(self):
        with patch("accounts.views.otp_service.send_otp"):
            self._send_otp()

        for _ in range(OTPVerification.MAX_ATTEMPTS):
            self.client.post(reverse("verify_otp"), {"mobile_number": "+15551234567", "code": "000000"})

        resp = self.client.post(
            reverse("verify_otp"), {"mobile_number": "+15551234567", "code": "000000"}
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Too many incorrect attempts", resp.json()["error"])

    def test_verify_rejects_expired_code(self):
        with patch("accounts.views.otp_service.send_otp"):
            self._send_otp()

        otp = self._latest_code_for("+15551234567")
        otp.expires_at = timezone.now() - timezone.timedelta(minutes=1)
        otp.save(update_fields=["expires_at"])

        resp = self.client.post(
            reverse("verify_otp"), {"mobile_number": "+15551234567", "code": "123456"}
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("expired", resp.json()["error"])

    def test_verify_without_pending_code_fails(self):
        resp = self.client.post(
            reverse("verify_otp"), {"mobile_number": "+15559990000", "code": "123456"}
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("No pending code", resp.json()["error"])

    def test_end_to_end_signup_via_real_otp_flow(self):
        """
        Full happy path a real customer would take: request a code,
        verify it, then submit the rest of the signup form -- with no
        session shortcuts, unlike SignupTests above.
        """
        captured = {}

        def fake_send(mobile_number, channel, code):
            captured["code"] = code
            return True

        with patch("accounts.views.otp_service.send_otp", side_effect=fake_send):
            send_resp = self._send_otp(channel="whatsapp")
        self.assertTrue(send_resp.json()["ok"])

        verify_resp = self.client.post(
            reverse("verify_otp"), {"mobile_number": "+15551234567", "code": captured["code"]}
        )
        self.assertTrue(verify_resp.json()["ok"])

        signup_resp = self.client.post(
            reverse("signup"),
            {
                "full_name": "Real Flow Customer",
                "mobile_number": "+15551234567",
                "email": "real.flow@example.com",
                "password": "SupErStrongPW123",
                "confirm_password": "SupErStrongPW123",
            },
            follow=True,
        )
        self.assertEqual(signup_resp.redirect_chain[-1][0], reverse("home"))
        self.assertTrue(User.objects.filter(email="real.flow@example.com").exists())


class MSG91OTPServiceTests(TestCase):
    """
    Covers accounts.otp_service's MSG91 integration in isolation, with
    requests.post always mocked -- these never make a real network
    call, and none of them touch OTP_PROVIDER's actual configured
    value (they patch it per-test), so they can't accidentally send a
    real SMS/WhatsApp message even if MSG91 credentials are set in the
    environment they run in.
    """

    def _fake_response(self, status_code=200, text="{}"):
        response = type("FakeResponse", (), {})()
        response.status_code = status_code
        response.text = text
        return response

    def test_falls_back_to_console_without_auth_key(self):
        with patch("accounts.otp_service.OTP_PROVIDER", "msg91"), \
             patch("accounts.otp_service.MSG91_AUTH_KEY", ""), \
             patch("accounts.otp_service.requests.post") as mock_post:
            result = otp_service.send_otp("+919876543210", "sms", "123456")
        self.assertTrue(result)
        mock_post.assert_not_called()

    def test_sms_missing_sender_or_template_falls_back_to_console(self):
        with patch("accounts.otp_service.OTP_PROVIDER", "msg91"), \
             patch("accounts.otp_service.MSG91_AUTH_KEY", "key"), \
             patch("accounts.otp_service.MSG91_SMS_SENDER_ID", ""), \
             patch("accounts.otp_service.requests.post") as mock_post:
            result = otp_service.send_otp("+919876543210", "sms", "123456")
        self.assertTrue(result)
        mock_post.assert_not_called()

    def test_sms_success_posts_expected_payload(self):
        with patch("accounts.otp_service.OTP_PROVIDER", "msg91"), \
             patch("accounts.otp_service.MSG91_AUTH_KEY", "key"), \
             patch("accounts.otp_service.MSG91_SMS_SENDER_ID", "BUTKTN"), \
             patch("accounts.otp_service.MSG91_SMS_DLT_TEMPLATE_ID", "12345"), \
             patch("accounts.otp_service.requests.post", return_value=self._fake_response(200)) as mock_post:
            result = otp_service.send_otp("+919876543210", "sms", "123456")

        self.assertTrue(result)
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], otp_service.MSG91_SMS_URL)
        self.assertEqual(kwargs["headers"]["authkey"], "key")
        self.assertEqual(kwargs["json"]["sender"], "BUTKTN")
        self.assertEqual(kwargs["json"]["DLT_TE_ID"], "12345")
        self.assertEqual(kwargs["json"]["sms"][0]["to"], ["919876543210"])
        self.assertIn("123456", kwargs["json"]["sms"][0]["message"])

    def test_sms_error_response_returns_false(self):
        with patch("accounts.otp_service.OTP_PROVIDER", "msg91"), \
             patch("accounts.otp_service.MSG91_AUTH_KEY", "key"), \
             patch("accounts.otp_service.MSG91_SMS_SENDER_ID", "BUTKTN"), \
             patch("accounts.otp_service.MSG91_SMS_DLT_TEMPLATE_ID", "12345"), \
             patch("accounts.otp_service.requests.post", return_value=self._fake_response(401, "bad authkey")):
            result = otp_service.send_otp("+919876543210", "sms", "123456")
        self.assertFalse(result)

    def test_whatsapp_missing_config_falls_back_to_console(self):
        with patch("accounts.otp_service.OTP_PROVIDER", "msg91"), \
             patch("accounts.otp_service.MSG91_AUTH_KEY", "key"), \
             patch("accounts.otp_service.MSG91_WHATSAPP_TEMPLATE_NAME", ""), \
             patch("accounts.otp_service.requests.post") as mock_post:
            result = otp_service.send_otp("+919876543210", "whatsapp", "123456")
        self.assertTrue(result)
        mock_post.assert_not_called()

    def test_whatsapp_success_posts_expected_payload(self):
        with patch("accounts.otp_service.OTP_PROVIDER", "msg91"), \
             patch("accounts.otp_service.MSG91_AUTH_KEY", "key"), \
             patch("accounts.otp_service.MSG91_WHATSAPP_INTEGRATED_NUMBER", "919999999999"), \
             patch("accounts.otp_service.MSG91_WHATSAPP_TEMPLATE_NAME", "otp_verification"), \
             patch("accounts.otp_service.MSG91_WHATSAPP_NAMESPACE", "ns-123"), \
             patch("accounts.otp_service.requests.post", return_value=self._fake_response(200)) as mock_post:
            result = otp_service.send_otp("+919876543210", "whatsapp", "654321")

        self.assertTrue(result)
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], otp_service.MSG91_WHATSAPP_URL)
        payload = kwargs["json"]["payload"]
        self.assertEqual(payload["template"]["name"], "otp_verification")
        self.assertEqual(payload["template"]["namespace"], "ns-123")
        to_and_components = payload["template"]["to_and_components"][0]
        self.assertEqual(to_and_components["to"], ["919876543210"])
        self.assertEqual(to_and_components["components"]["body_1"]["value"], "654321")

    def test_request_exception_returns_false(self):
        with patch("accounts.otp_service.OTP_PROVIDER", "msg91"), \
             patch("accounts.otp_service.MSG91_AUTH_KEY", "key"), \
             patch("accounts.otp_service.MSG91_SMS_SENDER_ID", "BUTKTN"), \
             patch("accounts.otp_service.MSG91_SMS_DLT_TEMPLATE_ID", "12345"), \
             patch("accounts.otp_service.requests.post", side_effect=requests.RequestException("boom")):
            result = otp_service.send_otp("+919876543210", "sms", "123456")
        self.assertFalse(result)

    def test_normalize_indian_mobile_handles_common_formats(self):
        self.assertEqual(otp_service._normalize_indian_mobile("9876543210"), "919876543210")
        self.assertEqual(otp_service._normalize_indian_mobile("+919876543210"), "919876543210")
        self.assertEqual(otp_service._normalize_indian_mobile("919876543210"), "919876543210")


class CustomerAdminAccessTests(TestCase):
    def setUp(self):
        signup_via_client(
            self.client,
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
        signup_via_client(
            self.client,
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


class AdminDashboardAndReportsTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_superuser(
            "reportadmin", "reportadmin@example.com", "AdminPW12345"
        )
        self.client.login(username="reportadmin", password="AdminPW12345")

    def test_reports_page_accessible_to_staff(self):
        resp = self.client.get(reverse("admin:reports"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Total Orders")

    def test_reports_page_blocked_for_customers(self):
        self.client.logout()
        signup_via_client(
            self.client,
            {
                "full_name": "Regular Customer",
                "mobile_number": "+15556667777",
                "email": "regular.customer@example.com",
                "password": "SupErStrongPW123",
                "confirm_password": "SupErStrongPW123",
            },
        )
        resp = self.client.get(reverse("admin:reports"))
        self.assertNotEqual(resp.status_code, 200)

    def test_customer_admin_list_accessible_to_staff(self):
        resp = self.client.get(reverse("admin:accounts_customerprofile_changelist"))
        self.assertEqual(resp.status_code, 200)


class GlobalSearchTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_superuser(
            "searchadmin", "searchadmin@example.com", "AdminPW12345"
        )
        self.client.login(username="searchadmin", password="AdminPW12345")
        target_user = User.objects.create_user("gina", "gina@example.com", "GinaPW12345")
        CustomerProfile.objects.create(
            user=target_user, full_name="Gina Rodriguez", mobile_number="+15558889999"
        )

    def test_search_finds_matching_customer(self):
        resp = self.client.get(reverse("admin:global_search"), {"q": "Gina"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Gina Rodriguez")

    def test_search_blocked_for_customers(self):
        self.client.logout()
        signup_via_client(
            self.client,
            {
                "full_name": "Search Customer",
                "mobile_number": "+15550009999",
                "email": "search.customer@example.com",
                "password": "SupErStrongPW123",
                "confirm_password": "SupErStrongPW123",
            },
        )
        resp = self.client.get(reverse("admin:global_search"), {"q": "Gina"})
        self.assertNotEqual(resp.status_code, 200)


class LoginCaseInsensitivityTests(TestCase):
    def test_login_succeeds_with_different_case_email(self):
        signup_via_client(
            self.client,
            {
                "full_name": "Case Test",
                "mobile_number": "+15552223333",
                "email": "MixedCase@Example.com",
                "password": "SupErStrongPW123",
                "confirm_password": "SupErStrongPW123",
            },
        )
        self.client.get(reverse("logout"))

        # Signup stores the email lowercased; logging back in by typing
        # the original mixed-case version must still work.
        resp = self.client.post(
            reverse("login"),
            {"username": "MixedCase@Example.com", "password": "SupErStrongPW123"},
            follow=True,
        )
        self.assertTrue(resp.context["user"].is_authenticated)

    def test_login_still_rejects_wrong_password(self):
        signup_via_client(
            self.client,
            {
                "full_name": "Case Test Two",
                "mobile_number": "+15552223344",
                "email": "casetwo@example.com",
                "password": "SupErStrongPW123",
                "confirm_password": "SupErStrongPW123",
            },
        )
        self.client.get(reverse("logout"))
        resp = self.client.post(
            reverse("login"),
            {"username": "casetwo@example.com", "password": "WrongPassword123"},
        )
        self.assertContains(resp, "Invalid email or password")


class AccountPageShowsOrdersTests(TestCase):
    def test_account_page_links_to_my_orders_and_has_no_embedded_order_list(self):
        signup_via_client(
            self.client,
            {
                "full_name": "Order Viewer",
                "mobile_number": "+15556661111",
                "email": "order.viewer@example.com",
                "password": "SupErStrongPW123",
                "confirm_password": "SupErStrongPW123",
            },
        )
        resp = self.client.get(reverse("account"))
        # The profile page links out to My Orders rather than embedding
        # the order list itself, but keeps the editable profile form.
        self.assertContains(resp, reverse("my_orders"))
        self.assertContains(resp, "Save Changes")
        self.assertNotContains(resp, "order-tracker")

    def test_my_orders_page_lists_own_orders(self):
        from orders.models import Order, OrderItem

        signup_via_client(
            self.client,
            {
                "full_name": "Order Viewer",
                "mobile_number": "+15556661111",
                "email": "order.viewer@example.com",
                "password": "SupErStrongPW123",
                "confirm_password": "SupErStrongPW123",
            },
        )
        user = User.objects.get(email="order.viewer@example.com")
        order = Order.objects.create(user=user, status=Order.STATUS_PENDING, total_amount="99.00")
        OrderItem.objects.create(order=order, item_name="Cold Coffee", price="99.00", quantity=1)

        resp = self.client.get(reverse("my_orders"))
        self.assertContains(resp, f"Order #{order.id}")
        self.assertContains(resp, "Cold Coffee")

    def test_my_orders_page_never_shows_another_customers_orders(self):
        from orders.models import Order

        signup_via_client(
            self.client,
            {
                "full_name": "Viewer One",
                "mobile_number": "+15556661122",
                "email": "viewer.one@example.com",
                "password": "SupErStrongPW123",
                "confirm_password": "SupErStrongPW123",
            },
        )
        self.client.get(reverse("logout"))

        other_user = User.objects.create_user("otherorderowner", password="pw12345!")
        other_order = Order.objects.create(user=other_user, status=Order.STATUS_PENDING, total_amount="50.00")

        signup_via_client(
            self.client,
            {
                "full_name": "Viewer Two",
                "mobile_number": "+15556661133",
                "email": "viewer.two@example.com",
                "password": "SupErStrongPW123",
                "confirm_password": "SupErStrongPW123",
            },
        )
        resp = self.client.get(reverse("my_orders"))
        self.assertNotContains(resp, f"Order #{other_order.id}")


class MobileNavAccountLinkTests(TestCase):
    def test_mobile_nav_includes_account_link_for_authenticated_user(self):
        signup_via_client(
            self.client,
            {
                "full_name": "Mobile Nav Tester",
                "mobile_number": "+15557778899",
                "email": "mobile.nav@example.com",
                "password": "SupErStrongPW123",
                "confirm_password": "SupErStrongPW123",
            },
        )
        resp = self.client.get(reverse("home"))
        self.assertContains(resp, "nav-links-mobile-only")
        # The mobile-only block must contain a real My Account link, not
        # just the desktop nav-actions copy.
        body = resp.content.decode()
        mobile_block = body.split("nav-links-mobile-only")[1][:400]
        self.assertIn(reverse("account"), mobile_block)

    def test_mobile_nav_shows_login_link_for_anonymous_user(self):
        resp = self.client.get(reverse("home"))
        body = resp.content.decode()
        mobile_block = body.split("nav-links-mobile-only")[1][:400]
        self.assertIn(reverse("login"), mobile_block)


class ChefSpecialAddToCartTests(TestCase):
    def test_chef_special_item_has_add_to_cart_control(self):
        from menu.models import Category, MenuItem

        category = Category.objects.create(name="Mains")
        MenuItem.objects.create(
            category=category, name="Chicken Biryani", price="300.00",
            is_available=True, is_chef_special=True,
        )
        resp = self.client.get(reverse("home"))
        self.assertContains(resp, "food-cart-controls")
        self.assertContains(resp, "Chicken Biryani")
        # The old plain "Order" link must be gone from the chef special
        # card in favour of the real add-to-cart control.
        self.assertNotContains(resp, "home-order-link")


class DesignSystemAccessibilityTests(TestCase):
    def test_skip_link_and_nav_toggle_aria_present(self):
        resp = self.client.get(reverse("home"))
        body = resp.content.decode()
        self.assertIn('class="skip-link"', body)
        self.assertIn('aria-controls="primary-nav"', body)
        self.assertIn('aria-expanded="false"', body)
        self.assertIn('id="main-content"', body)

    def test_admin_theme_stylesheet_linked_on_every_admin_page(self):
        admin_user = User.objects.create_superuser(
            "themeadmin", "themeadmin@example.com", "AdminPW12345"
        )
        self.client.login(username="themeadmin", password="AdminPW12345")
        for url_name, args in [
            ("admin:orders_order_changelist", []),
            ("admin:menu_menuitem_changelist", []),
            ("admin:accounts_customerprofile_changelist", []),
        ]:
            resp = self.client.get(reverse(url_name, args=args))
            self.assertContains(resp, "butterfly_admin.css")
            self.assertContains(resp, "Butterfly Admin")


class AdminBrandingPolishTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_superuser(
            "brandadmin", "brandadmin@example.com", "AdminPW12345"
        )

    def test_login_page_has_no_emoji_uses_real_logo_and_no_theme_toggle(self):
        resp = self.client.get("/admin/login/")
        self.assertNotContains(resp, "\U0001F98B")  # butterfly emoji
        self.assertContains(resp, "butterfly.jpeg")
        self.assertNotContains(resp, 'class="theme-toggle"')

    def test_dashboard_has_no_emoji_uses_real_logo_and_no_theme_toggle(self):
        self.client.login(username="brandadmin", password="AdminPW12345")
        resp = self.client.get(reverse("admin:index"))
        self.assertNotContains(resp, "\U0001F98B")
        self.assertContains(resp, "butterfly.jpeg")
        self.assertNotContains(resp, 'class="theme-toggle"')

    def test_changelist_pages_have_no_theme_toggle(self):
        self.client.login(username="brandadmin", password="AdminPW12345")
        resp = self.client.get(reverse("admin:orders_order_changelist"))
        self.assertNotContains(resp, 'class="theme-toggle"')


class DashboardMobilePolishTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_superuser(
            "polishadmin", "polishadmin@example.com", "AdminPW12345"
        )
        self.client.login(username="polishadmin", password="AdminPW12345")

    def test_dashboard_shows_at_most_3_recent_reviews(self):
        from menu.models import CustomerReview

        for i in range(5):
            CustomerReview.objects.create(
                customer_name=f"Reviewer {i}", review_text="Great!", rating=5, is_active=True
            )
        resp = self.client.get(reverse("admin:index"))
        self.assertEqual(resp.content.decode().count('<div class="bck-review">'), 3)

    def test_dashboard_has_view_site_link_to_home(self):
        resp = self.client.get(reverse("admin:index"))
        self.assertContains(resp, "View Site")
        self.assertContains(resp, reverse("home"))

    def test_dashboard_orders_table_has_min_width_for_mobile_scroll(self):
        resp = self.client.get(reverse("admin:index"))
        self.assertContains(resp, "min-width: 640px")


class MobileNavAndOrderCardCSSTests(TestCase):
    def _read_style_css(self):
        from django.contrib.staticfiles import finders

        path = finders.find("css/style.css")
        with open(path, encoding="utf-8") as f:
            return f.read()

    def test_mobile_nav_actions_flush_against_toggle(self):
        # Regression test for the visible gap between the Cart button
        # and the hamburger on mobile. A previous fix relied on an auto
        # margin interacting with justify-content: space-between across
        # loose siblings, which turned out fragile -- the robust fix
        # wraps .nav-actions and .nav-toggle in one shared flex group
        # (.nav-right-group) so their spacing is never ambiguous.
        resp = self.client.get(reverse("home"))
        body = resp.content.decode()
        self.assertIn('class="nav-right-group"', body)
        # Both the cart/login actions and the hamburger button must sit
        # inside that same group in the DOM.
        group = body.split('class="nav-right-group"')[1][:800]
        self.assertIn("nav-actions", group)
        self.assertIn("nav-toggle", group)

        css = self._read_style_css()
        self.assertIn(".nav-right-group {", css)

    def test_order_card_head_wraps_on_narrow_screens(self):
        css = self._read_style_css()
        self.assertIn("flex-wrap: wrap", css.split(".order-card-head {")[-1][:100])


class AdminLogoutTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_superuser(
            "logoutadmin", "logoutadmin@example.com", "AdminPW12345"
        )

    def test_dashboard_logout_is_a_post_form_not_a_get_link(self):
        """
        Regression test for the 405 error: Django 5+'s LogoutView only
        accepts POST, so a plain <a href> to admin:logout (a GET
        request) fails. The sidebar must submit via a real form.
        """
        self.client.login(username="logoutadmin", password="AdminPW12345")
        resp = self.client.get(reverse("admin:index"))
        body = resp.content.decode()
        self.assertIn(f'action="{reverse("admin:logout")}"', body)
        self.assertNotIn(f'href="{reverse("admin:logout")}"', body)

    def test_logout_via_post_redirects_to_admin_login(self):
        client = Client(enforce_csrf_checks=True)
        client.login(username="logoutadmin", password="AdminPW12345")
        resp = client.get(reverse("admin:index"))
        import re

        match = re.search(
            r'name="csrfmiddlewaretoken" value="([^"]+)"[^<]*<input type="hidden" name="next" value="([^"]+)"',
            resp.content.decode(),
        )
        self.assertIsNotNone(match)
        token, next_url = match.groups()
        resp = client.post(reverse("admin:logout"), {"csrfmiddlewaretoken": token, "next": next_url})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], reverse("admin:login"))

    def test_logout_via_get_is_not_used_anywhere(self):
        """A plain GET to admin:logout should never be the only way to
        log out -- confirms the old broken link pattern is gone."""
        self.client.login(username="logoutadmin", password="AdminPW12345")
        resp = self.client.get(reverse("admin:logout"))
        self.assertEqual(resp.status_code, 405)


class NoBrokenTemplateCommentsTests(TestCase):
    def test_admin_pages_never_leak_raw_comment_text(self):
        """
        Regression test: Django's {# #} comment tag cannot span
        multiple lines -- if it does, Django renders it as literal
        text instead of stripping it. This previously leaked an
        internal implementation note onto every admin page's header.
        """
        admin_user = User.objects.create_superuser(
            "commentadmin", "commentadmin@example.com", "AdminPW12345"
        )
        self.client.login(username="commentadmin", password="AdminPW12345")
        for url_name in ["admin:index", "admin:orders_order_changelist"]:
            resp = self.client.get(reverse(url_name))
            body = resp.content.decode()
            self.assertNotIn("{#", body)
            self.assertNotIn("#}", body)
            self.assertNotIn("light-themed", body.lower())


class FilterSidebarStyleTests(TestCase):
    def test_filter_sidebar_has_modern_styling(self):
        from django.contrib.staticfiles import finders

        path = finders.find("admin/css/butterfly_admin.css")
        with open(path, encoding="utf-8") as f:
            css = f.read()
        self.assertIn("#changelist-filter-extra-actions", css)
        self.assertIn("#changelist-filter li.selected a", css)


class MobileOverflowFixTests(TestCase):
    def _read_style_css(self):
        from django.contrib.staticfiles import finders

        path = finders.find("css/style.css")
        with open(path, encoding="utf-8") as f:
            return f.read()

    def test_account_layout_grid_items_allow_shrinking(self):
        """
        Regression test: CSS Grid items default to min-width:auto (they
        refuse to shrink below their content's intrinsic width). The
        order tracker's several non-shrinking steps pushed the whole
        grid column -- and with it the page -- into horizontal overflow
        on mobile instead of scrolling just the tracker.
        """
        css = self._read_style_css()
        self.assertIn(".account-profile-col { position: sticky; top: 100px; min-width: 0; }", css)
        self.assertIn(".account-orders-col { min-width: 0; }", css)

    def test_admin_dashboard_panels_allow_shrinking(self):
        admin_user = User.objects.create_superuser(
            "overflowadmin", "overflowadmin@example.com", "AdminPW12345"
        )
        self.client.login(username="overflowadmin", password="AdminPW12345")
        resp = self.client.get(reverse("admin:index"))
        body = resp.content.decode()
        self.assertIn("min-width: 0", body)
        self.assertIn("overflow-x: hidden", body)
