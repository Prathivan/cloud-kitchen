from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from menu.models import CustomerReview, MenuItem, RunningOffer
from menu.views import attach_cart_state

from . import otp_service
from .forms import CustomerProfileForm, CustomerSignupForm
from .models import CustomerProfile, OTPVerification, mobile_number_re

# Session keys used to carry "this mobile number was OTP-verified"
# across the two signup requests (send/verify OTP, then the final
# signup POST). Cleared once the account is actually created.
SESSION_VERIFIED_MOBILE = "otp_verified_mobile_number"
SESSION_VERIFIED_AT = "otp_verified_mobile_at"


def home(request):
    chef_special_items = attach_cart_state(
        MenuItem.objects.select_related("category").filter(
            is_chef_special=True, is_available=True
        ),
        request.user,
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


@require_POST
def send_otp_view(request):
    """
    Step 1 of signup: generate and "send" (see accounts.otp_service) an
    OTP for a mobile number, over the customer's chosen channel.

    Deliberately does NOT require the caller to be logged out or
    logged in -- it never touches User/CustomerProfile, only the
    standalone OTPVerification model, so it's safe to call before any
    account exists.
    """
    mobile_number = request.POST.get("mobile_number", "").strip()
    channel = request.POST.get("channel", "").strip()

    if not mobile_number_re.match(mobile_number):
        return JsonResponse(
            {"ok": False, "error": "Enter a valid mobile number (7-15 digits, optionally starting with +)."},
            status=400,
        )
    if channel not in (OTPVerification.CHANNEL_SMS, OTPVerification.CHANNEL_WHATSAPP):
        return JsonResponse({"ok": False, "error": "Choose SMS or WhatsApp to receive the code."}, status=400)
    if CustomerProfile.objects.filter(mobile_number=mobile_number).exists():
        return JsonResponse(
            {"ok": False, "error": "An account with this mobile number already exists. Please log in instead."},
            status=400,
        )

    cooldown = OTPVerification.cooldown_remaining_seconds(mobile_number)
    if cooldown > 0:
        return JsonResponse(
            {"ok": False, "error": f"Please wait {cooldown}s before requesting another code.", "cooldown": cooldown},
            status=429,
        )

    otp, raw_code = OTPVerification.create_for(mobile_number, channel)
    otp_service.send_otp(mobile_number, channel, raw_code)

    # This mobile number is no longer verified in THIS session until
    # the new code is confirmed -- clears any stale verification from
    # an earlier code for the same number.
    if request.session.get(SESSION_VERIFIED_MOBILE) == mobile_number:
        del request.session[SESSION_VERIFIED_MOBILE]
        request.session.pop(SESSION_VERIFIED_AT, None)

    response_data = {
        "ok": True,
        "message": f"A verification code was sent via {otp.get_channel_display()}.",
        "expires_in": OTPVerification.VALIDITY_MINUTES * 60,
        "resend_cooldown": OTPVerification.RESEND_COOLDOWN_SECONDS,
    }
    # TEMPORARY dev convenience: show the code directly on the signup
    # page so it's testable while no real SMS/WhatsApp provider is
    # live yet, without digging through the runserver console. Gated
    # on DEBUG so this can NEVER leak a real code once the site is
    # actually deployed for real customers (DEBUG=False in production)
    # -- remove this block entirely once MSG91 is fully verified and
    # sending for real, so testers see the real delivery experience.
    if settings.DEBUG:
        response_data["debug_code"] = raw_code
    return JsonResponse(response_data)


@require_POST
def verify_otp_view(request):
    """
    Step 2 of signup: check the code the customer typed in against the
    most recent OTP issued for that mobile number. On success, marks
    the mobile number verified in THIS browser session only (not in
    the database as belonging to any account) -- signup_view checks
    for exactly this session flag before it will create an account.
    """
    mobile_number = request.POST.get("mobile_number", "").strip()
    code = request.POST.get("code", "").strip()

    if not mobile_number_re.match(mobile_number):
        return JsonResponse({"ok": False, "error": "Enter a valid mobile number first."}, status=400)
    if not code:
        return JsonResponse({"ok": False, "error": "Enter the code you received."}, status=400)

    otp = OTPVerification.objects.filter(mobile_number=mobile_number, is_verified=False).order_by("-created_at").first()
    if otp is None:
        return JsonResponse(
            {"ok": False, "error": "No pending code for this number. Please request a new one."}, status=400
        )
    if otp.is_expired():
        return JsonResponse({"ok": False, "error": "This code has expired. Please request a new one."}, status=400)
    if otp.attempts >= OTPVerification.MAX_ATTEMPTS:
        return JsonResponse(
            {"ok": False, "error": "Too many incorrect attempts. Please request a new code."}, status=400
        )

    if not otp.check_code(code):
        otp.attempts += 1
        otp.save(update_fields=["attempts"])
        remaining = OTPVerification.MAX_ATTEMPTS - otp.attempts
        return JsonResponse(
            {"ok": False, "error": f"Incorrect code. {remaining} attempt(s) remaining."}, status=400
        )

    otp.is_verified = True
    otp.verified_at = timezone.now()
    otp.save(update_fields=["is_verified", "verified_at"])

    request.session[SESSION_VERIFIED_MOBILE] = mobile_number
    request.session[SESSION_VERIFIED_AT] = timezone.now().isoformat()

    return JsonResponse({"ok": True, "message": "Mobile number verified."})


def signup_view(request):
    if request.user.is_authenticated:
        return redirect("home")

    verified_mobile = request.session.get(SESSION_VERIFIED_MOBILE, "")

    form = CustomerSignupForm(request.POST or None, request=request)
    if request.method == "POST":
        if form.is_valid():
            user = form.save()
            request.session.pop(SESSION_VERIFIED_MOBILE, None)
            request.session.pop(SESSION_VERIFIED_AT, None)
            auth_login(request, user)
            messages.success(request, f"Account created — welcome, {user.first_name}!")
            return redirect("home")
        messages.error(request, "Please fix the errors below and try again.")
        # Keep whatever the customer had typed for mobile_number so the
        # verified-number step in the template doesn't silently reopen
        # on an unrelated validation error elsewhere in the form.
        verified_mobile = request.session.get(SESSION_VERIFIED_MOBILE, "")

    return render(request, "signup.html", {"form": form, "verified_mobile": verified_mobile})


def logout_view(request):
    auth_logout(request)
    messages.success(request, "You've been logged out.")
    return redirect("home")


@login_required
def account_view(request):
    """
    A customer's own profile page: Full Name / Mobile Number / Email,
    editable, with no order information on this page -- that lives at
    /my-orders/ (orders.views.my_orders) instead.

    Always operates on request.user's own CustomerProfile -- there is
    no way to pass in a different user id, so a logged-in customer can
    never view or edit another customer's data through this view.
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

    return render(request, "account.html", {"form": form, "profile": profile})


def cart(request):
    return render(request, "cart.html")
