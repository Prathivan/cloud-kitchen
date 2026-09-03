from django.contrib import admin, messages
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from .models import Order, OrderItem


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


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "status_badge",
        "item_count",
        "total_amount",
        "created_at",
        "quick_action",
    )
    list_filter = ("status", "created_at")
    search_fields = ("=id", "user__email", "user__username", "user__customer_profile__mobile_number")
    date_hierarchy = "created_at"
    readonly_fields = (
        "user", "total_amount", "created_at",
        "confirmed_at", "preparing_at", "ready_at", "out_for_delivery_at",
        "delivered_at", "cancelled_at",
    )
    inlines = [OrderItemInline]
    actions = [accept_orders, start_preparing, mark_ready, dispatch_orders, complete_delivery, cancel_orders]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("user").prefetch_related("items")

    def changelist_view(self, request, extra_context=None):
        # Stashed so quick_action() below can generate a real CSRF token
        # for its inline per-row form (list_display methods don't
        # otherwise receive the request).
        self._request = request
        return super().changelist_view(request, extra_context)

    @admin.display(description="Items")
    def item_count(self, obj):
        return sum(item.quantity for item in obj.items.all())

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
        and run a bulk action. Posts to the same admin:advance_order
        view the custom dashboard uses, then returns to this changelist.
        """
        next_status = NEXT_STATUS.get(obj.status)
        if not next_status:
            return "—"
        label = ADVANCE_LABEL[obj.status]
        url = reverse("admin:advance_order", args=[obj.id])
        changelist_url = reverse("admin:orders_order_changelist")
        from django.middleware.csrf import get_token
        token = get_token(getattr(self, "_request", None)) if getattr(self, "_request", None) else ""
        return format_html(
            '<form method="post" action="{}" style="display:inline;">'
            '<input type="hidden" name="csrfmiddlewaretoken" value="{}">'
            '<input type="hidden" name="next" value="{}">'
            '<button type="submit" style="border:0;background:#2b9ed8;color:#fff;'
            'font-size:11px;font-weight:700;padding:5px 10px;border-radius:8px;cursor:pointer;">{}</button>'
            '</form>',
            url, token, changelist_url, label,
        )
