from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class Category(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)

    def __str__(self):
        return self.name


class MenuItem(models.Model):
    FOOD_TYPE_CHOICES = [
        ("veg", "Veg"),
        ("non_veg", "Non-Veg"),
    ]

    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        related_name="menu_items"
    )
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    image = models.ImageField(upload_to="menu/", blank=True, null=True)

    food_type = models.CharField(
        max_length=10,
        choices=FOOD_TYPE_CHOICES,
        default="veg",
    )

    # Homepage marketing flags. Purely presentational -- neither affects
    # ordering/availability logic.
    is_chef_special = models.BooleanField(default=False)
    is_popular = models.BooleanField(default=False)

    # Offer pricing. offer_price is only used when has_offer is True; the
    # effective_price property below is the single source of truth every
    # part of the app (menu, home sliders, cart, checkout) must use.
    has_offer = models.BooleanField(default=False)
    offer_price = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )

    # Main/manual availability switch.
    is_available = models.BooleanField(default=True)

    # Controls whether the daily selling LIMIT (per_day_selling_units) is
    # enforced. total_selling_units is ALWAYS tracked regardless of this flag.
    # Defaults to off: with per_day_selling_units defaulting to 0, leaving
    # tracking on by default would make every newly-created item
    # immediately "sold out" (0 >= 0) until an admin explicitly configures
    # a limit. Off-by-default means new items are orderable immediately.
    is_selling_unit_tracking = models.BooleanField(default=False)
    per_day_selling_units = models.PositiveIntegerField(default=0)
    total_selling_units = models.PositiveIntegerField(default=0)

    # The calendar day (in the app's configured timezone) that
    # total_selling_units currently reflects. Used to lazily reset the
    # counter at the start of a new day without depending on a scheduler.
    selling_units_date = models.DateField(default=timezone.localdate)

    # Controls whether the is_available_from/is_available_till time window
    # is enforced.
    available_tracking = models.BooleanField(default=True)
    is_available_from = models.TimeField(null=True, blank=True)
    is_available_till = models.TimeField(null=True, blank=True)

    def __str__(self):
        return self.name

    # ------------------------------------------------------------------
    # Offer pricing
    # ------------------------------------------------------------------
    def clean(self):
        super().clean()
        if self.has_offer:
            if self.offer_price is None:
                raise ValidationError(
                    {"offer_price": "Set an offer price, or turn the offer off."}
                )
            if self.offer_price <= 0:
                raise ValidationError(
                    {"offer_price": "Offer price must be greater than 0."}
                )
            if self.price is not None and self.offer_price >= self.price:
                raise ValidationError(
                    {"offer_price": "Offer price must be less than the original price."}
                )

    @property
    def effective_price(self):
        """
        The single source of truth for what the customer actually pays.
        Every price shown or charged anywhere in the app (menu, home
        sliders, cart, checkout) must go through this property so an
        active offer is never silently ignored.
        """
        if self.has_offer and self.offer_price is not None:
            return self.offer_price
        return self.price

    # ------------------------------------------------------------------
    # Daily selling-unit tracking
    # ------------------------------------------------------------------
    def reset_units_if_new_day(self):
        """
        Reset the in-memory total_selling_units/selling_units_date if the
        tracked day has rolled over. This mutates the instance only; the
        caller is responsible for persisting the change (see
        register_confirmed_sale, which does this under a row lock).

        Read-only callers (e.g. rendering the menu page) can use this to
        get an accurate *value* without necessarily persisting a reset
        that another concurrent request may already be performing.
        """
        today = timezone.localdate()
        if self.selling_units_date != today:
            self.total_selling_units = 0
            self.selling_units_date = today
            return True
        return False

    def remaining_selling_units(self):
        """
        Units still available to sell today, or None if selling-unit
        limit tracking is disabled for this item (no cap).
        """
        if not self.is_selling_unit_tracking:
            return None
        self.reset_units_if_new_day()
        remaining = self.per_day_selling_units - self.total_selling_units
        return max(remaining, 0)

    def is_selling_limit_reached(self):
        """
        True only when selling-unit tracking is enabled AND the daily
        limit has been reached/exceeded. When tracking is disabled this
        always returns False, even though total_selling_units keeps
        counting in the background.
        """
        if not self.is_selling_unit_tracking:
            return False
        self.reset_units_if_new_day()
        return self.total_selling_units >= self.per_day_selling_units

    def register_confirmed_sale(self, quantity):
        """
        Record `quantity` confirmed units sold today. Must be called with
        this row locked (select_for_update) inside an atomic transaction
        so concurrent confirmations can't oversell. Always increments
        total_selling_units, whether or not is_selling_unit_tracking is
        enabled.
        """
        self.reset_units_if_new_day()
        self.total_selling_units += quantity
        self.save(update_fields=["total_selling_units", "selling_units_date"])

    # ------------------------------------------------------------------
    # Time-window availability
    # ------------------------------------------------------------------
    def is_within_available_time(self, at=None):
        """
        True when time-based availability is disabled, no window is
        configured, or the given/current local time falls within
        [is_available_from, is_available_till].
        """
        if not self.available_tracking:
            return True
        if not self.is_available_from or not self.is_available_till:
            return True
        current_time = at or timezone.localtime().time()
        return self.is_available_from <= current_time <= self.is_available_till

    # ------------------------------------------------------------------
    # Combined availability
    # ------------------------------------------------------------------
    def is_currently_orderable(self):
        """
        AVAILABLE = is_available
            AND (selling-unit tracking off OR limit not reached)
            AND (time tracking off OR within the configured window)
        """
        return (
            self.is_available
            and not self.is_selling_limit_reached()
            and self.is_within_available_time()
        )


class RunningOffer(models.Model):
    """A promotional banner shown in the Home page 'Running Offers' slider."""

    title = models.CharField(max_length=150)
    description = models.CharField(max_length=255, blank=True)
    image = models.ImageField(upload_to="offers/", blank=True, null=True)
    button_text = models.CharField(max_length=40, blank=True)
    button_link = models.URLField(blank=True)
    is_active = models.BooleanField(default=True)
    display_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["display_order", "-created_at"]

    def __str__(self):
        return self.title


class CustomerReview(models.Model):
    """A customer testimonial shown in the Home page reviews slider."""

    RATING_CHOICES = [(i, "★" * i) for i in range(1, 6)]

    customer_name = models.CharField(max_length=100)
    review_text = models.TextField()
    rating = models.PositiveSmallIntegerField(choices=RATING_CHOICES, default=5)
    avatar = models.ImageField(upload_to="reviews/", blank=True, null=True)
    is_active = models.BooleanField(default=True)
    display_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["display_order", "-created_at"]

    def __str__(self):
        return f"{self.customer_name} ({self.rating}★)"
