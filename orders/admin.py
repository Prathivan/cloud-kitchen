from django.contrib import admin, messages
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from .models import AdminNotification, Order, OrderItem


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ("menu_item", "item_name", "price", "quantity")

    def has_add_permission(self, request, obj=None):
        return False


STATUS_BADGE_COLORS = {
    Order.STATUS_PENDING: "#f4a261",
    Order.STATUS_CONFIRMED: "#2b9ed8",
    Order.STATUS_PREPARING: "#1878ad",
    Order.STATUS_READY: "#2e9e5b",
    Order.STATUS_OUT_FOR_DELIVERY: "#8a5cf6",
    Order.STATUS_DELIVERED: "#2e9e5b",
    Order.STATUS_CANCELLED: "#e2574c",
}


def _make_transition_action(target_status, from_statuses, short_description):
    """
    Builds an admin action that advances every selected order currently
    in one of `from_statuses` to `target_status`. Orders not in an
    eligible starting status are left untouched (and counted separately)
    so an accidental multi-select never silently corrupts unrelated
    orders sitting in a different stage of the workflow.
    """

    def action(modeladmin, request, queryset):
        eligible = queryset.filter(status__in=from_statuses)
        skipped = queryset.exclude(status__in=from_statuses).count()

        updated = 0
        for order in eligible:
            order.advance_to(target_status)
            order.save()
            updated += 1

        if updated:
            target_label = dict(Order.STATUS_CHOICES).get(target_status, target_status)
            messages.success(request, f"{updated} order(s) moved to '{target_label}'.")
        if skipped:
            messages.warning(
                request,
                f"{skipped} order(s) were skipped because they weren't in an eligible status for this action.",
            )

    action.short_description = short_description
    action.__name__ = f"transition_to_{target_status}"
    return action


accept_orders = _make_transition_action(
    Order.STATUS_CONFIRMED, [Order.STATUS_PENDING], "Accept selected orders (Pending → Confirmed)"
)
start_preparing = _make_transition_action(
    Order.STATUS_PREPARING, [Order.STATUS_CONFIRMED], "Start preparing (Confirmed → Preparing)"
)
mark_ready = _make_transition_action(
    Order.STATUS_READY, [Order.STATUS_PREPARING], "Mark ready (Preparing → Ready)"
)
dispatch_orders = _make_transition_action(
    Order.STATUS_OUT_FOR_DELIVERY, [Order.STATUS_READY], "Dispatch (Ready → Out for Delivery)"
)
complete_delivery = _make_transition_action(
    Order.STATUS_DELIVERED, [Order.STATUS_OUT_FOR_DELIVERY], "Complete delivery (Out for Delivery → Delivered)"
)
cancel_orders = _make_transition_action(
    Order.STATUS_CANCELLED,
    [Order.STATUS_PENDING, Order.STATUS_CONFIRMED, Order.STATUS_PREPARING, Order.STATUS_READY, Order.STATUS_OUT_FOR_DELIVERY],
    "Cancel selected orders",
)


# Same forward path used by the dashboard's per-row "advance" button
# (config/admin_dashboard.py) and the changelist's quick_action column
# below -- both post to the shared admin:advance_order view.
NEXT_STATUS = {
    Order.STATUS_PENDING: Order.STATUS_CONFIRMED,
    Order.STATUS_CONFIRMED: Order.STATUS_PREPARING,
    Order.STATUS_PREPARING: Order.STATUS_READY,
    Order.STATUS_READY: Order.STATUS_OUT_FOR_DELIVERY,
    Order.STATUS_OUT_FOR_DELIVERY: Order.STATUS_DELIVERED,
}
ADVANCE_LABEL = {
    Order.STATUS_PENDING: "Accept",
    Order.STATUS_CONFIRMED: "Start Preparing",
    Order.STATUS_PREPARING: "Mark Ready",
    Order.STATUS_READY: "Dispatch",
    Order.STATUS_OUT_FOR_DELIVERY: "Complete",
}


