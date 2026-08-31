import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("menu", "0009_menuitem_is_selling_unit_tracking"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("orders", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="order",
            name="status",
            field=models.CharField(
                choices=[("confirmed", "Confirmed"), ("cancelled", "Cancelled")],
                default="confirmed",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="order",
            name="total_amount",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10),
        ),
        migrations.AddField(
            model_name="order",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True, default=django.utils.timezone.now),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name="order",
            name="user",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="orders",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.CreateModel(
            name="OrderItem",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("item_name", models.CharField(max_length=150)),
                ("price", models.DecimalField(decimal_places=2, max_digits=10)),
                ("quantity", models.PositiveIntegerField()),
                (
                    "menu_item",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="order_items",
                        to="menu.menuitem",
                    ),
                ),
                (
                    "order",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="items",
                        to="orders.order",
                    ),
                ),
            ],
        ),
    ]
