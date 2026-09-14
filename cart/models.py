from django.db import models
from menu.models import MenuItem
from django.contrib.auth.models import User

class CartItem(models.Model):
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )
    
    menu_item = models.ForeignKey(
        MenuItem,
        on_delete=models.CASCADE
    )

    quantity = models.PositiveIntegerField(default=1)

    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "menu_item"],
                name="unique_cart_item_per_user_menu_item",
            )
        ]

    def subtotal(self):
        return self.menu_item.effective_price * self.quantity

    def __str__(self):
        return f"{self.menu_item.name} x {self.quantity}"


ORDER_TYPE_NORMAL = "normal"
ORDER_TYPE_PREORDER = "preorder"


def cart_order_type(user):
    """
    Whether `user`'s current cart is a NORMAL cart, a PRE-ORDER cart, or
    empty (None). A cart can only ever be one or the other -- this is
    the single place that fact is derived from, so every view/template
    that needs to enforce or display the "no mixing" rule (see
    cart.views.add_to_cart) reads it from here rather than
    re-implementing the check.
    """
    first_item = (
        CartItem.objects.filter(user=user).select_related("menu_item").first()
    )
    if first_item is None:
        return None
    return ORDER_TYPE_PREORDER if first_item.menu_item.is_preorder else ORDER_TYPE_NORMAL