class OrderTypeFilter(admin.SimpleListFilter):
    """All / Normal Orders / Pre-Orders filter for the changelist sidebar."""

    title = "order type"
    parameter_name = "order_type"

    def lookups(self, request, model_admin):
        return [("normal", "Normal Orders"), ("preorder", "Pre-Orders")]

    def queryset(self, request, queryset):
        if self.value() == "normal":
            return queryset.filter(is_preorder=False)
        if self.value() == "preorder":
            return queryset.filter(is_preorder=True)
        return queryset


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "order_type_badge",
        "status_badge",
        "item_count",
        "formatted_total",
        "created_at",
        "preorder_datetime_display",
        "quick_action",
    )
    list_filter = (OrderTypeFilter, "status", "created_at")
    search_fields = ("=id", "user__email", "user__username", "user__customer_profile__mobile_number")
    date_hierarchy = "created_at"
    readonly_fields = (
        "user", "total_amount", "created_at",
        "confirmed_at", "preparing_at", "ready_at", "out_for_delivery_at",
        "delivered_at", "cancelled_at",
        "is_preorder", "preorder_datetime", "preorder_reminder_sent",
    )
    inlines = [OrderItemInline]
    actions = [accept_orders, start_preparing, mark_ready, dispatch_orders, complete_delivery, cancel_orders]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("user").prefetch_related("items")

    @admin.display(description="Items")
    def item_count(self, obj):
        return sum(item.quantity for item in obj.items.all())

    @admin.display(description="Total", ordering="total_amount")
    def formatted_total(self, obj):
        from django.contrib.humanize.templatetags.humanize import intcomma

        return f"₹{intcomma(obj.total_amount)}"

    @admin.display(description="Type", ordering="is_preorder")
    def order_type_badge(self, obj):
        from django.utils.safestring import mark_safe

        if obj.is_preorder:
            return mark_safe(
                '<span style="display:inline-block;padding:3px 10px;border-radius:999px;'
                'font-size:11px;font-weight:700;color:#fff;background:#8a5cf6;">Pre-Order</span>'
            )
        return mark_safe(
            '<span style="display:inline-block;padding:3px 10px;border-radius:999px;'
            'font-size:11px;font-weight:700;color:#52616b;background:#eef2f4;">Normal Order</span>'
        )

    @admin.display(description="Pre-Order Date & Time", ordering="preorder_datetime")
    def preorder_datetime_display(self, obj):
        # Hidden/marked N/A for normal orders -- never show an empty
        # date/time field for them.
        if not obj.is_preorder or not obj.preorder_datetime:
            return "—"
        return timezone.localtime(obj.preorder_datetime).strftime("%d %b %Y, %I:%M %p")

    @admin.display(description="Status")
    def status_badge(self, obj):
        color = STATUS_BADGE_COLORS.get(obj.status, "#52616b")
        return format_html(
            '<span style="display:inline-block;padding:3px 10px;border-radius:999px;'
            'font-size:11px;font-weight:700;color:#fff;background:{};">{}</span>',
            color, obj.get_status_display(),
        )

    @admin.display(description="Action")
    def quick_action(self, obj):
        """
        A one-click button that moves this single order to the next
        status in the kitchen workflow, without needing to select it
        and run a bulk action.

        IMPORTANT: Django's changelist page already wraps the entire
        results table in one <form id="changelist-form">. Nesting a
        second <form> inside a table cell here (as an earlier version
        of this method did) produces invalid, unreliable HTML -- browsers
        don't support nested forms, so the inner submit button ends up
        firing the *outer* changelist form instead of this one, and the
        button silently does nothing useful. Using formaction/formmethod
        on a plain <button> avoids nesting: the click still submits the
        one real (outer) form -- reusing its already-valid CSRF token --
        but targets this order's advance-status URL instead of the
        default changelist action.
        """
        next_status = NEXT_STATUS.get(obj.status)
        if not next_status:
            return "—"
        label = ADVANCE_LABEL[obj.status]
        # The `next` param travels as a query string on the formaction
        # URL (not a hidden field, since there's no nested form to hold
        # one) so the view can redirect back here afterwards.
        changelist_url = reverse("admin:orders_order_changelist")
        url = reverse("admin:advance_order", args=[obj.id]) + f"?next={changelist_url}"
        return format_html(
            '<button type="submit" formaction="{}" formmethod="post" '
            'style="border:0;background:#2b9ed8;color:#fff;font-size:11px;font-weight:700;'
            'padding:5px 10px;border-radius:8px;cursor:pointer;">{}</button>',
            url, label,
        )


@admin.register(AdminNotification)
class AdminNotificationAdmin(admin.ModelAdmin):
    list_display = ("message", "notification_type", "order_link", "is_read", "created_at")
    list_filter = ("notification_type", "is_read")
    readonly_fields = ("notification_type", "message", "order", "created_at")
    actions = ["mark_as_read"]

    @admin.display(description="Order")
    def order_link(self, obj):
        if not obj.order_id:
            return "—"
        url = reverse("admin:orders_order_change", args=[obj.order_id])
        return format_html('<a href="{}">#ORD{:05d}</a>', url, obj.order_id)

    @admin.action(description="Mark selected notifications as read")
    def mark_as_read(self, request, queryset):
        updated = queryset.update(is_read=True)
        messages.success(request, f"{updated} notification(s) marked as read.")
