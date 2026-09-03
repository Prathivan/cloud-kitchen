"""
Custom "Kitchen Management Dashboard" admin homepage for Django Admin.

This patches the existing (default) admin.site rather than replacing
it: branding, a redesigned dashboard homepage, a reports page, a
per-order quick status-change action, a live stats JSON endpoint, and
a small cross-model search are all added as extra views registered on
admin.site's own URLconf (via admin_view(), so every one of them is
automatically staff-only, same as every other admin page). Every
model stays registered exactly as it already is in each app's
admin.py -- nothing here touches that, and the normal Django Admin
changelist/changeform pages for every model are unaffected.
"""
import types

from django.contrib import admin, messages
from django.contrib.admin.sites import AdminSite
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone

STATUS_COLORS = {
    "pending": "#f4a261",
    "confirmed": "#2b9ed8",
    "preparing": "#1878ad",
    "ready": "#2e9e5b",
    "out_for_delivery": "#8a5cf6",
    "delivered": "#2e9e5b",
    "cancelled": "#e2574c",
}

# The forward order-status path each "advance" button steps through.
NEXT_STATUS = {
    "pending": "confirmed",
    "confirmed": "preparing",
    "preparing": "ready",
    "ready": "out_for_delivery",
    "out_for_delivery": "delivered",
}
ADVANCE_LABEL = {
    "pending": "Accept",
    "confirmed": "Start Preparing",
    "preparing": "Mark Ready",
    "ready": "Dispatch",
    "out_for_delivery": "Complete",
}


def _changelist_url(app_label, model_name, **filters):
    url = reverse(f"admin:{app_label}_{model_name}_changelist")
    if filters:
        from urllib.parse import urlencode
        url += "?" + urlencode(filters)
    return url


def _today_filters():
    today = timezone.localdate()
    return {"created_at__year": today.year, "created_at__month": today.month, "created_at__day": today.day}


def _stat_cards_context():
    """The 6 clickable stat cards + the data needed to keep them live."""
    from orders.models import Order

    today = timezone.localdate()
    today_orders = Order.objects.filter(created_at__date=today)
    today_revenue = (
        today_orders.exclude(status=Order.STATUS_CANCELLED)
        .aggregate(total=Sum("total_amount"))["total"] or 0
    )
    from accounts.models import CustomerProfile

    today_filters = _today_filters()
    cards = [
        {
            "key": "todays_orders", "label": "Today's Orders", "value": today_orders.count(),
            "icon": "🛍️", "tone": "blue",
            "url": _changelist_url("orders", "order", **today_filters),
        },
        {
            "key": "pending_orders", "label": "Pending Orders",
            "value": Order.objects.filter(status=Order.STATUS_PENDING).count(),
            "icon": "⏱️", "tone": "amber",
            "url": _changelist_url("orders", "order", status__exact=Order.STATUS_PENDING),
        },
        {
            "key": "preparing_orders", "label": "Preparing",
            "value": Order.objects.filter(status=Order.STATUS_PREPARING).count(),
            "icon": "👩‍🍳", "tone": "purple",
            "url": _changelist_url("orders", "order", status__exact=Order.STATUS_PREPARING),
        },
        {
            "key": "delivered_orders", "label": "Delivered Today",
            "value": today_orders.filter(status=Order.STATUS_DELIVERED).count(),
            "icon": "🛵", "tone": "green",
            "url": _changelist_url("orders", "order", status__exact=Order.STATUS_DELIVERED, **today_filters),
        },
        {
            "key": "todays_revenue", "label": "Today's Revenue", "value": today_revenue,
            "icon": "₹", "tone": "teal", "is_currency": True,
            "url": _changelist_url("orders", "order", **today_filters),
        },
        {
            "key": "total_customers", "label": "Customers",
            "value": CustomerProfile.objects.count(),
            "icon": "👥", "tone": "pink",
            "url": _changelist_url("accounts", "customerprofile"),
        },
    ]
    return cards


