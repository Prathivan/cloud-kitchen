from django.contrib import admin, messages
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
    list_display = ("title", "schedule_state", "is_active", "start_date", "end_date", "display_order", "created_at")
    list_filter = ("is_active",)
    search_fields = ("title", "description")
    list_editable = ("display_order",)
    fields = ("title", "description", "image", "button_text", "button_link", "is_active", "start_date", "end_date", "display_order")

    @admin.display(description="State")
    def schedule_state(self, obj):
        return obj.schedule_state


def approve_reviews(modeladmin, request, queryset):
    updated = queryset.update(is_active=True)
    messages.success(request, f"{updated} review(s) approved and are now visible on the website.")
approve_reviews.short_description = "Approve selected reviews (show on website)"


def hide_reviews(modeladmin, request, queryset):
    updated = queryset.update(is_active=False)
    messages.success(request, f"{updated} review(s) hidden from the website.")
hide_reviews.short_description = "Hide selected reviews (remove from website)"


@admin.register(CustomerReview)
class CustomerReviewAdmin(admin.ModelAdmin):
    list_display = ("customer_name", "rating", "review_preview", "status_label", "display_order", "created_at")
    list_filter = ("is_active", "rating")
    search_fields = ("customer_name", "review_text")
    list_editable = ("display_order",)
    actions = [approve_reviews, hide_reviews]

    @admin.display(description="Review")
    def review_preview(self, obj):
        text = obj.review_text or ""
        return text if len(text) <= 60 else text[:57] + "…"

    @admin.display(description="Status")
    def status_label(self, obj):
        return "Approved" if obj.is_active else "Hidden"
