import pytest
from django.urls import reverse

from recipes.models import Household, Recipe, UserProfile


@pytest.mark.django_db
class TestSharedCatalogDeduplication:
    def test_shared_catalog_deduplicates_same_url_across_households(self, client, test_household, secondary_household):
        """When multiple households have the same recipe URL, only one appears in shared catalog."""
        url = "https://example.com/tasty-soup"
        Recipe.objects.create(
            household=secondary_household,
            title="Tasty Soup (Neighbor's Copy)",
            original_url=url,
            is_shared=True,
            is_future=False,
        )
        Recipe.objects.create(
            household=test_household,
            title="Tasty Soup (Our Copy)",
            original_url=f"{url}#copy-ab12",
            is_shared=True,
            is_future=False,
        )

        response = client.get(reverse("recipes:shared_recipe_list"))
        assert response.status_code == 200
        content = response.content.decode()

        # The viewer's household copy should be displayed
        assert "Tasty Soup (Our Copy)" in content
        assert "Tasty Soup (Neighbor's Copy)" not in content
        assert "Already saved" in content
        assert "Copy to My Recipes" not in content

        # Check total count reflects 1 distinct recipe, not 2
        assert response.context["page_obj"].paginator.count == 1

    def test_shared_catalog_prioritizes_viewer_household_copy(
        self, client, secondary_client, test_household, secondary_household
    ):
        """Each household sees its own copy prioritized as 'Already saved'."""
        url = "https://example.com/honey-garlic-chicken"
        r_sec = Recipe.objects.create(
            household=secondary_household,
            title="Honey Garlic Chicken",
            original_url=url,
            is_shared=True,
            is_future=False,
        )
        r_own = Recipe.objects.create(
            household=test_household,
            title="Honey Garlic Chicken",
            original_url=url,
            is_shared=True,
            is_future=False,
        )

        # Primary household viewing
        resp_primary = client.get(reverse("recipes:shared_recipe_list"))
        recipes_primary = list(resp_primary.context["recipes"])
        assert len(recipes_primary) == 1
        assert recipes_primary[0].pk == r_own.pk
        assert "Already saved" in resp_primary.content.decode()

        # Secondary household viewing
        resp_sec = secondary_client.get(reverse("recipes:shared_recipe_list"))
        recipes_sec = list(resp_sec.context["recipes"])
        assert len(recipes_sec) == 1
        assert recipes_sec[0].pk == r_sec.pk
        assert "Already saved" in resp_sec.content.decode()

    def test_shared_catalog_non_owning_household_sees_single_copy_to_my_recipes(
        self, unauthenticated_client, test_household, secondary_household, django_user_model
    ):
        """A 3rd household that does not own the recipe sees exactly one card with 'Copy to My Recipes'."""
        third_hh = Household.objects.create(name="Third Household")
        third_user = django_user_model.objects.create_user(username="third@example.com")
        UserProfile.objects.create(user=third_user, household=third_hh, role="admin")

        url = "https://example.com/honey-garlic-chicken"
        Recipe.objects.create(
            household=secondary_household,
            title="Honey Garlic Chicken",
            original_url=url,
            is_shared=True,
            is_future=False,
        )
        Recipe.objects.create(
            household=test_household,
            title="Honey Garlic Chicken",
            original_url=url,
            is_shared=True,
            is_future=False,
        )

        unauthenticated_client.force_login(third_user)
        resp = unauthenticated_client.get(reverse("recipes:shared_recipe_list"))
        assert resp.status_code == 200
        recipes = list(resp.context["recipes"])
        assert len(recipes) == 1
        assert "Copy to My Recipes" in resp.content.decode()
        assert "Already saved" not in resp.content.decode()

    def test_shared_catalog_deduplicates_manual_recipes_by_title(
        self, client, test_household, secondary_household
    ):
        """Manual recipes without external URLs are deduplicated by title (case-insensitive)."""
        Recipe.objects.create(
            household=secondary_household,
            title="Grandma's Apple Pie",
            original_url=None,
            is_shared=True,
            is_future=False,
        )
        Recipe.objects.create(
            household=test_household,
            title="grandma's apple pie",
            original_url="",
            is_shared=True,
            is_future=False,
        )

        response = client.get(reverse("recipes:shared_recipe_list"))
        assert response.status_code == 200
        recipes = list(response.context["recipes"])
        assert len(recipes) == 1
        # Own household's copy should be prioritized
        assert recipes[0].household == test_household
        assert "Already saved" in response.content.decode()
