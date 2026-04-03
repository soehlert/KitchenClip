from datetime import time

import pytest
from django.utils import timezone

from recipes.models import MealPlan, Recipe, RecipeTag


@pytest.mark.django_db
def test_recipe_creation():
    recipe = Recipe.objects.create(
        title="Spaghetti Bolognese",
        original_url="http://spaghetti.local",
        prep_time=15,
        cook_time=45
    )
    assert recipe.title == "Spaghetti Bolognese"
    assert recipe.total_time_display == "01:00"

@pytest.mark.django_db
def test_total_time_display_with_explicit_total():
    recipe = Recipe.objects.create(
        title="Quick Snack",
        original_url="http://snack.local",
        total_time=10
    )
    assert recipe.total_time_display == "00:10"

@pytest.mark.django_db
def test_meal_plan_creation():
    recipe = Recipe.objects.create(title="Dinner Roast", original_url="http://roast.local")
    plan = MealPlan.objects.create(
        date=timezone.now().date(),
        meal_type="DINNER",
        recipe=recipe,
        ready_at=time(18, 30)
    )
    assert plan.recipe.title == "Dinner Roast"
    assert plan.notification_sent is False

@pytest.mark.django_db
def test_tag_auto_color():
    tag = RecipeTag.objects.create(name="Vegetarian")
    assert tag.color is not None
    assert tag.color.startswith("#")
    assert tag.slug == "vegetarian"
