from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from accounts.models import validate_mobile_number


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
    # Flat fee at the time of writing (matches the amount already shown
    # to the customer in the cart summary, see static/js/script.js's
    # cart total calculation) -- kept editable per-order rather than a
    # global constant so a future zone-based or promotional fee never
    # has to touch old orders.
    delivery_fee = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("40.00"))
    created_at = models.DateTimeField(auto_now_add=True)

    # ------------------------------------------------------------------
    # Delivery snapshot
    # ------------------------------------------------------------------
    # Everything below is copied ("snapshotted") from the customer's
    # account and/or their chosen delivery.models.DeliveryAddress at the
    # exact moment checkout happens (see orders.views.place_order) --
    # and is NEVER read back from those live records afterwards. This is
    # deliberate: if the customer later edits their name, phone, or a
    # saved address, every order placed before that edit must keep
    # showing exactly what was true when it was placed. Treat every
    # field in this section as frozen history, not a live reference.

    DELIVERY_TYPE_SELF = "self"
    DELIVERY_TYPE_OTHER = "other"
    DELIVERY_TYPE_CHOICES = [
        (DELIVERY_TYPE_SELF, "Myself"),
        (DELIVERY_TYPE_OTHER, "Someone Else"),
    ]
    delivery_type = models.CharField(max_length=10, choices=DELIVERY_TYPE_CHOICES, default=DELIVERY_TYPE_SELF)

    # The account holder's own name/phone at checkout time -- always
    # filled in, regardless of delivery_type, so "who placed this
    # order" is never lost even if delivery_type is OTHER.
    customer_name = models.CharField(max_length=150, blank=True)
    customer_phone = models.CharField(max_length=20, blank=True)

    # Who the order actually goes to. When delivery_type is SELF, these
    # are copied from customer_name/customer_phone at checkout; when
    # OTHER, these are whatever the customer typed in for that one
    # order (see section 3 of the delivery feature spec) and are NEVER
    # confused with the account holder's own phone number.
    recipient_name = models.CharField(max_length=150, blank=True)
    recipient_phone = models.CharField(max_length=20, blank=True, validators=[validate_mobile_number])

    # Purely a traceability link back to the saved address that was
    # selected (so admin/support can see "which saved address did they
    # pick"), kept nullable + SET_NULL so deleting a saved address never
    # deletes or breaks any order. Every field actually needed to
    # fulfil or display the order is snapshotted as a plain column
    # below instead of being read through this relation.
    delivery_address = models.ForeignKey(
        "delivery.DeliveryAddress",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders",
    )

    address_line_1 = models.CharField(max_length=255, blank=True)
    address_line_2 = models.CharField(max_length=255, blank=True)
    building = models.CharField(max_length=100, blank=True)
    apartment = models.CharField(max_length=100, blank=True)
    floor = models.CharField(max_length=50, blank=True)
    street = models.CharField(max_length=150, blank=True)
    area = models.CharField(max_length=150, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    country = models.CharField(max_length=100, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    formatted_address = models.CharField(max_length=500, blank=True)

    latitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True,
        validators=[MinValueValidator(-90), MaxValueValidator(90)],
    )
    longitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True,
        validators=[MinValueValidator(-180), MaxValueValidator(180)],
    )
    google_place_id = models.CharField(max_length=255, blank=True)

    delivery_instructions = models.TextField(blank=True)

    # ------------------------------------------------------------------
    # Pre-order
    # ------------------------------------------------------------------
    # True for an order made up entirely of pre-order menu items. Cart
    # logic (see cart.models.cart_order_type) guarantees a cart -- and
    # therefore an order created from it -- never mixes normal and
    # pre-order items, so this single flag is enough to tell the two
    # order types apart everywhere (admin list/filter, customer pages).
    is_preorder = models.BooleanField(default=False, db_index=True)

    # Calculated once at checkout as
    #   order.created_at + max(item.menu_item.preorder_hours for item in order)
    # and never recalculated afterwards -- see orders.views.checkout.
    # This is a *snapshot*: if an admin later changes a menu item's
    # preorder_hours, existing orders keep the value that was true when
    # they were placed. Always null for normal orders.
    preorder_datetime = models.DateTimeField(null=True, blank=True, db_index=True)

    # Flips to True the moment the 1-hour-before reminder has been
    # created for this order, so the scheduler never creates a duplicate
    # reminder for the same order on a later run.
    preorder_reminder_sent = models.BooleanField(default=False)

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

    def google_maps_url(self):
        """
        A direct link to this order's exact delivery pin, for admin/
        support use (see orders/admin.py and the print view). Built
        from stored latitude/longitude rather than the text address, as
        required -- addresses can be ambiguous, coordinates aren't.
        Returns None if no pin was captured for this order.
        """
        if self.latitude is None or self.longitude is None:
            return None
        return f"https://www.google.com/maps/search/?api=1&query={self.latitude},{self.longitude}"

    def masked_customer_phone(self):
        """
        The account holder's phone with everything but the last 4
        digits hidden, e.g. "••••••3210". Used on the printed order
        slip (see order_print.html), which is meant for kitchen/
        delivery staff -- they need the RECIPIENT's full number to
        actually make the delivery, but have no legitimate need to see
        the account holder's full number when delivering to someone
        else. Returns "—" if there's no customer phone on file at all.
        """
        digits = self.customer_phone or ""
        if len(digits) <= 4:
            return digits or "—"
        return "•" * (len(digits) - 4) + digits[-4:]

    def items_subtotal(self):
        """Sum of every line item, before delivery_fee -- used by the
        checkout/print views so "Subtotal" and "Total" never have to be
        kept in sync by hand."""
        return sum((item.subtotal() for item in self.items.all()), Decimal("0.00"))

    def to_delivery_partner_dict(self):
        """
        Everything a future third-party delivery-partner API would need
        to pick up and deliver this order, in one place. Nothing calls
        this yet (per the current scope: prepare the data, don't
        integrate a provider) -- it exists so that integration, when it
        happens, consumes this method rather than reaching into model
        fields ad hoc across the codebase.
        """
        return {
            "order_id": self.id,
            "customer_name": self.customer_name,
            "customer_phone": self.customer_phone,
            "recipient_name": self.recipient_name,
            "recipient_phone": self.recipient_phone,
            "delivery_type": self.delivery_type,
            "address": {
                "line_1": self.address_line_1,
                "line_2": self.address_line_2,
                "building": self.building,
                "apartment": self.apartment,
                "floor": self.floor,
                "street": self.street,
                "area": self.area,
                "city": self.city,
                "state": self.state,
                "country": self.country,
                "postal_code": self.postal_code,
                "formatted_address": self.formatted_address,
            },
            "latitude": float(self.latitude) if self.latitude is not None else None,
            "longitude": float(self.longitude) if self.longitude is not None else None,
            "google_place_id": self.google_place_id,
            "delivery_instructions": self.delivery_instructions,
            "items": [
                {"name": item.item_name, "quantity": item.quantity, "price": str(item.price)}
                for item in self.items.all()
            ],
            "subtotal": str(self.items_subtotal()),
            "delivery_fee": str(self.delivery_fee),
            "total_amount": str(self.total_amount),
        }

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


class AdminNotification(models.Model):
    """
    Generic admin-panel notification. Currently only created by the
    pre-order reminder scheduler (see orders/reminders.py), but kept
    general so other kinds of alerts can reuse it later.
    """

    TYPE_PREORDER_REMINDER = "preorder_reminder"
    TYPE_CHOICES = [
        (TYPE_PREORDER_REMINDER, "Pre-Order Reminder"),
    ]

    notification_type = models.CharField(max_length=30, choices=TYPE_CHOICES)
    message = models.CharField(max_length=255)
    order = models.ForeignKey(
        Order, on_delete=models.CASCADE, null=True, blank=True, related_name="notifications"
    )
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.message
