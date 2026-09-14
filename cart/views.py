from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache

from menu.models import MenuItem
from .models import CartItem, ORDER_TYPE_NORMAL, ORDER_TYPE_PREORDER, cart_order_type


def _is_ajax(request):
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def _cart_count(user):
    """Total quantity across all of this user's cart rows (not row count)."""
    return CartItem.objects.filter(user=user).aggregate(
        total=Sum("quantity")
    )["total"] or 0


def _mixing_conflict_message(existing_type):
    """
    The customer already has `existing_type` items in their cart and is
    trying to add the opposite kind. See _dashboard's business rule:
    a cart/order is always ALL-normal or ALL-pre-order, never both.
    """
    if existing_type == ORDER_TYPE_NORMAL:
        return "Pre-order items cannot be combined with normal orders. Please checkout your current order first, or clear your cart to start a pre-order."
    return "Normal items cannot be combined with pre-order items. Please place your pre-order separately, or clear your cart to start a normal order."


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

    force = request.POST.get("force") == "1"

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

        incoming_type = ORDER_TYPE_PREORDER if menu_item.is_preorder else ORDER_TYPE_NORMAL
        existing_type = cart_order_type(request.user)

        if existing_type is not None and existing_type != incoming_type:
            if not force:
                error = _mixing_conflict_message(existing_type)
                if _is_ajax(request):
                    return JsonResponse(
                        {
                            "ok": False,
                            "conflict": True,
                            "cart_type": existing_type,
                            "incoming_type": incoming_type,
                            "error": error,
                        },
                        status=409,
                    )
                messages.error(request, error)
                return redirect("menu")
            # Confirmed: clear the existing (opposite-type) cart before
            # adding this item, so the cart always ends up single-type.
            CartItem.objects.filter(user=request.user).delete()

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
        "is_preorder_cart": cart_order_type(request.user) == ORDER_TYPE_PREORDER,
    }

    return render(request, "cart.html", context)


@login_required
def clear_cart(request):
    """
    Empties the current user's cart. Used both as a standalone "Clear
    Cart" action on the cart page, and as the fallback for switching
    order type (normal <-> pre-order) when JavaScript isn't available
    to drive the add_to_cart(force=1) confirm flow.
    """
    if request.method == "POST":
        CartItem.objects.filter(user=request.user).delete()
        if _is_ajax(request):
            return JsonResponse({"ok": True, "cart_count": 0})
        messages.success(request, "Your cart has been cleared.")

    next_url = request.POST.get("next") or request.GET.get("next")
    if next_url in ("menu", "cart"):
        return redirect(next_url)
    return redirect("cart")


@login_required
def remove_from_cart(request, item_id):
    if request.method == "POST":
        # Idempotent by design: if the row is already gone (e.g. the cart
        # was cleared by the normal/pre-order switch, or removed from
        # another tab), the end state the user wants -- this item not
        # being in their cart -- is already true. Treat that as success
        # rather than a 404, since the frontend never has a reliable way
        # to know its cached CartItem id is stale before it tries to use
        # it (see update_cart_quantity for the same reasoning).
        CartItem.objects.filter(id=item_id, user=request.user).delete()

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

    origin = request.POST.get("origin")

    with transaction.atomic():
        cart_item = (
            CartItem.objects.select_for_update()
            .select_related("menu_item")
            .filter(id=item_id, user=request.user)
            .first()
        )

        if cart_item is None:
            # The CartItem this form/button was rendered for no longer
            # exists -- most commonly because the cart was cleared in
            # the meantime (normal/pre-order switch, "Clear Cart", or a
            # second tab/device). The database is the source of truth,
            # so tell the caller plainly instead of raising an unhandled
            # 404; the frontend uses `stale: true` to refresh its view
            # of the cart rather than keep reusing this dead id.
            error = "This item is no longer in your cart."
            cart_count = _cart_count(request.user)
            if _is_ajax(request):
                return JsonResponse(
                    {
                        "ok": False,
                        "stale": True,
                        "in_cart": False,
                        "quantity": 0,
                        "cart_count": cart_count,
                        "error": error,
                    },
                    status=200,
                )
            messages.info(request, error)
            return redirect("menu") if origin == "menu" else redirect("cart")

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
            return redirect("menu") if origin == "menu" else redirect("cart")

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

    return redirect("menu") if origin == "menu" else redirect("cart")