def _status_breakdown_data():
    from django.db.models import Count
    from orders.models import Order

    raw = dict(Order.objects.values_list("status").annotate(n=Count("id")).values_list("status", "n"))
    total = sum(raw.values()) or 1
    rows = []
    gradient_parts = []
    cursor = 0
    for status_value, label in Order.STATUS_CHOICES:
        count = raw.get(status_value, 0)
        percent = round(count * 100 / total, 1) if total else 0
        color = STATUS_COLORS.get(status_value, "#ccc")
        rows.append({"status": status_value, "label": label, "count": count, "percent": percent, "color": color})
        if count:
            start, end = cursor, cursor + percent
            gradient_parts.append(f"{color} {start}% {end}%")
            cursor = end
    if not gradient_parts:
        gradient_parts = ["#e5edf2 0% 100%"]
    return rows, "conic-gradient(" + ", ".join(gradient_parts) + ")"


def _todays_orders_queryset(limit=10):
    from orders.models import Order

    today = timezone.localdate()
    return (
        Order.objects.filter(created_at__date=today)
        .select_related("user")
        .prefetch_related("items")
        .order_by("-created_at")[:limit]
    )


def _order_rows_context():
    orders = list(_todays_orders_queryset())
    for order in orders:
        order.item_total = sum(i.quantity for i in order.items.all())
        order.next_status = NEXT_STATUS.get(order.status)
        order.next_label = ADVANCE_LABEL.get(order.status)
    return orders


def _best_sellers(limit=5):
    from orders.models import Order, OrderItem

    return list(
        OrderItem.objects.exclude(order__status=Order.STATUS_CANCELLED)
        .values("item_name")
        .annotate(units_sold=Sum("quantity"), revenue=Sum("price"))
        .order_by("-units_sold")[:limit]
    )


def _recent_reviews(limit=5):
    from menu.models import CustomerReview

    reviews = list(CustomerReview.objects.filter(is_active=True).order_by("-created_at")[:limit])
    for review in reviews:
        review.star_display = "★" * review.rating + "☆" * (5 - review.rating)
    return reviews


def _dashboard_context(request):
    status_rows, donut_gradient = _status_breakdown_data()
    return {
        "stat_cards": _stat_cards_context(),
        "status_rows": status_rows,
        "donut_gradient": donut_gradient,
        "todays_orders": _order_rows_context(),
        "best_sellers": _best_sellers(),
        "recent_reviews": _recent_reviews(),
        "pending_count": next((r["count"] for r in status_rows if r["status"] == "pending"), 0),
    }


def _dashboard_view(request):
    context = dict(admin.site.each_context(request), title="Kitchen Management Dashboard")
    try:
        context.update(_dashboard_context(request))
    except Exception:
        # Never let a stats query break the admin homepage -- e.g. on a
        # fresh DB before migrations for a new field have been applied.
        pass
    return TemplateResponse(request, "admin/dashboard.html", context)


def _patched_index(self, request, extra_context=None):
    # /admin/ itself now renders the custom dashboard instead of
    # Django's default app-list index page.
    return _dashboard_view(request)


def _dashboard_stats_json_view(request):
    from django.http import JsonResponse

    cards = _stat_cards_context()
    status_rows, donut_gradient = _status_breakdown_data()
    orders = _order_rows_context()
    orders_html = TemplateResponse(
        request, "admin/_dashboard_orders_rows.html", {"todays_orders": orders},
    ).render().content.decode()

    return JsonResponse({
        "cards": {c["key"]: c["value"] for c in cards},
        "status_rows": status_rows,
        "donut_gradient": donut_gradient,
        "pending_count": next((r["count"] for r in status_rows if r["status"] == "pending"), 0),
        "orders_html": orders_html,
    })


def _advance_order_view(request, order_id):
    from orders.models import Order

    order = get_object_or_404(Order, pk=order_id)
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "cancel":
            if order.status not in (Order.STATUS_DELIVERED, Order.STATUS_CANCELLED):
                order.advance_to(Order.STATUS_CANCELLED)
                order.save()
                messages.success(request, f"Order #{order.id} cancelled.")
        else:
            next_status = NEXT_STATUS.get(order.status)
            if next_status:
                order.advance_to(next_status)
                order.save()
                messages.success(request, f"Order #{order.id} moved to '{order.get_status_display()}'.")
            else:
                messages.warning(request, f"Order #{order.id} has no further status to advance to.")
    next_url = request.POST.get("next") or reverse("admin:index")
    return redirect(next_url)


