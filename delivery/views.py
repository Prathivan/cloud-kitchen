from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import DeliveryAddressForm
from .models import DeliveryAddress


def _owned_address_or_404(request, pk):
    """
    Every view below MUST use this (never DeliveryAddress.objects.get)
    to fetch an address by id -- filtering by user=request.user here is
    what actually prevents one customer from viewing, editing, deleting,
    or defaulting another customer's address. A 404 (not a 403) is
    returned for someone else's address, so its existence isn't leaked
    either.
    """
    return get_object_or_404(DeliveryAddress, pk=pk, user=request.user)


@login_required
def address_list(request):
    addresses = DeliveryAddress.objects.filter(user=request.user)
    next_url = request.GET.get("next", "")
    return render(request, "delivery_addresses.html", {"addresses": addresses, "next_url": next_url})


@login_required
def address_add(request):
    next_url = request.GET.get("next") or request.POST.get("next", "")
    if request.method == "POST":
        form = DeliveryAddressForm(request.POST)
        if form.is_valid():
            address = form.save(commit=False)
            address.user = request.user
            # A customer's very first address is always their default --
            # there would otherwise be no default at all to preselect at
            # checkout.
            if not DeliveryAddress.objects.filter(user=request.user).exists():
                address.is_default = True
            address.full_clean()
            address.save()
            messages.success(request, "Delivery address saved.")
            return redirect(next_url or "address_list")
    else:
        form = DeliveryAddressForm(initial={"country": "India"})

    return render(
        request,
        "delivery_address_form.html",
        {
            "form": form,
            "is_edit": False,
            "next_url": next_url,
            "google_maps_api_key": settings.GOOGLE_MAPS_API_KEY,
        },
    )


@login_required
def address_edit(request, pk):
    address = _owned_address_or_404(request, pk)
    next_url = request.GET.get("next") or request.POST.get("next", "")
    if request.method == "POST":
        form = DeliveryAddressForm(request.POST, instance=address)
        if form.is_valid():
            updated = form.save(commit=False)
            updated.full_clean()
            updated.save()
            messages.success(request, "Delivery address updated.")
            return redirect(next_url or "address_list")
    else:
        form = DeliveryAddressForm(instance=address)

    return render(
        request,
        "delivery_address_form.html",
        {
            "form": form,
            "is_edit": True,
            "address": address,
            "next_url": next_url,
            "google_maps_api_key": settings.GOOGLE_MAPS_API_KEY,
        },
    )


@login_required
@require_POST
def address_delete(request, pk):
    address = _owned_address_or_404(request, pk)
    was_default = address.is_default
    address.delete()
    # If the deleted address was the default, promote the next most
    # recently updated remaining address so the customer always has a
    # default to fall back on at checkout, rather than silently ending
    # up with none.
    if was_default:
        fallback = DeliveryAddress.objects.filter(user=request.user).first()
        if fallback:
            fallback.is_default = True
            fallback.save(update_fields=["is_default"])
    messages.success(request, "Delivery address deleted.")
    return redirect("address_list")


@login_required
@require_POST
def address_set_default(request, pk):
    address = _owned_address_or_404(request, pk)
    address.is_default = True
    address.save(update_fields=["is_default"])
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"ok": True, "default_address_id": address.id})
    messages.success(request, "Default address updated.")
    return redirect("address_list")
