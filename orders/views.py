from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect, render
from django.utils import timezone

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
            # Backend is the source of truth: re-derive the order type
            # from the locked cart items themselves rather than trusting
            # anything the client sent, and reject a mixed cart outright
            # even though the cart UI already prevents building one.
            preorder_item_ids = {ci.menu_item_id for ci in cart_items if ci.menu_item.is_preorder}
            normal_item_ids = {ci.menu_item_id for ci in cart_items if not ci.menu_item.is_preorder}
            if preorder_item_ids and normal_item_ids:
                raise ValueError(
                    "Your cart mixes normal and pre-order items, which isn't allowed. "
                    "Please clear your cart and checkout each order type separately."
                )
            is_preorder_order = bool(preorder_item_ids)

            order = Order.objects.create(
                user=request.user, status=Order.STATUS_PENDING, is_preorder=is_preorder_order
            )
            total_amount = Decimal("0.00")
            order_placed_at = timezone.now()
            max_preorder_hours = 0

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

                if menu_item.is_preorder:
                    if not menu_item.preorder_hours or menu_item.preorder_hours <= 0:
                        raise ValueError(
                            f'"{menu_item.name}" is missing a valid pre-order lead time. '
                            f"Please contact support."
                        )
                    # If multiple pre-order items are in the same order with
                    # different lead times, the order is only ready once
                    # EVERY item is ready -- so use the longest one.
                    max_preorder_hours = max(max_preorder_hours, menu_item.preorder_hours)

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
            update_fields = ["total_amount"]

            if is_preorder_order:
                # Snapshot the fulfillment time NOW, from the hours value
                # each menu item had at the moment of purchase. This is
                # deliberately never recalculated from the live MenuItem
                # later -- if an admin changes preorder_hours afterwards,
                # already-placed orders must keep the time the customer
                # was originally promised.
                order.preorder_datetime = order_placed_at + timezone.timedelta(hours=max_preorder_hours)
                update_fields.append("preorder_datetime")

            order.save(update_fields=update_fields)

            CartItem.objects.filter(
                id__in=[ci.id for ci in cart_items]
            ).delete()
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("cart")

    messages.success(request, f"Order #{order.id} confirmed!")
    return redirect("my_orders")
