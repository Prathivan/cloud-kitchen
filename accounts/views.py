from django.contrib import messages
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from menu.models import CustomerReview, MenuItem, RunningOffer
from menu.views import attach_cart_state

from .forms import CustomerProfileForm, CustomerSignupForm
from .models import CustomerProfile


def home(request):
    # Chef Special is now a compact promotional poster in the hero (no
    # Add-to-cart controls there), so it doesn't need cart-state lookups.
    chef_special_items = list(
        MenuItem.objects.select_related("category").filter(
            is_chef_special=True, is_available=True
        )
    )
    popular_items = attach_cart_state(
        MenuItem.objects.select_related("category").filter(
            is_popular=True, is_available=True
        ),
        request.user,
    )
    active_offers = [
        offer for offer in RunningOffer.objects.filter(is_active=True)
        if offer.is_currently_active()
    ]
    reviews = CustomerReview.objects.filter(is_active=True)

    return render(
        request,
        "home.html",
        {
            "chef_special_items": chef_special_items,
            "popular_items": popular_items,
            "active_offers": active_offers,
            "reviews": reviews,
        },
    )


def about(request):
    return render(request, "about.html")


def contact(request):
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        email = request.POST.get("email", "").strip()
        message = request.POST.get("message", "").strip()

        if name and email and message:
            # Demo only: replace with an email send / DB save / ticket creation.
            messages.success(
                request,
                "Thanks for reaching out! We've received your message and will get back to you soon.",
            )
            return redirect("contact")
        messages.error(request, "Please fill in your name, email and message before sending.")

    return render(request, "contact.html")


def login_view(request):
    if request.user.is_authenticated:
        return redirect("home")

    if request.method == "POST":
        # Website accounts sign up with an email address rather than a
        # separate username (the signup form has no username field), so
        # login accepts that same email here — it was stored as the
        # user's username at signup time.
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        user = authenticate(request, username=username, password=password)
        if user is None and username:
            # Signup always stores the email lowercased as the username
            # (see CustomerSignupForm.clean_email), but Django's default
            # auth backend matches usernames case-sensitively. Someone
            # who signs up as "Jane@Example.com" gets stored as
            # "jane@example.com" — if they then type the capitalised
            # version again at login, authenticate() above fails even
            # though the password is correct. Retry once with the
            # lowercased value before giving up.
            user = authenticate(request, username=username.lower(), password=password)
        if user is not None:
            # Customers land on the normal website; this is the same
            # redirect for every account type here because this login
            # form is website-only. Staff/admin backend access is
            # handled entirely by Django's separate /admin/ login, which
            # this view never touches.
            auth_login(request, user)
            display_name = user.first_name or user.username
            messages.success(request, f"Welcome back, {display_name}!")
            return redirect("home")
        messages.error(request, "Invalid email or password. Please try again.")

    return render(request, "login.html")


def signup_view(request):
    if request.user.is_authenticated:
        return redirect("home")

    form = CustomerSignupForm(request.POST or None)
    if request.method == "POST":
        if form.is_valid():
            user = form.save()
            auth_login(request, user)
            messages.success(request, f"Account created — welcome, {user.first_name}!")
            return redirect("home")
        messages.error(request, "Please fix the errors below and try again.")

    return render(request, "signup.html", {"form": form})


def logout_view(request):
    auth_logout(request)
    messages.success(request, "You've been logged out.")
    return redirect("home")


@login_required
def account_view(request):
    """
    A customer's own profile page. Always operates on request.user's own
    CustomerProfile — there is no way to pass in a different user id, so
    a logged-in customer can never view or edit another customer's data
    through this view.
    """
    profile, _created = CustomerProfile.objects.get_or_create(
        user=request.user,
        defaults={
            "full_name": request.user.get_full_name() or request.user.username,
            "mobile_number": "",
        },
    )

    if request.method == "POST":
        form = CustomerProfileForm(
            request.POST,
            user=request.user,
            initial={
                "full_name": profile.full_name,
                "mobile_number": profile.mobile_number,
                "email": request.user.email,
            },
        )
        if form.is_valid():
            profile.full_name = form.cleaned_data["full_name"]
            profile.mobile_number = form.cleaned_data["mobile_number"]
            profile.save(update_fields=["full_name", "mobile_number"])

            name_parts = profile.full_name.split(" ", 1)
            request.user.first_name = name_parts[0]
            request.user.last_name = name_parts[1] if len(name_parts) > 1 else ""
            request.user.email = form.cleaned_data["email"]
            request.user.save(update_fields=["first_name", "last_name", "email"])

            messages.success(request, "Your profile has been updated.")
            return redirect("account")
        messages.error(request, "Please fix the errors below and try again.")
    else:
        form = CustomerProfileForm(
            user=request.user,
            initial={
                "full_name": profile.full_name,
                "mobile_number": profile.mobile_number,
                "email": request.user.email,
            },
        )

    orders = (
        request.user.orders
        .prefetch_related("items")
        .order_by("-created_at")
    )

    return render(request, "account.html", {"form": form, "profile": profile, "orders": orders})


def cart(request):
    return render(request, "cart.html")
