from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect, render

from cart.models import CartItem
from menu.models import MenuItem
from .models import Order, OrderItem


@login_required
def my_orders(request):
    orders = (
        Order.objects.filter(user=request.user)
        .prefetch_related("items")
        .order_by("-created_at")
    )

    return render(
        request,
        "orders.html",
        {"orders": orders}
    )


@login_required
def checkout(request):
    """
    Confirms the current user's cart as an Order.

    Runs entirely on the backend inside a single atomic transaction:
    each affected MenuItem row is locked with select_for_update so that
    concurrent checkouts for the same item can never oversell the daily
    selling-unit limit. Availability (base/time/selling-limit) and
    remaining-unit checks are re-validated here regardless of what the
    frontend already showed the user, since frontend validation is for
    UX only and must never be the only protection.
    """
    if request.method != "POST":
        return redirect("cart")

    cart_items = list(
        CartItem.objects.select_related("menu_item")
        .filter(user=request.user)
        .order_by("menu_item_id")  # stable lock ordering avoids deadlocks
    )

    if not cart_items:
        messages.error(request, "Your cart is empty.")
        return redirect("cart")

    try:
        with transaction.atomic():
            order = Order.objects.create(user=request.user, status=Order.STATUS_CONFIRMED)
            total_amount = Decimal("0.00")

            for cart_item in cart_items:
                # Lock the menu item row for the duration of the
                # transaction so a concurrent checkout for the same item
                # can't read a stale total_selling_units value.
                menu_item = MenuItem.objects.select_for_update().get(
                    pk=cart_item.menu_item_id
                )

                if not menu_item.is_available:
                    raise ValueError(f'"{menu_item.name}" is no longer available.')

                if not menu_item.is_within_available_time():
                    raise ValueError(
                        f'"{menu_item.name}" is outside its available ordering hours.'
                    )

                if menu_item.is_selling_unit_tracking:
                    remaining = menu_item.remaining_selling_units()
                    if cart_item.quantity > remaining:
                        raise ValueError(
                            f'Only {remaining} unit(s) of "{menu_item.name}" '
                            f"are left today."
                        )

                OrderItem.objects.create(
                    order=order,
                    menu_item=menu_item,
                    item_name=menu_item.name,
                    price=menu_item.effective_price,
                    quantity=cart_item.quantity,
                )
                total_amount += menu_item.effective_price * cart_item.quantity

                # Always record the confirmed sale, whether or not
                # selling-unit limit tracking is enabled for this item.
                menu_item.register_confirmed_sale(cart_item.quantity)

            order.total_amount = total_amount
            order.save(update_fields=["total_amount"])

            CartItem.objects.filter(
                id__in=[ci.id for ci in cart_items]
            ).delete()
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("cart")

    messages.success(request, f"Order #{order.id} confirmed!")
    return redirect("my_orders")
