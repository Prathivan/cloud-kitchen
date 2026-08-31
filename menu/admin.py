from django.contrib import admin
from .models import Category, CustomerReview, MenuItem, RunningOffer


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)


@admin.register(MenuItem)
class MenuItemAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "category",
        "food_type",
        "price",
        "has_offer",
        "offer_price",
        "is_available",
        "is_chef_special",
        "is_popular",
        "is_selling_unit_tracking",
        "per_day_selling_units",
        "total_selling_units",
        "available_tracking",
    )
    list_filter = (
        "category",
        "food_type",
        "is_chef_special",
        "is_popular",
        "has_offer",
        "is_available",
        "is_selling_unit_tracking",
        "available_tracking",
    )
    search_fields = ("name", "description")
    readonly_fields = ("total_selling_units", "selling_units_date")

    fieldsets = (
        (None, {
            "fields": ("category", "name", "description", "image", "food_type"),
        }),
        ("Pricing & offer", {
            "fields": ("price", "has_offer", "offer_price"),
        }),
        ("Homepage highlights", {
            "fields": ("is_chef_special", "is_popular"),
        }),
        ("Availability", {
            "fields": ("is_available", "available_tracking", "is_available_from", "is_available_till"),
        }),
        ("Daily selling-unit limit", {
            "fields": (
                "is_selling_unit_tracking",
                "per_day_selling_units",
                "total_selling_units",
                "selling_units_date",
            ),
        }),
    )


@admin.register(RunningOffer)
class RunningOfferAdmin(admin.ModelAdmin):
    list_display = ("title", "is_active", "display_order", "created_at")
    list_filter = ("is_active",)
    search_fields = ("title", "description")
    list_editable = ("display_order",)


@admin.register(CustomerReview)
class CustomerReviewAdmin(admin.ModelAdmin):
    list_display = ("customer_name", "rating", "is_active", "display_order", "created_at")
    list_filter = ("is_active", "rating")
    search_fields = ("customer_name", "review_text")
    list_editable = ("display_order",)
