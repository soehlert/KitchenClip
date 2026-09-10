import json

import pytest
from django.urls import reverse
from django.utils import timezone

from recipes.models import MealPlan, Recipe, RecipeTag

# ==============================================================================
# Tier 1: Authentication Gate & Redirection (Unauthenticated Requests)
# ==============================================================================

@pytest.mark.django_db
@pytest.mark.parametrize("url_name,kwargs,method", [
    ("recipes:list_recipe", {}, "GET"),
    ("recipes:future_recipes", {}, "GET"),
    ("recipes:shared_recipe_list", {}, "GET"),
    ("recipes:add_recipe", {}, "GET"),
    ("recipes:manual_add", {}, "GET"),
    ("recipes:meal_plan", {}, "GET"),
    ("recipes:meal_plan_kiosk", {}, "GET"),
    ("recipes:tag_autocomplete", {}, "GET"),
    ("recipes:sidebar_pagination_api", {}, "GET"),
    ("recipes:search_recipes_api", {}, "GET"),
])
def test_unauthenticated_views_redirect_to_login(unauthenticated_client, url_name, kwargs, method):
    url = reverse(url_name, kwargs=kwargs)
    response = unauthenticated_client.get(url) if method == "GET" else unauthenticated_client.post(url)
    assert response.status_code == 302
    assert "/auth/login/" in response.url


@pytest.mark.django_db
def test_unauthenticated_recipe_detail_redirects(unauthenticated_client, recipe_factory):
    recipe = recipe_factory()
    url = reverse("recipes:detail_recipe", kwargs={"pk": recipe.pk})
    response = unauthenticated_client.get(url)
    assert response.status_code == 302
    assert "/auth/login/" in response.url


@pytest.mark.django_db
def test_unauthenticated_recipe_edit_redirects(unauthenticated_client, recipe_factory):
    recipe = recipe_factory()
    url = reverse("recipes:edit_recipe", kwargs={"pk": recipe.pk})
    response = unauthenticated_client.get(url)
    assert response.status_code == 302
    assert "/auth/login/" in response.url


@pytest.mark.django_db
def test_unauthenticated_recipe_delete_redirects(unauthenticated_client, recipe_factory):
    recipe = recipe_factory()
    url = reverse("recipes:delete_recipe", kwargs={"pk": recipe.pk})
    response = unauthenticated_client.get(url)
    assert response.status_code == 302
    assert "/auth/login/" in response.url


# ==============================================================================
# Tier 2: Cross-Tenant Isolation (Household A vs Household B)
# ==============================================================================

@pytest.mark.django_db
def test_recipe_list_scoped_to_household(client, secondary_client, test_household, secondary_household, recipe_factory):
    r1 = recipe_factory(household=test_household, title="Household A Pasta")
    r2 = recipe_factory(household=secondary_household, title="Household B Curry")

    resp_a = client.get(reverse("recipes:list_recipe"))
    assert resp_a.status_code == 200
    recipes_a = list(resp_a.context["recipes"])
    assert r1 in recipes_a
    assert r2 not in recipes_a

    resp_b = secondary_client.get(reverse("recipes:list_recipe"))
    assert resp_b.status_code == 200
    recipes_b = list(resp_b.context["recipes"])
    assert r2 in recipes_b
    assert r1 not in recipes_b


@pytest.mark.django_db
def test_future_recipes_scoped_to_household(client, secondary_client, test_household, secondary_household, recipe_factory):
    r1 = recipe_factory(household=test_household, title="Idea A", is_future=True)
    r2 = recipe_factory(household=secondary_household, title="Idea B", is_future=True)

    resp_a = client.get(reverse("recipes:future_recipes"))
    recipes_a = list(resp_a.context["recipes"])
    assert r1 in recipes_a
    assert r2 not in recipes_a

    resp_b = secondary_client.get(reverse("recipes:future_recipes"))
    recipes_b = list(resp_b.context["recipes"])
    assert r2 in recipes_b
    assert r1 not in recipes_b


