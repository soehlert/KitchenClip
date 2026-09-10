"""Milestone M3 Empirical Challenge Test Suite (Challenger 2).

Tests:
1. Cross-household recipe sharing, catalog filtering, detail view permissions.
2. 1-click cloning fidelity, deep clone of ingredients and ordering, tag scoping,
   URL collision disambiguation, and privacy guarantees.
3. URL normalization variants (schemes, default ports, www, trailing slashes,
   tracking params, sorted query params, fragment stripping).
4. Duplicate URL detection banner, same-household form validation rejection,
   copy-duplicate action, and force-scrape bypass.
5. Adversarial security/authorization challenge on copy-duplicate endpoint (IDOR probe).
"""

from unittest.mock import MagicMock, patch

import pytest
from django.urls import reverse

from recipes.models import Ingredient, Recipe, RecipeIngredient, RecipeTag
from recipes.url_utils import find_recipe_by_url, normalize_url


@pytest.mark.django_db
class TestURLNormalizationEdgeCases:
    """Empirical challenge on URL normalization and variant generation."""

    def test_normalization_matrix(self):
        cases = [
            # (input_url, expected_normalized)
            ("http://EXAMPLE.com/recipes/pasta", "https://example.com/recipes/pasta"),
            ("https://www.example.com:443/recipes/pasta/", "https://example.com/recipes/pasta"),
            ("http://www.example.com:80/recipes/pasta///", "https://example.com/recipes/pasta"),
            ("https://example.com/recipes/pasta?utm_source=twitter&utm_medium=social", "https://example.com/recipes/pasta"),
            ("https://example.com/recipes/pasta?fbclid=12345&gclid=67890", "https://example.com/recipes/pasta"),
            ("https://example.com/recipes/pasta?b=2&a=1", "https://example.com/recipes/pasta?a=1&b=2"),
            ("https://example.com/recipes/pasta?UTM_SOURCE=ad&valid=yes", "https://example.com/recipes/pasta?valid=yes"),
            ("https://example.com/recipes/pasta#instructions", "https://example.com/recipes/pasta"),
            ("  https://example.com/recipes/pasta  ", "https://example.com/recipes/pasta"),
        ]
        for raw, expected in cases:
            assert normalize_url(raw) == expected, f"Failed for {raw}: got {normalize_url(raw)}"

    def test_cross_household_lookup_variants(self, secondary_household):
        """Verify find_recipe_by_url matches across various URL representations."""
        recipe = Recipe.objects.create(
            household=secondary_household,
            original_url="https://example.com/recipes/brownies",
            title="Neighbor Brownies",
        )

        test_variants = [
            "http://example.com/recipes/brownies",
            "https://www.example.com/recipes/brownies",
            "http://www.example.com/recipes/brownies/",
            "https://example.com/recipes/brownies/",
            "https://example.com/recipes/brownies?utm_source=google&utm_campaign=summer",
            "https://example.com/recipes/brownies#section-2",
        ]

        for variant in test_variants:
            found = find_recipe_by_url(variant, exclude_household=None)
            assert found is not None, f"Variant not found: {variant}"
            assert found.pk == recipe.pk

    def test_root_domain_trailing_slash_variant_lookup(self, secondary_household):
        """Verify that a recipe saved with https://example.com/ is matched when entering https://example.com."""
        recipe = Recipe.objects.create(
            household=secondary_household,
            original_url="https://example.com/",
            title="Root URL Dish",
        )
        found = find_recipe_by_url("https://example.com", exclude_household=None)
        assert found is not None, "Failed to match root domain URL across trailing slash boundary"
        assert found.pk == recipe.pk


