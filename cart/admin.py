from django.contrib import admin
from .models import CartItem


@admin.register(CartItem)
class CartItemAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "menu_item", "quantity", "added_at")
    list_filter = ("added_at",)
    search_fields = ("user__email", "user__username", "menu_item__name")
    readonly_fields = ("added_at",)
