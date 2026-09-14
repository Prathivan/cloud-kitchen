from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from accounts.models import validate_mobile_number


class DeliveryAddress(models.Model):
    """
    A customer's saved delivery address, optionally pinned to an exact
    spot on Google Maps.

    IMPORTANT: this model is the *editable* record a customer manages
    from their account (add/edit/delete/set default). It is NOT what an
    already-placed Order reads from. At checkout, every field a
    customer might later change here gets copied ("snapshotted") onto
    the Order itself (see orders.models.Order) -- so editing or
    deleting an address here never alters any past order. Treat this
    model purely as "the customer's current address book," and
    orders.models.Order as "what an order actually shipped to."
    """

    LABEL_HOME = "home"
    LABEL_WORK = "work"
    LABEL_OTHER = "other"
    LABEL_CHOICES = [
        (LABEL_HOME, "Home"),
        (LABEL_WORK, "Work"),
        (LABEL_OTHER, "Other"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="delivery_addresses",
    )

    full_name = models.CharField(max_length=150)
    phone = models.CharField(max_length=20, validators=[validate_mobile_number])

    address_line_1 = models.CharField(max_length=255)
    address_line_2 = models.CharField(max_length=255, blank=True)
    building = models.CharField(max_length=100, blank=True)
    apartment = models.CharField(max_length=100, blank=True)
    floor = models.CharField(max_length=50, blank=True)
    street = models.CharField(max_length=150, blank=True)
    area = models.CharField(max_length=150, blank=True)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100)
    country = models.CharField(max_length=100, default="India")
    postal_code = models.CharField(max_length=20)

    delivery_instructions = models.TextField(blank=True)
    address_label = models.CharField(max_length=10, choices=LABEL_CHOICES, default=LABEL_HOME)

    # Populated by the Google Maps picker on the address form (see
    # templates/delivery_address_form.html). All optional: a customer
    # can, in principle, save an address without ever touching the map,
    # though the UI strongly encourages pinning one for accurate
    # delivery.
    latitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True,
        validators=[MinValueValidator(-90), MaxValueValidator(90)],
    )
    longitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True,
        validators=[MinValueValidator(-180), MaxValueValidator(180)],
    )
    google_place_id = models.CharField(max_length=255, blank=True)
    formatted_address = models.CharField(max_length=500, blank=True)

    is_default = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-is_default", "-updated_at"]
        verbose_name_plural = "delivery addresses"

    def __str__(self):
        return f"{self.get_address_label_display()} address for {self.user} (#{self.pk})"

    def clean(self):
        # Lat/long are optional individually at the DB level (a customer
        # might save partial progress), but if either is present, both
        # must be -- a lone coordinate is meaningless and almost always
        # a sign the map pin was never actually confirmed.
        if (self.latitude is None) != (self.longitude is None):
            raise ValidationError("Both latitude and longitude are required together, or leave both empty.")

    def short_display(self):
        """One-line summary for address-picker UI (checkout, address list)."""
        parts = [p for p in [self.address_line_1, self.area, self.city] if p]
        return ", ".join(parts)

    def as_snapshot_dict(self):
        """
        The subset of fields copied onto an Order at checkout time (see
        orders.views.place_order). Centralized here so the checkout view
        and any future caller build the snapshot the exact same way.
        """
        return {
            "address_line_1": self.address_line_1,
            "address_line_2": self.address_line_2,
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
            "latitude": self.latitude,
            "longitude": self.longitude,
            "google_place_id": self.google_place_id,
            "delivery_instructions": self.delivery_instructions,
        }

    def save(self, *args, **kwargs):
        """
        Enforces "at most one default address per customer" at the model
        level (not just in the view), so this invariant holds no matter
        how a save happens (admin, shell, future API, etc.) -- not only
        through delivery.views.set_default_address.
        """
        super().save(*args, **kwargs)
        if self.is_default:
            DeliveryAddress.objects.filter(user_id=self.user_id).exclude(pk=self.pk).update(is_default=False)