@pytest.mark.django_db
def test_cross_household_private_recipe_detail_returns_404(secondary_client, test_household, recipe_factory):
    private_recipe = recipe_factory(household=test_household, title="Secret Family Recipe", is_shared=False)
    url = reverse("recipes:detail_recipe", kwargs={"pk": private_recipe.pk})
    response = secondary_client.get(url)
    assert response.status_code == 404


@pytest.mark.django_db
def test_cross_household_recipe_edit_returns_404(secondary_client, test_household, recipe_factory):
    recipe = recipe_factory(household=test_household, title="Original Title")
    url = reverse("recipes:edit_recipe", kwargs={"pk": recipe.pk})

    assert secondary_client.get(url).status_code == 404

    post_resp = secondary_client.post(url, {
        "title": "Hacked Title",
        "instructions": "Overwritten instructions",
        "prep_time": "10",
        "cook_time": "10",
        "total_time": "20",
        "servings": "4",
    })
    assert post_resp.status_code == 404
    recipe.refresh_from_db()
    assert recipe.title == "Original Title"


@pytest.mark.django_db
def test_cross_household_recipe_delete_returns_404(secondary_client, test_household, recipe_factory):
    recipe = recipe_factory(household=test_household, title="Protected Recipe")
    url = reverse("recipes:delete_recipe", kwargs={"pk": recipe.pk})
    response = secondary_client.post(url)
    assert response.status_code == 404
    assert Recipe.objects.filter(pk=recipe.pk).exists()


@pytest.mark.django_db
def test_cross_household_move_to_recipes_returns_404(secondary_client, test_household, recipe_factory):
    recipe = recipe_factory(household=test_household, is_future=True)
    url = reverse("recipes:move_to_recipes", kwargs={"pk": recipe.pk})
    response = secondary_client.post(url)
    assert response.status_code == 404
    recipe.refresh_from_db()
    assert recipe.is_future is True


@pytest.mark.django_db
def test_cross_household_toggle_menu_returns_404(secondary_client, test_household, recipe_factory):
    recipe = recipe_factory(household=test_household, is_on_menu=False)
    url = reverse("recipes:toggle_menu_status")
    response = secondary_client.post(url, data=json.dumps({"recipe_id": recipe.pk}), content_type="application/json")
    assert response.status_code == 404
    recipe.refresh_from_db()
    assert recipe.is_on_menu is False


@pytest.mark.django_db
def test_cross_household_search_recipes_api_isolation(client, secondary_client, test_household, secondary_household, recipe_factory):
    recipe_factory(household=test_household, title="Secret Lasagna")
    recipe_factory(household=secondary_household, title="Authentic Lasagna")

    url = reverse("recipes:search_recipes_api") + "?q=Lasagna"

    resp_a = client.get(url).json()
    assert len(resp_a["recipes"]) == 1
    assert resp_a["recipes"][0]["title"] == "Secret Lasagna"

    resp_b = secondary_client.get(url).json()
    assert len(resp_b["recipes"]) == 1
    assert resp_b["recipes"][0]["title"] == "Authentic Lasagna"


# ==============================================================================
# Tier 3: Same-Household Multi-User Sharing (Spouse / Partner Read & Write)
# ==============================================================================

@pytest.mark.django_db
def test_spouse_can_view_household_recipes(auth_client_factory, test_household, test_user, household_member_user, recipe_factory):
    recipe = recipe_factory(household=test_household, created_by=test_user, title="Family Chili")

    spouse_client = auth_client_factory(user=household_member_user, household=test_household, role="member")

    resp = spouse_client.get(reverse("recipes:list_recipe"))
    assert resp.status_code == 200
    assert recipe in resp.context["recipes"]

    detail_resp = spouse_client.get(reverse("recipes:detail_recipe", kwargs={"pk": recipe.pk}))
    assert detail_resp.status_code == 200
    assert detail_resp.context["recipe"].title == "Family Chili"


