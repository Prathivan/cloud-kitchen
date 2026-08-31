from django.contrib import admin

from .models import CustomerProfile


@admin.register(CustomerProfile)
class CustomerProfileAdmin(admin.ModelAdmin):
    list_display = ("full_name", "mobile_number", "user", "role", "created_at")
    search_fields = ("full_name", "mobile_number", "user__email", "user__username")
    list_filter = ("role",)
    # Role is descriptive only (see CustomerProfile docstring); it is
    # deliberately left editable here for staff, but a customer never
    # reaches this page — /admin/ is staff-only, enforced server-side.
    readonly_fields = ("created_at",)
