from django.conf import settings
from django.db import models
from django.utils import timezone


class Order(models.Model):
    """
    Kitchen order-status workflow.

    STATUS_PENDING is the entry point (a customer just checked out; the
    kitchen hasn't acted on it yet). From there the kitchen moves an
    order forward one step at a time:

        pending -> confirmed -> preparing -> ready -> out_for_delivery -> delivered

    STATUS_CANCELLED can be reached from any non-terminal state. Each
    *_at timestamp is set once, the moment the order enters that status
    (see OrderAdmin actions) -- they are never backdated or invented.
    """

    STATUS_PENDING = "pending"
    STATUS_CONFIRMED = "confirmed"
    STATUS_PREPARING = "preparing"
    STATUS_READY = "ready"
    STATUS_OUT_FOR_DELIVERY = "out_for_delivery"
    STATUS_DELIVERED = "delivered"
    STATUS_CANCELLED = "cancelled"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_CONFIRMED, "Confirmed"),
        (STATUS_PREPARING, "Preparing"),
        (STATUS_READY, "Ready"),
        (STATUS_OUT_FOR_DELIVERY, "Out for Delivery"),
        (STATUS_DELIVERED, "Delivered"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    # The normal forward path (excludes the cancelled side-branch), used
    # to build the "Order Placed -> ... -> Delivered" progress tracker.
    FORWARD_STATUSES = [
        STATUS_PENDING,
        STATUS_CONFIRMED,
        STATUS_PREPARING,
        STATUS_READY,
        STATUS_OUT_FOR_DELIVERY,
        STATUS_DELIVERED,
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="orders",
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
    )
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    # Set once, the moment the order enters that status. Never backdated.
    confirmed_at = models.DateTimeField(null=True, blank=True)
    preparing_at = models.DateTimeField(null=True, blank=True)
    ready_at = models.DateTimeField(null=True, blank=True)
    out_for_delivery_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Order #{self.id} ({self.user})"

    # Maps each forward status to the timestamp field that records when
    # the order entered it, and the model constant for "the next status".
    _STATUS_TIMESTAMP_FIELD = {
        STATUS_CONFIRMED: "confirmed_at",
        STATUS_PREPARING: "preparing_at",
        STATUS_READY: "ready_at",
        STATUS_OUT_FOR_DELIVERY: "out_for_delivery_at",
        STATUS_DELIVERED: "delivered_at",
        STATUS_CANCELLED: "cancelled_at",
    }

    def advance_to(self, new_status):
        """
        Move this order to `new_status` and stamp the matching timestamp
        field with the current time, if it hasn't already been set.
        Does not save() -- callers (e.g. an admin action operating on a
        queryset) control when to persist.
        """
        self.status = new_status
        field = self._STATUS_TIMESTAMP_FIELD.get(new_status)
        if field and getattr(self, field) is None:
            setattr(self, field, timezone.now())

    def progress_steps(self):
        """
        The forward-path steps with their label and timestamp (or None
        if not yet reached), for a simple "Order Placed -> ... ->
        Delivered" progress tracker. Never used when the order is
        cancelled -- callers should check `status == STATUS_CANCELLED`
        separately.
        """
        label_map = dict(self.STATUS_CHOICES)
        timestamp_map = {
            self.STATUS_PENDING: self.created_at,
            self.STATUS_CONFIRMED: self.confirmed_at,
            self.STATUS_PREPARING: self.preparing_at,
            self.STATUS_READY: self.ready_at,
            self.STATUS_OUT_FOR_DELIVERY: self.out_for_delivery_at,
            self.STATUS_DELIVERED: self.delivered_at,
        }
        current_index = self.FORWARD_STATUSES.index(self.status) if self.status in self.FORWARD_STATUSES else -1
        steps = []
        for index, status_value in enumerate(self.FORWARD_STATUSES):
            steps.append({
                "status": status_value,
                "label": "Order Placed" if status_value == self.STATUS_PENDING else label_map[status_value],
                "timestamp": timestamp_map[status_value],
                "reached": index <= current_index,
            })
        return steps


class OrderItem(models.Model):
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="items",
    )
    # Kept nullable + SET_NULL so a menu item can later be edited/removed
    # from the menu without breaking historical order records.
    menu_item = models.ForeignKey(
        "menu.MenuItem",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="order_items",
    )
    # Snapshot fields so historical orders stay accurate even if the menu
    # item's name/price changes later.
    item_name = models.CharField(max_length=150)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.PositiveIntegerField()

    def subtotal(self):
        return self.price * self.quantity

    def __str__(self):
        return f"{self.item_name} x {self.quantity}"
