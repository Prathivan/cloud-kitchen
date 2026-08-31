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