def _global_search_view(request):
    from accounts.models import CustomerProfile
    from menu.models import MenuItem
    from orders.models import Order

    query = request.GET.get("q", "").strip()
    results = {"orders": [], "customers": [], "menu_items": []}
    if query:
        order_filter = Q(user__email__icontains=query) | Q(user__customer_profile__full_name__icontains=query) \
            | Q(user__customer_profile__mobile_number__icontains=query)
        if query.isdigit():
            order_filter |= Q(id=int(query))
        results["orders"] = list(Order.objects.filter(order_filter).select_related("user")[:10])
        results["customers"] = list(
            CustomerProfile.objects.filter(
                Q(full_name__icontains=query) | Q(mobile_number__icontains=query) | Q(user__email__icontains=query)
            ).select_related("user")[:10]
        )
        results["menu_items"] = list(MenuItem.objects.filter(name__icontains=query)[:10])

    context = dict(admin.site.each_context(request), title="Search Results", query=query, results=results)
    return TemplateResponse(request, "admin/search_results.html", context)


def _reports_context(request):
    from django.db.models import Avg
    from orders.models import Order, OrderItem

    today = timezone.localdate()
    range_key = request.GET.get("range", "7d")
    custom_start = request.GET.get("start") or None
    custom_end = request.GET.get("end") or None

    if range_key == "today":
        start_date, end_date = today, today
    elif range_key == "yesterday":
        start_date = end_date = today - timezone.timedelta(days=1)
    elif range_key == "30d":
        start_date, end_date = today - timezone.timedelta(days=29), today
    elif range_key == "custom" and custom_start and custom_end:
        start_date, end_date = custom_start, custom_end
    else:
        range_key = "7d"
        start_date, end_date = today - timezone.timedelta(days=6), today

    orders_in_range = Order.objects.filter(
        created_at__date__gte=start_date, created_at__date__lte=end_date
    )
    completed = orders_in_range.exclude(status=Order.STATUS_CANCELLED)

    totals = completed.aggregate(total_sales=Sum("total_amount"), avg_order=Avg("total_amount"))

    best_sellers = (
        OrderItem.objects.filter(
            order__created_at__date__gte=start_date,
            order__created_at__date__lte=end_date,
        )
        .exclude(order__status=Order.STATUS_CANCELLED)
        .values("item_name")
        .annotate(units_sold=Sum("quantity"), revenue=Sum("price"))
        .order_by("-units_sold")[:10]
    )

    popular_categories = (
        OrderItem.objects.filter(
            order__created_at__date__gte=start_date,
            order__created_at__date__lte=end_date,
            menu_item__isnull=False,
        )
        .exclude(order__status=Order.STATUS_CANCELLED)
        .values("menu_item__category__name")
        .annotate(units_sold=Sum("quantity"))
        .order_by("-units_sold")[:8]
    )

    return {
        "range_key": range_key,
        "start_date": start_date,
        "end_date": end_date,
        "total_orders": orders_in_range.count(),
        "cancelled_orders": orders_in_range.filter(status=Order.STATUS_CANCELLED).count(),
        "total_sales": totals["total_sales"] or 0,
        "average_order_value": totals["avg_order"] or 0,
        "best_sellers": list(best_sellers),
        "popular_categories": list(popular_categories),
    }


def _reports_view(request):
    context = dict(admin.site.each_context(request), title="Reports")
    context.update(_reports_context(request))
    return TemplateResponse(request, "admin/reports.html", context)


def _get_urls_with_extras(original_get_urls):
    def get_urls(self):
        extra = [
            path("reports/", self.admin_view(_reports_view), name="reports"),
            path("dashboard-stats.json/", self.admin_view(_dashboard_stats_json_view), name="dashboard_stats"),
            path("orders/<int:order_id>/advance/", self.admin_view(_advance_order_view), name="advance_order"),
            path("search/", self.admin_view(_global_search_view), name="global_search"),
        ]
        return extra + original_get_urls()

    return get_urls


def install():
    admin.site.site_header = "Butterfly Admin"
    admin.site.site_title = "Butterfly Admin"
    admin.site.index_title = "Kitchen Management Dashboard"
    admin.site.index = types.MethodType(_patched_index, admin.site)
    admin.site.get_urls = types.MethodType(
        _get_urls_with_extras(admin.site.get_urls), admin.site
    )
