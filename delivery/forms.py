from django import forms

from .models import DeliveryAddress


class DeliveryAddressForm(forms.ModelForm):
    """
    Backs both "add address" and "edit address". latitude/longitude/
    google_place_id/formatted_address are rendered as hidden inputs
    that templates/delivery_address_form.html's Google Maps JS fills
    in as the customer searches/drags the pin -- see that template for
    the JS side of this contract.
    """

    class Meta:
        model = DeliveryAddress
        fields = [
            "address_label", "full_name", "phone",
            "address_line_1", "address_line_2", "building", "apartment", "floor",
            "street", "area", "city", "state", "country", "postal_code",
            "delivery_instructions",
            "latitude", "longitude", "google_place_id", "formatted_address",
            "is_default",
        ]
        widgets = {
            "address_label": forms.RadioSelect(),
            "delivery_instructions": forms.Textarea(attrs={"rows": 3}),
            "latitude": forms.HiddenInput(),
            "longitude": forms.HiddenInput(),
            "google_place_id": forms.HiddenInput(),
            "formatted_address": forms.HiddenInput(),
        }

    def clean(self):
        cleaned_data = super().clean()
        latitude = cleaned_data.get("latitude")
        longitude = cleaned_data.get("longitude")
        if (latitude is None) != (longitude is None):
            self.add_error(None, "Both latitude and longitude are required together, or leave both empty.")
        return cleaned_data
