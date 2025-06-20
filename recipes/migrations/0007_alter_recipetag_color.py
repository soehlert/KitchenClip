# Generated by Django 5.2.3 on 2025-06-12 05:21

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('recipes', '0006_alter_recipetag_color'),
    ]

    operations = [
        migrations.AlterField(
            model_name='recipetag',
            name='color',
            field=models.CharField(blank=True, help_text='HEX color code for this tag (e.g., #FF5733)', max_length=7),
        ),
    ]
