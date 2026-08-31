from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from .models import CustomerProfile, mobile_number_re

User = get_user_model()


class CustomerSignupForm(forms.Form):
    """
    Public website signup form.

    Every account created through this form is a plain CUSTOMER account:
    is_staff and is_superuser are never set from here (they default to
    False on a new User and there is no field on this form that can
    touch them), so there is no way to submit your way into an admin
    or staff account through signup.
    """

    full_name = forms.CharField(
        label="Full Name",
        max_length=150,
        widget=forms.TextInput(attrs={"placeholder": "Your full name", "autocomplete": "name"}),
    )
    mobile_number = forms.CharField(
        label="Mobile Number",
        max_length=20,
        widget=forms.TextInput(attrs={"placeholder": "e.g. +1 555 123 4567", "autocomplete": "tel"}),
    )
    email = forms.EmailField(
        label="Email Address",
        widget=forms.EmailInput(attrs={"placeholder": "you@example.com", "autocomplete": "email"}),
    )
    password = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(attrs={"placeholder": "Create a password", "autocomplete": "new-password"}),
    )
    confirm_password = forms.CharField(
        label="Confirm Password",
        widget=forms.PasswordInput(attrs={"placeholder": "Re-enter your password", "autocomplete": "new-password"}),
    )

    def clean_full_name(self):
        full_name = self.cleaned_data["full_name"].strip()
        if not full_name:
            raise ValidationError("Please enter your full name.")
        return full_name

    def clean_mobile_number(self):
        mobile_number = self.cleaned_data["mobile_number"].strip()
        if not mobile_number_re.match(mobile_number):
            raise ValidationError("Enter a valid mobile number (7-15 digits, optionally starting with +).")
        if CustomerProfile.objects.filter(mobile_number=mobile_number).exists():
            raise ValidationError("An account with this mobile number already exists.")
        return mobile_number

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError("An account with this email address already exists.")
        return email

    def clean_password(self):
        password = self.cleaned_data["password"]
        # Reuses Django's built-in password validators (min length,
        # common-password check, not-all-numeric, similarity to the
        # user's own info) instead of inventing new rules.
        validate_password(password)
        return password

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        confirm_password = cleaned_data.get("confirm_password")
        if password and confirm_password and password != confirm_password:
            self.add_error("confirm_password", "Passwords do not match.")
        return cleaned_data

    def save(self):
        """
        Creates the User + CustomerProfile.

        is_staff and is_superuser are explicitly forced to False here,
        even though that's already the Django default for a new user --
        so a future edit to this form can't accidentally start trusting
        a caller-supplied value for either flag.
        """
        email = self.cleaned_data["email"]
        user = User.objects.create_user(
            username=email,
            email=email,
            password=self.cleaned_data["password"],
            is_staff=False,
            is_superuser=False,
        )
        full_name = self.cleaned_data["full_name"]
        name_parts = full_name.split(" ", 1)
        user.first_name = name_parts[0]
        user.last_name = name_parts[1] if len(name_parts) > 1 else ""
        user.save(update_fields=["first_name", "last_name"])

        CustomerProfile.objects.create(
            user=user,
            full_name=full_name,
            mobile_number=self.cleaned_data["mobile_number"],
            role=CustomerProfile.ROLE_CUSTOMER,
        )
        return user


class CustomerProfileForm(forms.Form):
    """
    Lets a logged-in customer view/update their OWN full name, mobile
    number and email. The view that uses this form must always load and
    save against request.user's own profile -- there is no user-id field
    on this form, so there is nothing here a customer could tamper with
    to reach another customer's data.
    """

    full_name = forms.CharField(label="Full Name", max_length=150)
    mobile_number = forms.CharField(label="Mobile Number", max_length=20)
    email = forms.EmailField(label="Email Address")

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_mobile_number(self):
        mobile_number = self.cleaned_data["mobile_number"].strip()
        if not mobile_number_re.match(mobile_number):
            raise ValidationError("Enter a valid mobile number (7-15 digits, optionally starting with +).")
        conflict = CustomerProfile.objects.filter(mobile_number=mobile_number)
        if self.user is not None:
            conflict = conflict.exclude(user=self.user)
        if conflict.exists():
            raise ValidationError("An account with this mobile number already exists.")
        return mobile_number

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        conflict = User.objects.filter(email__iexact=email)
        if self.user is not None:
            conflict = conflict.exclude(pk=self.user.pk)
        if conflict.exists():
            raise ValidationError("An account with this email address already exists.")
        return email