@pytest.mark.django_db
class TestCrossHouseholdSharingCatalogAndAccess:
    """Empirical challenge on shared recipes catalog and detail page access controls."""

    def test_shared_catalog_excludes_private_and_future(self, client, secondary_household):
        """Catalog must only show is_shared=True AND is_future=False recipes."""
        r_shared = Recipe.objects.create(
            household=secondary_household, title="Public Shared Soup", is_shared=True, is_future=False
        )
        r_private = Recipe.objects.create(
            household=secondary_household, title="Private Secret Soup", is_shared=False, is_future=False
        )
        r_future_shared = Recipe.objects.create(
            household=secondary_household, title="Future Public Idea", is_shared=True, is_future=True
        )

        response = client.get(reverse("recipes:shared_recipe_list"))
        assert response.status_code == 200
        content = response.content.decode()
        assert r_shared.title in content
        assert r_private.title not in content
        assert r_future_shared.title not in content

    def test_shared_catalog_search_filtering(self, client, secondary_household):
        """Search query matches title, description, or ingredients in shared catalog only."""
        r1 = Recipe.objects.create(
            household=secondary_household, title="Avocado Toast", description="Simple breakfast", is_shared=True
        )
        r2 = Recipe.objects.create(
            household=secondary_household, title="Pancakes", description="Fluffy breakfast", is_shared=True
        )
        ing = Ingredient.objects.create(name="Blueberry")
        RecipeIngredient.objects.create(recipe=r2, ingredient=ing, raw_text="1 cup blueberries", quantity="1", unit="cup", order=0)

        # Search by title
        res = client.get(reverse("recipes:shared_recipe_list"), {"search": "Avocado"})
        assert r1.title in res.content.decode()
        assert r2.title not in res.content.decode()

        # Search by ingredient
        res = client.get(reverse("recipes:shared_recipe_list"), {"search": "Blueberry"})
        assert r2.title in res.content.decode()
        assert r1.title not in res.content.decode()

    def test_shared_catalog_time_range_filter(self, client, secondary_household):
        """Total time range filters properly constrain shared catalog."""
        r_quick = Recipe.objects.create(household=secondary_household, title="Quick Snack", total_time=15, is_shared=True)
        r_med = Recipe.objects.create(household=secondary_household, title="Medium Dinner", total_time=35, is_shared=True)
        r_long = Recipe.objects.create(household=secondary_household, title="Slow Roast", total_time=120, is_shared=True)

        res_quick = client.get(reverse("recipes:shared_recipe_list"), {"time_range": "0-20"})
        content = res_quick.content.decode()
        assert r_quick.title in content
        assert r_med.title not in content
        assert r_long.title not in content

        res_long = client.get(reverse("recipes:shared_recipe_list"), {"time_range": "60+"})
        content = res_long.content.decode()
        assert r_long.title in content
        assert r_quick.title not in content
        assert r_med.title not in content

    def test_detail_view_permissions_and_template_controls(self, client, test_household, secondary_household):
        """Shared recipes from another household display Copy button and hide Edit/Delete."""
        foreign_shared = Recipe.objects.create(
            household=secondary_household, title="Foreign Shared Dish", is_shared=True
        )
        own_recipe = Recipe.objects.create(
            household=test_household, title="Our Own Dish", is_shared=True
        )

        # Foreign shared view
        res = client.get(reverse("recipes:detail_recipe", kwargs={"pk": foreign_shared.pk}))
        assert res.status_code == 200
        content = res.content.decode()
        assert f"Shared by {secondary_household.name}" in content or f"Shared by <strong>{secondary_household.name}</strong>" in content
        assert "Copy to My Household" in content
        assert reverse("recipes:edit_recipe", kwargs={"pk": foreign_shared.pk}) not in content
        assert reverse("recipes:delete_recipe", kwargs={"pk": foreign_shared.pk}) not in content

        # Own recipe view
        res = client.get(reverse("recipes:detail_recipe", kwargs={"pk": own_recipe.pk}))
        assert res.status_code == 200
        content = res.content.decode()
        assert "Shared" in content
        assert "Copy to My Household" not in content
        assert reverse("recipes:edit_recipe", kwargs={"pk": own_recipe.pk}) in content
        assert reverse("recipes:delete_recipe", kwargs={"pk": own_recipe.pk}) in content


