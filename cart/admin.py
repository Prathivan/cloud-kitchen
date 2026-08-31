from django.contrib import admin
from .models import CartItem


@admin.register(CartItem)
class CartItemAdmin(admin.ModelAdmin):
    list_display = ("id", "menu_item", "quantity")