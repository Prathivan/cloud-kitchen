from django.shortcuts import render

from cart.models import CartItem
from menu.models import Category, MenuItem


def attach_cart_state(items, user):
    """
    Annotate each MenuItem in `items` (a list, not a queryset -- so this
    can be reused across independently-fetched sections on the Home page)
    with:

      - cart_item: the user's existing CartItem for this item, or None
      - orderable: combined availability (see MenuItem.is_currently_orderable)
      - remaining_units: units left today, or None if untracked

    Shared by the Menu page and every Home page section (Chef Special,
    Popular Dishes) that renders the same Add/quantity cart controls, so
    the cart logic lives in exactly one place.
    """
    items = list(items)
    if not items:
        return items

    if user.is_authenticated:
        cart_items = CartItem.objects.filter(
            user=user,
            menu_item_id__in=[item.id for item in items],
        )
    else:
        cart_items = CartItem.objects.none()

    cart_item_map = {
        cart_item.menu_item_id: cart_item
        for cart_item in cart_items
    }

    for item in items:
        item.cart_item = cart_item_map.get(item.id)
        item.orderable = item.is_currently_orderable()
        item.remaining_units = item.remaining_selling_units()

    return items


def menu(request):
    categories = Category.objects.all()
    menu_items = attach_cart_state(
        MenuItem.objects.select_related("category").all(),
        request.user,
    )

    return render(
        request,
        "menu.html",
        {
            "categories": categories,
            "menu_items": menu_items,
        }
    )
