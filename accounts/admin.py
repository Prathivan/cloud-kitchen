from django.contrib import admin
from django.db.models import Count, Q, Sum
from django.urls import reverse
from django.utils.html import format_html

from .models import CustomerProfile, OTPVerification


@admin.register(CustomerProfile)
class CustomerProfileAdmin(admin.ModelAdmin):
    list_display = (
        "full_name", "mobile_number", "user_email", "role",
        "order_count", "total_spent", "date_joined",
    )
    search_fields = ("full_name", "mobile_number", "user__email", "user__username")
    list_filter = ("role",)
    # Role is descriptive only (see CustomerProfile docstring); it is
    # deliberately left editable here for staff, but a customer never
    # reaches this page — /admin/ is staff-only, enforced server-side.
    readonly_fields = ("created_at", "order_count", "total_spent", "recent_orders")
    fields = ("user", "full_name", "mobile_number", "role", "created_at", "order_count", "total_spent", "recent_orders")

    def get_queryset(self, request):
        # Only completed (non-cancelled) orders count toward spend, so a
        # cancelled order never inflates a customer's totals.
        from orders.models import Order
        return (
            super().get_queryset(request)
            .select_related("user")
            .annotate(
                _order_count=Count("user__orders", distinct=True),
                _total_spent=Sum(
                    "user__orders__total_amount",
                    filter=~Q(user__orders__status=Order.STATUS_CANCELLED),
                ),
            )
        )

    @admin.display(description="Email")
    def user_email(self, obj):
        return obj.user.email

    @admin.display(description="Date Joined")
    def date_joined(self, obj):
        return obj.created_at

    @admin.display(description="Orders", ordering="_order_count")
    def order_count(self, obj):
        return getattr(obj, "_order_count", None)

    @admin.display(description="Total Spent", ordering="_total_spent")
    def total_spent(self, obj):
        from decimal import ROUND_HALF_UP, Decimal

        from django.contrib.humanize.templatetags.humanize import intcomma

        amount = getattr(obj, "_total_spent", None)
        if not amount:
            return "₹0.00"
        # Same SQLite Sum()-on-DecimalField precision issue fixed
        # elsewhere for the dashboard (see config/admin_dashboard.py's
        # _money()) -- quantize before display so this never shows a
        # long float-noise tail.
        clean = Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return f"₹{intcomma(clean)}"

    @admin.display(description="Recent Orders")
    def recent_orders(self, obj):
        from orders.models import Order
        orders = Order.objects.filter(user=obj.user).order_by("-created_at")[:5]
        if not orders:
            return "No orders yet."
        rows = "".join(
            format_html(
                '<li><a href="{}">Order #{}</a> — {} — ₹{}</li>',
                reverse("admin:orders_order_change", args=[o.id]),
                o.id, o.get_status_display(), o.total_amount,
            )
            for o in orders
        )
        return format_html("<ul style='margin:0;padding-left:16px;'>{}</ul>", rows)


@admin.register(OTPVerification)
class OTPVerificationAdmin(admin.ModelAdmin):
    """
    Read-only listing for debugging the signup OTP flow (e.g. checking
    why a code didn't verify). The code itself is stored hashed
    (see OTPVerification.code_hash) so it's never visible here, even
    to staff — during local testing, the actual code appears in the
    runserver console/log instead (see accounts.otp_service).
    """

    list_display = ("mobile_number", "channel", "is_verified", "attempts", "created_at", "expires_at")
    list_filter = ("channel", "is_verified")
    search_fields = ("mobile_number",)
    readonly_fields = (
        "mobile_number", "channel", "created_at", "expires_at",
        "attempts", "is_verified", "verified_at",
    )
    fields = readonly_fields

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
