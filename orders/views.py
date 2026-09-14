from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from cart.models import CartItem
from delivery.models import DeliveryAddress
from menu.models import MenuItem
from accounts.models import mobile_number_re
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


def _account_name_and_phone(user, fallback_address=None):
    """
    The account holder's current name/phone, used as the "Myself"
    delivery default and always recorded as customer_name/
    customer_phone on the order regardless of delivery_type.

    Falls back gracefully when there's no CustomerProfile at all (e.g.
    an account made via `createsuperuser` rather than signup, which
    never gets one) -- in that case, the contact info entered on the
    selected delivery address is a far more useful fallback than a
    blank field, since the customer typed a real name/phone there.
    Only falls back to the bare username (with no phone) if neither is
    available.
    """
    profile = getattr(user, "customer_profile", None)
    if profile:
        return profile.full_name, profile.mobile_number
    if fallback_address:
        return fallback_address.full_name, fallback_address.phone
    return (user.get_full_name() or user.username), ""


@login_required
def checkout_address_select(request):
    """
    The "Select Delivery Address" / "Deliver To" step shown between the
    cart and actually placing the order (see templates/checkout.html).
    This is purely a display + form step -- nothing here creates the
    order or touches the cart; the form on this page POSTs to the
    `checkout` view below, which does all the real validation and
    order creation.
    """
    cart_items = list(CartItem.objects.select_related("menu_item").filter(user=request.user))
    if not cart_items:
        messages.error(request, "Your cart is empty.")
        return redirect("cart")

    addresses = DeliveryAddress.objects.filter(user=request.user)
    default_address = addresses.filter(is_default=True).first() or addresses.first()
    subtotal = sum((ci.menu_item.effective_price * ci.quantity for ci in cart_items), Decimal("0.00"))
    delivery_fee = Order._meta.get_field("delivery_fee").default
    customer_name, customer_phone = _account_name_and_phone(request.user, fallback_address=default_address)

    return render(
        request,
        "checkout.html",
        {
            "cart_items": cart_items,
            "addresses": addresses,
            "default_address": default_address,
            "subtotal": subtotal,
            "delivery_fee": delivery_fee,
            "total": subtotal + delivery_fee,
            "customer_name": customer_name,
            "customer_phone": customer_phone,
            "google_maps_api_key": settings.GOOGLE_MAPS_API_KEY,
        },
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

    Delivery/recipient fields (address_id, deliver_to, recipient_name,
    recipient_phone, delivery_instructions) are all OPTIONAL POST
    fields: this view is also called directly (with just the cart, no
    delivery step) by anything that posts here without going through
    checkout_address_select first, so it must keep working with none of
    them supplied -- defaulting delivery_type to SELF and using the
    account holder's own name/phone as the recipient.
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

    # ------------------------------------------------------------------
    # Resolve delivery/recipient details BEFORE the transaction, so a
    # validation problem here (e.g. missing recipient phone) never
    # leaves a half-created order or a needlessly-locked MenuItem row.
    # ------------------------------------------------------------------
    address_snapshot = {}
    delivery_address = None
    address_id = request.POST.get("address_id")
    if address_id:
        # Ownership check: a customer can only select one of THEIR OWN
        # saved addresses -- never trust a raw id from the client alone.
        delivery_address = get_object_or_404(DeliveryAddress, pk=address_id, user=request.user)
        address_snapshot = delivery_address.as_snapshot_dict()

    # Resolved AFTER the address lookup above so that, when the account
    # has no CustomerProfile (e.g. createsuperuser rather than signup),
    # the selected address's own contact fields are available as a
    # fallback -- see _account_name_and_phone's docstring.
    customer_name, customer_phone = _account_name_and_phone(request.user, fallback_address=delivery_address)

    deliver_to = request.POST.get("deliver_to", Order.DELIVERY_TYPE_SELF)
    if deliver_to not in (Order.DELIVERY_TYPE_SELF, Order.DELIVERY_TYPE_OTHER):
        deliver_to = Order.DELIVERY_TYPE_SELF

    if deliver_to == Order.DELIVERY_TYPE_OTHER:
        recipient_name = request.POST.get("recipient_name", "").strip()
        recipient_phone = request.POST.get("recipient_phone", "").strip()
        if not recipient_name or not recipient_phone:
            messages.error(request, "Please enter the recipient's name and mobile number.")
            return redirect("checkout_address")
        # Presence alone isn't enough -- format must actually be a
        # valid Indian mobile number too. This was previously only
        # checked on saved DeliveryAddress records (via the ModelForm),
        # never on a one-off "Someone Else" recipient typed in at
        # checkout, so something like "44323" was silently accepted
        # and stored as-is.
        if not mobile_number_re.match(recipient_phone):
            messages.error(
                request,
                "Enter a valid Indian mobile number for the recipient (10 digits starting with 6-9, optionally prefixed with +91).",
            )
            return redirect("checkout_address")
    else:
        # "Myself": the recipient IS the account holder -- never read
        # from a recipient_* POST field for this branch, so a stray or
        # tampered client value can't silently override it.
        recipient_name, recipient_phone = customer_name, customer_phone

    delivery_instructions_override = request.POST.get("delivery_instructions")
    if delivery_instructions_override is not None:
        address_snapshot["delivery_instructions"] = delivery_instructions_override.strip()

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
                user=request.user,
                status=Order.STATUS_PENDING,
                is_preorder=is_preorder_order,
                delivery_type=deliver_to,
                customer_name=customer_name,
                customer_phone=customer_phone,
                recipient_name=recipient_name,
                recipient_phone=recipient_phone,
                delivery_address=delivery_address,
                **address_snapshot,
            )
            items_subtotal = Decimal("0.00")
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
                items_subtotal += menu_item.effective_price * cart_item.quantity

                # Always record the confirmed sale, whether or not
                # selling-unit limit tracking is enabled for this item.
                menu_item.register_confirmed_sale(cart_item.quantity)

            # delivery_fee was already set to its model default by
            # Order.objects.create() above -- included here explicitly
            # so the total always reflects whatever that turns out to be.
            order.total_amount = items_subtotal + order.delivery_fee
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