@pytest.mark.django_db
class TestCloningFidelityAndEdgeCases:
    """Empirical challenge on 1-click deep cloning fidelity, ingredients, tags, and privacy."""

    def test_ingredient_ordering_and_fidelity(self, client, test_household, secondary_household):
        """Ingredients must preserve exact order, quantity, unit, preparation, and raw text."""
        source = Recipe.objects.create(
            household=secondary_household,
            title="Complex Lasagna",
            description="Multi-layer lasagna",
            instructions="Layer and bake.",
            is_shared=True,
            original_url="https://example.com/lasagna",
        )
        raw_data = [
            ("Ricotta Cheese", "15", "oz", "drained", "15 oz Ricotta Cheese, drained", 0),
            ("Lasagna Noodles", "12", "sheets", "boiled", "12 sheets Lasagna Noodles, boiled", 1),
            ("Ground Beef", "1", "lb", "browned", "1 lb Ground Beef, browned", 2),
            ("Marinara Sauce", "24", "oz", "", "24 oz Marinara Sauce", 3),
            ("Mozzarella", "2", "cups", "shredded", "2 cups Mozzarella, shredded", 4),
        ]
        for name, qty, unit, prep, raw, order in raw_data:
            ing, _ = Ingredient.objects.get_or_create(name=name)
            RecipeIngredient.objects.create(
                recipe=source,
                ingredient=ing,
                raw_text=raw,
                quantity=qty,
                unit=unit,
                preparation=prep,
                order=order,
            )

        res = client.post(reverse("recipes:copy_recipe", kwargs={"pk": source.pk}), follow=True)
        assert res.status_code == 200

        clone = Recipe.objects.filter(household=test_household, title="Complex Lasagna").first()
        assert clone is not None
        cloned_ings = list(clone.recipe_ingredients.order_by("order"))
        assert len(cloned_ings) == len(raw_data)

        for cloned_ri, expected in zip(cloned_ings, raw_data):
            exp_name, exp_qty, exp_unit, exp_prep, exp_raw, exp_order = expected
            assert cloned_ri.ingredient.name == exp_name
            assert cloned_ri.quantity == exp_qty
            assert cloned_ri.unit == exp_unit
            assert cloned_ri.preparation == exp_prep
            assert cloned_ri.raw_text == exp_raw
            assert cloned_ri.order == exp_order

    def test_tag_scoping_and_reuse_on_clone(self, client, test_household, secondary_household):
        """Cloning a recipe with tags reuses existing household tags if present or creates scoped ones."""
        source = Recipe.objects.create(
            household=secondary_household, title="Tagged Curry", is_shared=True
        )
        tag_shared_name = RecipeTag.objects.create(
            household=secondary_household, name="Dinner", color="#111111"
        )
        tag_unique = RecipeTag.objects.create(
            household=secondary_household, name="Spicy", color="#222222"
        )
        source.tags.add(tag_shared_name, tag_unique)

        # Target household already has its own 'Dinner' tag
        target_dinner_tag = RecipeTag.objects.create(
            household=test_household, name="Dinner", color="#999999"
        )

        res = client.post(reverse("recipes:copy_recipe", kwargs={"pk": source.pk}), follow=True)
        assert res.status_code == 200

        clone = Recipe.objects.filter(household=test_household, title="Tagged Curry").first()
        assert clone is not None

        clone_tag_names = set(clone.tags.values_list("name", flat=True))
        assert clone_tag_names == {"Dinner", "Spicy"}

        # Verify Dinner tag used target household's tag, not source's
        dinner_tag = clone.tags.get(name="Dinner")
        assert dinner_tag.pk == target_dinner_tag.pk
        assert dinner_tag.household == test_household

        # Verify Spicy tag was created in target household
        spicy_tag = clone.tags.get(name="Spicy")
        assert spicy_tag.household == test_household
        assert spicy_tag.pk != tag_unique.pk

    def test_url_collision_disambiguation(self, client, test_household, secondary_household):
        """Cloning when target household already has identical original_url appends #copy-<hex>."""
        url = "https://example.com/unique-pizza"
        Recipe.objects.create(household=test_household, original_url=url, title="Our Pizza")
        source = Recipe.objects.create(
            household=secondary_household, original_url=url, title="Their Pizza", is_shared=True
        )

        res = client.post(reverse("recipes:copy_recipe", kwargs={"pk": source.pk}), follow=True)
        assert res.status_code == 200

        clones = Recipe.objects.filter(household=test_household, title="Their Pizza")
        assert clones.count() == 1
        cloned_pizza = clones.first()
        assert cloned_pizza.original_url.startswith("https://example.com/unique-pizza#copy-")

    def test_privacy_guarantee_no_notes_or_rating_leaked(self, client, test_household, secondary_household):
        """Cross-household clone must never copy private source user_notes or rating."""
        source = Recipe.objects.create(
            household=secondary_household,
            title="Classified Brownies",
            user_notes="Extremely confidential family secret note!",
            rating=5,
            is_shared=True,
        )

        res = client.post(reverse("recipes:copy_recipe", kwargs={"pk": source.pk}), follow=True)
        assert res.status_code == 200

        clone = Recipe.objects.filter(household=test_household, title="Classified Brownies").first()
        assert clone is not None
        assert clone.user_notes == ""
        assert clone.rating is None


