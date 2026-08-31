from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cart", "0002_cartitem_user"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="cartitem",
            constraint=models.UniqueConstraint(
                fields=("user", "menu_item"),
                name="unique_cart_item_per_user_menu_item",
            ),
        ),
    ]
