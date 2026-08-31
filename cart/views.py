from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache

from menu.models import MenuItem
from .models import CartItem


def _is_ajax(request):
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def _cart_count(user):
    """Total quantity across all of this user's cart rows (not row count)."""
    return CartItem.objects.filter(user=user).aggregate(
        total=Sum("quantity")
    )["total"] or 0


def _cart_item_payload(cart_item, user):
    return {
        "cart_item_id": cart_item.id,
        "menu_item_id": cart_item.menu_item_id,
        "quantity": cart_item.quantity,
        "cart_count": _cart_count(user),
    }


@login_required
def add_to_cart(request, item_id):
    if request.method != "POST":
        return redirect("menu")

    with transaction.atomic():
        menu_item = get_object_or_404(
            MenuItem.objects.select_for_update(), id=item_id
        )

        if not menu_item.is_currently_orderable():
            error = "This item is currently unavailable."
            if _is_ajax(request):
                return JsonResponse({"ok": False, "error": error}, status=400)
            messages.error(request, error)
            return redirect("menu")

        cart_item, created = CartItem.objects.select_for_update().get_or_create(
            menu_item=menu_item,
            user=request.user,
            defaults={"quantity": 1},
        )

        if not created:
            new_quantity = cart_item.quantity + 1
            remaining = menu_item.remaining_selling_units()
            if remaining is not None and new_quantity > remaining:
                error = "Only a limited quantity of this item is left today."
                if _is_ajax(request):
                    return JsonResponse({"ok": False, "error": error}, status=400)
                messages.error(request, error)
                return redirect("menu")
            cart_item.quantity = new_quantity
            cart_item.save(update_fields=["quantity"])

    if _is_ajax(request):
        return JsonResponse({"ok": True, "in_cart": True, **_cart_item_payload(cart_item, request.user)})

    return redirect("menu")


@login_required
@never_cache
def cart(request):
    cart_items = CartItem.objects.select_related("menu_item").filter(user=request.user)

    subtotal = Decimal("0.00")

    for cart_item in cart_items:
        # Always the effective (offer-aware) price -- never the original
        # price when an offer is active.
        item_price = cart_item.menu_item.effective_price
        item_total = item_price * cart_item.quantity
        cart_item.display_price = item_price
        cart_item.item_total = item_total
        subtotal += item_total

    delivery_fee = Decimal("40.00") if cart_items else Decimal("0.00")
    tax = Decimal("0.00")

    total = subtotal + delivery_fee + tax

    context = {
        "cart_items": cart_items,
        "subtotal": subtotal,
        "delivery_fee": delivery_fee,
        "tax": tax,
        "total": total,
    }

    return render(request, "cart.html", context)


@login_required
def remove_from_cart(request, item_id):
    if request.method == "POST":
        cart_item = get_object_or_404(CartItem, id=item_id, user=request.user)
        cart_item.delete()

        if _is_ajax(request):
            return JsonResponse({
                "ok": True,
                "in_cart": False,
                "quantity": 0,
                "cart_count": _cart_count(request.user),
            })

    return redirect("cart")


@login_required
def update_cart_quantity(request, item_id):
    if request.method != "POST":
        return redirect("cart")

    with transaction.atomic():
        cart_item = get_object_or_404(
            CartItem.objects.select_for_update().select_related("menu_item"),
            id=item_id,
            user=request.user,
        )

        try:
            quantity = int(request.POST.get("quantity", 1))
        except (TypeError, ValueError):
            quantity = cart_item.quantity

        if quantity <= 0:
            cart_item.delete()
            if _is_ajax(request):
                return JsonResponse({
                    "ok": True,
                    "in_cart": False,
                    "quantity": 0,
                    "cart_count": _cart_count(request.user),
                })
            return redirect("menu") if request.POST.get("origin") == "menu" else redirect("cart")

        menu_item = MenuItem.objects.select_for_update().get(pk=cart_item.menu_item_id)

        # Cap increases at the remaining daily selling units. Backend
        # validation only -- the final authoritative check happens again,
        # under lock, at order confirmation.
        if quantity > cart_item.quantity:
            remaining = menu_item.remaining_selling_units()
            if remaining is not None and quantity > remaining:
                error = "Only a limited quantity of this item is left today."
                if _is_ajax(request):
                    return JsonResponse({"ok": False, "error": error}, status=400)
                messages.error(request, error)
                quantity = cart_item.quantity

        cart_item.quantity = quantity
        cart_item.save(update_fields=["quantity"])

    if _is_ajax(request):
        return JsonResponse({"ok": True, "in_cart": True, **_cart_item_payload(cart_item, request.user)})

    return redirect("menu") if request.POST.get("origin") == "menu" else redirect("cart")
