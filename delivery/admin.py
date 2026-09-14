from django.contrib import admin
from django.utils.html import format_html

from .models import DeliveryAddress


@admin.register(DeliveryAddress)
class DeliveryAddressAdmin(admin.ModelAdmin):
    """
    Read-mostly in the admin -- addresses are meant to be managed by
    the customer themselves (see delivery.views). This registration
    exists so support staff can look up what a customer has saved when
    helping with a delivery issue, and so it's visible at all (a model
    with no ModelAdmin doesn't show up in /admin/ menus).
    """

    list_display = ("id", "user", "address_label", "short_display", "city", "is_default", "map_link", "updated_at")
    list_filter = ("address_label", "is_default", "city")
    search_fields = ("user__email", "user__username", "full_name", "phone", "city", "postal_code")
    readonly_fields = ("created_at", "updated_at")

    @admin.display(description="Location")
    def map_link(self, obj):
        if obj.latitude is None or obj.longitude is None:
            return "—"
        url = f"https://www.google.com/maps/search/?api=1&query={obj.latitude},{obj.longitude}"
        return format_html('<a href="{}" target="_blank" rel="noopener">View on Google Maps</a>', url)
