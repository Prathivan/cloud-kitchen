from django.urls import path
from . import views


urlpatterns = [
    path(
        "my-orders/",
        views.my_orders,
        name="my_orders"
    ),
    path(
        "checkout/",
        views.checkout,
        name="checkout"
    ),
]