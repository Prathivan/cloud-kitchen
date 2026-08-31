import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


mobile_number_re = re.compile(r"^\+?\d{7,15}$")


def validate_mobile_number(value):
    if not mobile_number_re.match(value):
        raise ValidationError("Enter a valid mobile number (7-15 digits, optionally starting with +).")


class CustomerProfile(models.Model):
    """
    Extra signup/profile data for a website customer.

    Role/permission decisions are NEVER taken from this model -- they are
    always taken from the built-in User.is_staff / User.is_superuser
    flags, which are enforced by Django's own auth system server-side
    (including for the Django admin at /admin/) and can't be edited from
    a customer-facing form. ``role`` below is descriptive only, useful for
    display in the admin, and must not be used for authorization checks.
    """

    ROLE_CUSTOMER = "customer"
    ROLE_STAFF = "staff"
    ROLE_ADMIN = "admin"
    ROLE_CHOICES = [
        (ROLE_CUSTOMER, "Customer"),
        (ROLE_STAFF, "Staff"),
        (ROLE_ADMIN, "Admin"),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="customer_profile",
    )
    full_name = models.CharField(max_length=150)
    mobile_number = models.CharField(
        max_length=20,
        unique=True,
        validators=[validate_mobile_number],
    )
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default=ROLE_CUSTOMER)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.full_name} ({self.user.email})"