@pytest.mark.django_db
class TestDuplicateURLScrapingAlertAndForceScrape:
    """Empirical challenge on duplicate URL alert banner, copy, and force-scrape."""

    def test_same_household_duplicate_rejected_clean_validation(self, client, test_household):
        """Entering an already saved URL in own household returns clean form error, no crash."""
        Recipe.objects.create(
            household=test_household, original_url="https://example.com/tacos", title="Saved Tacos"
        )

        res = client.post(reverse("recipes:add_recipe"), {
            "original_url": "https://www.example.com/tacos/",
        })
        assert res.status_code == 200
        assert "form" in res.context
        assert "original_url" in res.context["form"].errors
        assert "already in your household" in str(res.context["form"].errors["original_url"])

    def test_cross_household_duplicate_banner_and_force_scrape(self, client, test_household, secondary_household):
        """Cross-household duplicate displays banner without scraping; force_scrape=1 overrides."""
        neighbor_recipe = Recipe.objects.create(
            household=secondary_household,
            original_url="https://example.com/soup",
            title="Neighbor's Creamy Soup",
            total_time=45,
            is_shared=True,
        )

        # 1. Normal submission -> intercepts and renders duplicate alert banner
        with patch("recipes.views.ParserRegistry.get_parser") as mock_parser:
            res = client.post(reverse("recipes:add_recipe"), {
                "original_url": "https://www.example.com/soup/",
            })
            assert res.status_code == 200
            assert res.context.get("duplicate_detected") is True
            assert res.context.get("duplicate_recipe").pk == neighbor_recipe.pk
            mock_parser.assert_not_called()

        # Check template rendered banner
        import html
        content = html.unescape(res.content.decode())
        assert "Recipe Already Saved on KitchenClip" in content
        assert "Neighbor's Creamy Soup" in content
        assert "btn-copy-existing" in content
        assert "btn-force-scrape" in content

        # 2. Force scrape submission -> bypasses duplicate detection and scrapes
        mock_instance = MagicMock()
        mock_instance.title = "Fresh Scraped Soup"
        mock_instance.description = "Freshly scraped"
        mock_instance.prep_time = 10
        mock_instance.cook_time = 35
        mock_instance.total_time = 45
        mock_instance.servings = 4
        mock_instance.instructions = "Heat and serve."
        mock_instance.image_url = ""
        mock_instance.ingredients = ["2 cups broth"]

        with patch("recipes.views.ParserRegistry.get_parser", return_value=mock_instance):
            res_force = client.post(reverse("recipes:add_recipe"), {
                "original_url": "https://example.com/soup",
                "force_scrape": "1",
            }, follow=True)
            assert res_force.status_code == 200

        own_scraped = Recipe.objects.filter(household=test_household, title="Fresh Scraped Soup").first()
        assert own_scraped is not None
        assert own_scraped.original_url == "https://example.com/soup"


@pytest.mark.django_db
class TestSecurityAndAuthorizationEdgeCases:
    """Empirical challenge on authorization constraints and attack surfaces."""

    def test_copy_endpoint_rejects_foreign_private_recipe(self, client, secondary_household):
        """POST /recipes/<pk>/copy/ must return 404 for a private recipe from another household."""
        private_recipe = Recipe.objects.create(
            household=secondary_household,
            title="Private Family Secret",
            instructions="Strictly confidential",
            is_shared=False,
        )
        res = client.post(reverse("recipes:copy_recipe", kwargs={"pk": private_recipe.pk}))
        assert res.status_code == 404

    def test_idor_probe_on_copy_duplicate_endpoint(self, client, test_household, secondary_household):
        """Probe copy-duplicate endpoint for unauthorized cross-household cloning of private recipes.
        
        If a private recipe has NO original_url (e.g. Grandma's secret family recipe created manually),
        can an unauthorized user from another household clone it via /recipes/<pk>/copy-duplicate/?
        """
        secret_recipe = Recipe.objects.create(
            household=secondary_household,
            title="Grandmas Top Secret Family Recipe",
            instructions="Secret family sauce steps",
            original_url=None,
            is_shared=False,
        )
        ing = Ingredient.objects.create(name="Secret Spice")
        RecipeIngredient.objects.create(
            recipe=secret_recipe, ingredient=ing, raw_text="1 tsp Secret Spice", quantity="1", unit="tsp", order=0
        )

        res = client.post(reverse("recipes:copy_duplicate", kwargs={"pk": secret_recipe.pk}))
        
        # Check whether the private recipe was unauthorizedly cloned
        stolen = Recipe.objects.filter(household=test_household, title="Grandmas Top Secret Family Recipe").first()
        
        # We record the empirical behavior: does copy_duplicate_recipe allow cloning private recipes with no original_url?
        if stolen is not None:
            pytest.fail(
                "SECURITY FINDING: copy_duplicate_recipe allows cloning private foreign recipes "
                f"without an original_url (IDOR on /recipes/{secret_recipe.pk}/copy-duplicate/)!"
            )
        else:
            assert res.status_code in (403, 404)
