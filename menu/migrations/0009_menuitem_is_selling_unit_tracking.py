import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("menu", "0008_rename_selling_unit_tracking_menuitem_disible_by_selling_unit"),
    ]

    operations = [
        migrations.RenameField(
            model_name="menuitem",
            old_name="disible_by_selling_unit",
            new_name="is_selling_unit_tracking",
        ),
        migrations.AddField(
            model_name="menuitem",
            name="selling_units_date",
            field=models.DateField(default=django.utils.timezone.localdate),
        ),
    ]
