import random
import re

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


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


class OTPVerification(models.Model):
    """
    A one-time-password challenge sent to a mobile number during signup,
    via either SMS or WhatsApp (the customer's choice).

    Verification happens BEFORE the account is created: signup_view only
    lets a CustomerSignupForm through once the mobile number on it
    matches a mobile number this model has on record as verified in the
    current session (see accounts.forms.CustomerSignupForm.clean and
    accounts.views.verify_otp_view). No User/CustomerProfile row is
    touched by this model at all.

    The actual "send" step is delegated to accounts.otp_service, which
    currently only logs/prints the code (no real SMS/WhatsApp provider
    is wired up yet) -- see that module's docstring for how to plug a
    provider in later without changing anything here.
    """

    CHANNEL_SMS = "sms"
    CHANNEL_WHATSAPP = "whatsapp"
    CHANNEL_CHOICES = [
        (CHANNEL_SMS, "SMS"),
        (CHANNEL_WHATSAPP, "WhatsApp"),
    ]

    CODE_LENGTH = 6
    VALIDITY_MINUTES = 5
    RESEND_COOLDOWN_SECONDS = 30
    MAX_ATTEMPTS = 5

    mobile_number = models.CharField(max_length=20, validators=[validate_mobile_number])
    channel = models.CharField(max_length=10, choices=CHANNEL_CHOICES)
    code_hash = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    is_verified = models.BooleanField(default=False)
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        status = "verified" if self.is_verified else "pending"
        return f"OTP for {self.mobile_number} via {self.channel} ({status})"

    @classmethod
    def generate_code(cls):
        return "".join(random.choices("0123456789", k=cls.CODE_LENGTH))

    @classmethod
    def create_for(cls, mobile_number, channel):
        raw_code = cls.generate_code()
        otp = cls.objects.create(
            mobile_number=mobile_number,
            channel=channel,
            code_hash=make_password(raw_code),
            expires_at=timezone.now() + timezone.timedelta(minutes=cls.VALIDITY_MINUTES),
        )
        return otp, raw_code

    @classmethod
    def cooldown_remaining_seconds(cls, mobile_number):
        """
        Seconds left before a new OTP may be requested for this mobile
        number, based on the most recently created (still-relevant)
        record. Returns 0 once the cooldown has passed or none exists.
        """
        last = cls.objects.filter(mobile_number=mobile_number).order_by("-created_at").first()
        if last is None:
            return 0
        elapsed = (timezone.now() - last.created_at).total_seconds()
        remaining = cls.RESEND_COOLDOWN_SECONDS - elapsed
        return max(0, int(remaining))

    def is_expired(self):
        return timezone.now() > self.expires_at

    def check_code(self, raw_code):
        return check_password(raw_code, self.code_hash)