@pytest.mark.django_db
def test_spouse_can_edit_and_delete_household_recipe(auth_client_factory, test_household, test_user, household_member_user, recipe_factory):
    recipe = recipe_factory(household=test_household, created_by=test_user, title="Spouse Test Recipe")
    spouse_client = auth_client_factory(user=household_member_user, household=test_household, role="member")

    edit_url = reverse("recipes:edit_recipe", kwargs={"pk": recipe.pk})
    resp = spouse_client.post(edit_url, {
        "title": "Spouse Updated Recipe",
        "instructions": "New steps",
        "prep_time": "15",
        "cook_time": "20",
        "total_time": "35",
        "servings": "4",
    })
    assert resp.status_code == 302
    recipe.refresh_from_db()
    assert recipe.title == "Spouse Updated Recipe"

    del_url = reverse("recipes:delete_recipe", kwargs={"pk": recipe.pk})
    del_resp = spouse_client.post(del_url)
    assert del_resp.status_code == 302
    assert not Recipe.objects.filter(pk=recipe.pk).exists()


# ==============================================================================
# Tier 4: Meal Plan Scoping & Destruction Prevention
# ==============================================================================

@pytest.mark.django_db
def test_meal_plan_view_scoped_to_household(client, secondary_client, test_household, secondary_household, meal_plan_factory):
    today = timezone.now().date()
    meal_plan_factory(household=test_household, date=today, meal_type="DINNER", custom_meal="Household A Stew")
    meal_plan_factory(household=secondary_household, date=today, meal_type="DINNER", custom_meal="Household B Pizza")

    resp_a = client.get(reverse("recipes:meal_plan"))
    assert resp_a.status_code == 200
    weeks_a = resp_a.context["weeks"]
    today_slot_a = next(day for week in weeks_a for day in week if day["date"] == today)
    assert today_slot_a["dinner"].custom_meal == "Household A Stew"

    resp_b = secondary_client.get(reverse("recipes:meal_plan"))
    assert resp_b.status_code == 200
    weeks_b = resp_b.context["weeks"]
    today_slot_b = next(day for week in weeks_b for day in week if day["date"] == today)
    assert today_slot_b["dinner"].custom_meal == "Household B Pizza"


@pytest.mark.django_db
def test_update_meal_plan_delete_action_does_not_delete_other_household(client, secondary_client, test_household, secondary_household, meal_plan_factory):
    today = timezone.now().date()
    p1 = meal_plan_factory(household=test_household, date=today, meal_type="LUNCH", custom_meal="A Lunch")
    p2 = meal_plan_factory(household=secondary_household, date=today, meal_type="LUNCH", custom_meal="B Lunch")

    payload = {
        "date": today.isoformat(),
        "meal_type": "LUNCH",
        "action": "delete"
    }
    resp = secondary_client.post(reverse("recipes:update_meal_plan"), data=json.dumps(payload), content_type="application/json")
    assert resp.status_code == 200

    assert not MealPlan.objects.filter(pk=p2.pk).exists()
    assert MealPlan.objects.filter(pk=p1.pk).exists()


@pytest.mark.django_db
def test_update_meal_plan_cannot_attach_cross_household_private_recipe(secondary_client, test_household, recipe_factory):
    private_recipe = recipe_factory(household=test_household, title="Private Roast", is_shared=False)
    today = timezone.now().date().isoformat()
    payload = {
        "date": today,
        "meal_type": "DINNER",
        "recipe_id": private_recipe.pk,
    }
    resp = secondary_client.post(reverse("recipes:update_meal_plan"), data=json.dumps(payload), content_type="application/json")
    assert resp.status_code in [404, 400]


# ==============================================================================
# Tier 5: Automatic Household and Created-By Assignment
# ==============================================================================

