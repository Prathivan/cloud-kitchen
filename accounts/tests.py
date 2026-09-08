from django.contrib.auth import get_user_model
from django.test import Client, TestCase
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
        self.client.post(
            reverse("signup"),
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
        self.client.post(
            reverse("signup"),
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
        self.client.post(
            reverse("signup"),
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
        self.client.post(
            reverse("signup"),
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
        self.client.post(
            reverse("signup"),
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

        self.client.post(
            reverse("signup"),
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

        self.client.post(
            reverse("signup"),
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

        self.client.post(
            reverse("signup"),
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
        self.client.post(
            reverse("signup"),
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
