import pytest
from django.urls import reverse

from recipes.models import Ingredient, Recipe, RecipeIngredient, RecipeTag


@pytest.mark.django_db
class TestCrossHouseholdSharingVisibility:
    def test_shared_catalog_lists_shared_recipes(self, client, secondary_client, test_household, secondary_household):
        """Recipes with is_shared=True appear in the shared catalog for all authenticated households."""
        Recipe.objects.create(household=secondary_household, title="Public Chili", is_shared=True)
        Recipe.objects.create(household=secondary_household, title="Secret Cookies", is_shared=False)

        response = client.get(reverse('recipes:shared_recipe_list'))
        assert response.status_code == 200
        content = response.content.decode()
        assert "Public Chili" in content
        assert "Secret Cookies" not in content

    def test_shared_catalog_requires_authentication(self, unauthenticated_client):
        """Unauthenticated requests to shared catalog redirect to login."""
        response = unauthenticated_client.get(reverse('recipes:shared_recipe_list'))
        assert response.status_code == 302
        assert "/auth/login/" in response.url

    def test_view_shared_recipe_from_another_household_allowed(self, client, secondary_household):
        """Users can view the detail page of a shared recipe from another household."""
        r = Recipe.objects.create(household=secondary_household, title="Shared Pasta", is_shared=True)
        response = client.get(reverse('recipes:detail_recipe', kwargs={'pk': r.pk}))
        assert response.status_code == 200
        content = response.content.decode()
        assert "Shared Pasta" in content
        assert "Copy to My Recipes" in content
        assert "Edit" not in content

    def test_view_private_recipe_from_another_household_returns_404(self, client, secondary_household):
        """Users receive 404 when attempting to view a private recipe from another household."""
        r = Recipe.objects.create(household=secondary_household, title="Private Curry", is_shared=False)
        response = client.get(reverse('recipes:detail_recipe', kwargs={'pk': r.pk}))
        assert response.status_code == 404


@pytest.mark.django_db
class TestRecipeDeepCloning:
    def test_1_click_copy_success(self, client, test_user, test_household, secondary_household, secondary_user):
        """1-click copy creates a complete, independent clone in the active household."""
        source = Recipe.objects.create(
            household=secondary_household,
            created_by=secondary_user,
            title="Famous Stew",
            description="Family stew recipe",
            instructions="Simmer for 2 hours",
            prep_time=20,
            cook_time=120,
            total_time=140,
            servings=6,
            rating=5,
            user_notes="Secret family ingredient is cinnamon",
            is_shared=True,
            original_url="https://example.com/stew",
        )
        ing = Ingredient.objects.create(name="Beef Chuck")
        RecipeIngredient.objects.create(recipe=source, ingredient=ing, raw_text="2 lbs Beef Chuck", quantity="2", unit="lbs", order=0)
        source_tag = RecipeTag.objects.create(household=secondary_household, name="Comfort Food", color="#123456")
        source.tags.add(source_tag)

        response = client.post(reverse('recipes:copy_recipe', kwargs={'pk': source.pk}), follow=True)
        assert response.status_code == 200

        cloned = Recipe.objects.filter(household=test_household, title="Famous Stew").first()
        assert cloned is not None
        assert cloned.created_by == test_user
        assert cloned.is_shared is True
        assert cloned.instructions == "Simmer for 2 hours"
        assert cloned.prep_time == 20
        assert cloned.cook_time == 120
        assert cloned.user_notes == ""
        assert cloned.rating is None

        assert cloned.recipe_ingredients.count() == 1
        ri = cloned.recipe_ingredients.first()
        assert ri.ingredient == ing
        assert ri.quantity == "2"
        assert ri.unit == "lbs"

        assert cloned.tags.count() == 1
        cloned_tag = cloned.tags.first()
        assert cloned_tag.name == "Comfort Food"
        assert cloned_tag.household == test_household
        assert cloned_tag.pk != source_tag.pk

    def test_copy_private_recipe_rejected_404(self, client, secondary_household):
        """Attempting to copy a private recipe of another household returns 404."""
        source = Recipe.objects.create(household=secondary_household, title="Secret Pie", is_shared=False)
        response = client.post(reverse('recipes:copy_recipe', kwargs={'pk': source.pk}))
        assert response.status_code == 404

    def test_copy_duplicate_url_gracefully_handled(self, client, test_household, secondary_household):
        """If target household already has that URL, copy handles constraint without 500 error."""
        url = "https://example.com/unique-taco"
        Recipe.objects.create(household=test_household, title="My Taco", original_url=url)
        source = Recipe.objects.create(household=secondary_household, title="Their Taco", original_url=url, is_shared=True)

        response = client.post(reverse('recipes:copy_recipe', kwargs={'pk': source.pk}), follow=True)
        assert response.status_code == 200
        assert Recipe.objects.filter(household=test_household).count() == 2

    def test_copy_requires_post(self, client, secondary_household):
        """GET request to copy endpoint is rejected."""
        source = Recipe.objects.create(household=secondary_household, title="Shared Cake", is_shared=True)
        response = client.get(reverse('recipes:copy_recipe', kwargs={'pk': source.pk}))
        assert response.status_code == 405

    def test_copy_own_recipe_informs_and_redirects(self, client, test_household):
        """Copying an existing recipe from user's own household does not duplicate."""
        r = Recipe.objects.create(household=test_household, title="My Own Bread", is_shared=True)
        response = client.post(reverse('recipes:copy_recipe', kwargs={'pk': r.pk}), follow=True)
        assert response.status_code == 200
        assert Recipe.objects.filter(household=test_household, title="My Own Bread").count() == 1


@pytest.mark.django_db
def test_view_shared_recipe_hides_foreign_notes_and_rating(client, secondary_household, test_household, test_user):
    """Viewing a shared recipe from another household hides author's private notes and rating."""
    shared_recipe = Recipe.objects.create(
        household=secondary_household,
        title="Shared Pasta",
        is_shared=True,
        rating=5,
        user_notes="Super confidential family notes: add saffron.",
    )
    response = client.get(reverse('recipes:detail_recipe', kwargs={'pk': shared_recipe.pk}))
    assert response.status_code == 200
    content = response.content.decode()
    assert "Super confidential family notes: add saffron." not in content
    assert "Your Notes" not in content
    assert "Rating:" not in content

    # But author household can see their own notes and rating
    own_recipe = Recipe.objects.create(
        household=test_household,
        created_by=test_user,
        title="My Own Pasta",
        rating=4,
        user_notes="My private personal note.",
    )
    own_response = client.get(reverse('recipes:detail_recipe', kwargs={'pk': own_recipe.pk}))
    assert own_response.status_code == 200
    own_content = own_response.content.decode()
    assert "My private personal note." in own_content
    assert "Your Notes" in own_content
    assert "Rating:" in own_content


@pytest.mark.django_db
def test_instruction_steps_xss_protection(client, secondary_household):
    """Instruction steps with HTML/script characters must be safely escaped."""
    xss_recipe = Recipe.objects.create(
        household=secondary_household,
        title="XSS Test Dish",
        is_shared=True,
        instructions="<script>alert('pwned')</script>\n<img src=x onerror=alert(1)>",
    )
    response = client.get(reverse('recipes:detail_recipe', kwargs={'pk': xss_recipe.pk}))
    assert response.status_code == 200
    content = response.content.decode()
    assert "<script>alert('pwned')</script>" not in content
    assert "<img src=x onerror=alert(1)>" not in content
    assert "&lt;script&gt;" in content
    assert "&lt;img" in content