@pytest.mark.django_db
def test_recipe_manual_create_assigns_household_and_creator(client, test_household, test_user):
    url = reverse("recipes:manual_add")
    data = {
        "title": "Auto Scoped Soup",
        "prep_time": "10",
        "cook_time": "20",
        "total_time": "30",
        "servings": "2",
        "ingredients_text": "1 can broth\n1 cup carrots",
        "instructions_text": "Simmer together.",
    }
    response = client.post(url, data)
    assert response.status_code == 302

    recipe = Recipe.objects.get(title="Auto Scoped Soup")
    assert recipe.household_id == test_household.id
    assert recipe.created_by_id == test_user.id


@pytest.mark.django_db
def test_update_meal_plan_assigns_household_and_creator(client, test_household, test_user):
    today = timezone.now().date().isoformat()
    payload = {
        "date": today,
        "meal_type": "DINNER",
        "custom_meal": "Taco Tuesday",
        "ready_at": "18:00"
    }
    url = reverse("recipes:update_meal_plan")
    response = client.post(url, data=json.dumps(payload), content_type="application/json")
    assert response.status_code == 200

    plan = MealPlan.objects.get(date=today, meal_type="DINNER", household=test_household)
    assert plan.household_id == test_household.id
    assert plan.created_by_id == test_user.id
    assert plan.custom_meal == "Taco Tuesday"


# ==============================================================================
# Tier 6: Recipe Tag Scoping & URL Duplicate Constraints
# ==============================================================================

@pytest.mark.django_db
def test_tag_autocomplete_scoped_to_household(client, secondary_client, test_household, secondary_household):
    RecipeTag.objects.create(household=test_household, name="quick-prep")
    RecipeTag.objects.create(household=secondary_household, name="quick-bake")

    url = reverse("recipes:tag_autocomplete") + "?q=quick"

    resp_a = client.get(url).json()
    tag_names_a = [t["name"] for t in resp_a]
    assert "quick-prep" in tag_names_a
    assert "quick-bake" not in tag_names_a

    resp_b = secondary_client.get(url).json()
    tag_names_b = [t["name"] for t in resp_b]
    assert "quick-bake" in tag_names_b
    assert "quick-prep" not in tag_names_b


@pytest.mark.django_db
def test_duplicate_url_allowed_across_households_blocked_within_same(client, secondary_client, test_household, secondary_household, recipe_factory):
    url_target = "https://example.com/unique-chili-recipe"

    r1 = recipe_factory(household=test_household, original_url=url_target, title="Chili A")
    r2 = recipe_factory(household=secondary_household, original_url=url_target, title="Chili B")
    assert r1.original_url == r2.original_url

    post_data = {
        "title": "Chili A Duplicate",
        "original_url": url_target,
        "prep_time": "10",
        "cook_time": "20",
        "total_time": "30",
        "servings": "4",
        "ingredients_text": "1 can beans",
        "instructions_text": "Heat beans.",
    }
    response = client.post(reverse("recipes:manual_add"), post_data)
    assert response.status_code == 200
    assert "form" in response.context
    assert "original_url" in response.context["form"].errors


@pytest.mark.django_db
def test_tag_slug_collision_resolution(client, test_household):
    """RecipeTag slug and case collisions are resolved smoothly without IntegrityError."""
    t1 = RecipeTag.objects.create(household=test_household, name="Comfort Food")
    assert t1.slug == "comfort-food"

    t2 = RecipeTag.get_or_create_for_household(test_household, "comfort-food")
    assert t2.pk == t1.pk

    t3 = RecipeTag.get_or_create_for_household(test_household, "COMFORT FOOD")
    assert t3.pk == t1.pk

    res = client.post(reverse("recipes:manual_add"), {
        "title": "Colliding Tag Dish",
        "tags": "comfort-food, Quick Prep",
        "ingredients_text": "1 potato",
        "instructions_text": "Bake potato.",
    }, follow=True)
    assert res.status_code == 200
    recipe = Recipe.objects.filter(household=test_household, title="Colliding Tag Dish").first()
    assert recipe is not None
    tag_names = set(recipe.tags.values_list("name", flat=True))
    assert "Comfort Food" in tag_names
    assert "Quick Prep" in tag_names

