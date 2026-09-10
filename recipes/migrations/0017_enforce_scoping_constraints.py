from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("recipes", "0016_populate_primary_household_and_data"),
    ]

    operations = [
        # 1. Enforce Recipe household NOT NULL
        migrations.AlterField(
            model_name="recipe",
            name="household",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="recipes", to="recipes.household"),
        ),
        # 2. Add scoped UniqueConstraint on Recipe (household + original_url)
        migrations.AddConstraint(
            model_name="recipe",
            constraint=models.UniqueConstraint(
                condition=models.Q(models.Q(("original_url__isnull", False)), models.Q(("original_url", ""), _negated=True)),
                fields=("household", "original_url"),
                name="unique_recipe_original_url_per_household"
            ),
        ),
        # 3. Enforce MealPlan household NOT NULL and unique_together
        migrations.AlterField(
            model_name="mealplan",
            name="household",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="meal_plans", to="recipes.household"),
        ),
        migrations.AlterUniqueTogether(
            name="mealplan",
            unique_together={("household", "date", "meal_type")},
        ),
        # 4. Add scoped UniqueConstraints on RecipeTag
        migrations.AddConstraint(
            model_name="recipetag",
            constraint=models.UniqueConstraint(
                fields=("household", "name"),
                name="unique_household_tag_name"
            ),
        ),
        migrations.AddConstraint(
            model_name="recipetag",
            constraint=models.UniqueConstraint(
                fields=("household", "slug"),
                name="unique_household_tag_slug"
            ),
        ),
    ]
