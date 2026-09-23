"""Milestone M4 Empirical Challenge Test Suite (teamwork_preview_challenger_m4_1).

Adversarial stress harness rigorously verifying:
1. Same-household multi-user sharing (recipes, weekly meal plans, synchronization, permissions).
2. Cross-household multi-tenancy isolation (HTTP 404 on private detail, edit, delete, copy, search isolation, meal plans).
3. Cross-household recipe sharing (catalog browsing, privacy-preserving suppression of author notes/ratings, deep 1-click cloning, independent mutation, revocation).
4. Duplicate URL scraping detection (cross-household alert banner, copy existing action, force scrape action, same-household form validation rejection, URL normalization, anti-IDOR).
"""

import datetime
import json
import secrets
from unittest.mock import MagicMock, patch

import pytest
from django.urls import reverse
from django.utils import timezone

from recipes.models import Ingredient, MealPlan, Recipe, RecipeIngredient, RecipeTag


@pytest.fixture
def spouse_client(auth_client_factory, household_member_user, test_household):
    """Authenticated client for a secondary member (e.g. spouse) within the primary household."""
    return auth_client_factory(user=household_member_user, household=test_household, role="member")


# =====================================================================
# 1. SAME-HOUSEHOLD MULTI-USER SHARING & PERMISSIONS
# =====================================================================

@pytest.mark.django_db
class TestSameHouseholdSharingEmpirical:
    """Empirical stress tests verifying that members of the same household share recipes and meal plans."""

    def test_spouse_sees_recipes_in_list_and_detail(self, client, spouse_client, test_household, test_user):
        """Spouse in same household immediately sees partner's recipe in list and detail view with full metadata."""
        recipe = Recipe.objects.create(
            household=test_household,
            created_by=test_user,
            title="Spouse Sunday Roast",
            instructions="Roast at 350 for 2 hours.",
            user_notes="Spouse 1 confidential secret gravy note",
            rating=5,
            is_shared=False,
            is_future=False,
        )

        # Spouse visits recipe catalog
        resp_list = spouse_client.get(reverse("recipes:list_recipe"))
        assert resp_list.status_code == 200
        assert "Spouse Sunday Roast" in resp_list.content.decode()

        # Spouse visits recipe detail
        resp_detail = spouse_client.get(reverse("recipes:detail_recipe", kwargs={"pk": recipe.pk}))
        assert resp_detail.status_code == 200
        content = resp_detail.content.decode()
        assert "Spouse Sunday Roast" in content
        # Because spouse is in the same household, is_own_recipe is True and notes are visible!
        assert resp_detail.context["is_own_recipe"] is True
        assert "Spouse 1 confidential secret gravy note" in content
        assert "Your Notes" in content

    def test_spouse_can_edit_and_delete_household_recipe(self, spouse_client, test_household, test_user):
        """Spouse in same household has collaborative write/delete access to household recipes."""
        recipe = Recipe.objects.create(
            household=test_household,
            created_by=test_user,
            title="Initial Title by User 1",
            instructions="Step 1: Chop veggies.",
            user_notes="Initial note",
            rating=3,
        )

        # Spouse edits the recipe
        edit_url = reverse("recipes:edit_recipe", kwargs={"pk": recipe.pk})
        resp_get = spouse_client.get(edit_url)
        assert resp_get.status_code == 200

        edit_payload = {
            "title": "Edited Title by Spouse",
            "instructions": "Step 1: Chop veggies.\nStep 2: Saute.",
            "user_notes": "Updated note by spouse",
            "rating": "4",
            "tags": "",
            "ingredients_text": "1 cup carrots\n2 tbsp olive oil",
        }
        resp_post = spouse_client.post(edit_url, data=edit_payload)
        assert resp_post.status_code in (302, 200)

        recipe.refresh_from_db()
        assert recipe.title == "Edited Title by Spouse"
        assert recipe.user_notes == "Updated note by spouse"
        assert recipe.rating == 4

        # Spouse deletes the recipe
        delete_url = reverse("recipes:delete_recipe", kwargs={"pk": recipe.pk})
        resp_del = spouse_client.post(delete_url)
        assert resp_del.status_code == 302
        assert not Recipe.objects.filter(pk=recipe.pk).exists()

    def test_spouse_shares_weekly_meal_plan(self, client, spouse_client, test_household, test_user, recipe_factory):
        """Meal plan entries created by one spouse are shared and immediately visible to the other spouse."""
        recipe = recipe_factory(household=test_household, created_by=test_user, title="Collaborative Curry")
        plan_date = timezone.now().date() + datetime.timedelta(days=2)

        # User 1 sets meal plan
        MealPlan.objects.create(
            household=test_household,
            created_by=test_user,
            date=plan_date,
            meal_type="DINNER",
            recipe=recipe,
        )

        # Spouse accesses meal plan view
        resp = spouse_client.get(reverse("recipes:meal_plan"))
        assert resp.status_code == 200
        assert "Collaborative Curry" in resp.content.decode()

        # Spouse accesses kiosk view
        resp_kiosk = spouse_client.get(reverse("recipes:meal_plan_kiosk"))
        assert resp_kiosk.status_code == 200
        assert "Collaborative Curry" in resp_kiosk.content.decode()

    def test_spouse_can_update_and_delete_meal_plan(self, spouse_client, test_household, test_user):
        """Spouse can update or delete meal plan entries using the meal plan API."""
        plan_date = timezone.now().date() + datetime.timedelta(days=1)
        plan_date_str = plan_date.strftime("%Y-%m-%d")

        # Spouse adds custom meal via API
        add_payload = {
            "date": plan_date_str,
            "meal_type": "LUNCH",
            "custom_meal": "Taco Tuesday",
            "action": "update",
        }
        resp = spouse_client.post(
            reverse("recipes:update_meal_plan"),
            data=json.dumps(add_payload),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"

        plan = MealPlan.objects.get(household=test_household, date=plan_date, meal_type="LUNCH")
        assert plan.custom_meal == "Taco Tuesday"

        # Spouse deletes the meal plan
        del_payload = {
            "date": plan_date_str,
            "meal_type": "LUNCH",
            "action": "delete",
        }
        resp_del = spouse_client.post(
            reverse("recipes:update_meal_plan"),
            data=json.dumps(del_payload),
            content_type="application/json",
        )
        assert resp_del.status_code == 200
        assert resp_del.json()["status"] == "success"
        assert not MealPlan.objects.filter(household=test_household, date=plan_date, meal_type="LUNCH").exists()

    def test_spouse_sees_future_and_search_recipes(self, spouse_client, test_household, test_user, recipe_factory):
        """Future recipes and search API results are synchronized across household members."""
        future_recipe = recipe_factory(
            household=test_household,
            created_by=test_user,
            title="Future Lasagna",
            is_future=True,
        )

        # Future view
        resp_future = spouse_client.get(reverse("recipes:future_recipes"))
        assert resp_future.status_code == 200
        assert "Future Lasagna" in resp_future.content.decode()

        # Search API
        resp_search = spouse_client.get(f"{reverse('recipes:search_recipes_api')}?q=Lasagna")
        assert resp_search.status_code == 200
        data = resp_search.json()
        assert any(item["id"] == future_recipe.id for item in data.get("recipes", []))


# =====================================================================
# 2. CROSS-HOUSEHOLD MULTI-TENANCY ISOLATION (ASSERT HTTP 404)
# =====================================================================

@pytest.mark.django_db
class TestCrossHouseholdIsolationEmpirical:
    """Empirical stress tests verifying that Household A cannot view, modify, or delete Household B private data."""

    def test_private_recipe_detail_returns_404(self, client, secondary_household, secondary_user):
        """GET request for foreign private recipe detail must return HTTP 404."""
        foreign_recipe = Recipe.objects.create(
            household=secondary_household,
            created_by=secondary_user,
            title="Household B Private Souffle",
            instructions="Secret steps.",
            is_shared=False,
        )

        resp = client.get(reverse("recipes:detail_recipe", kwargs={"pk": foreign_recipe.pk}))
        assert resp.status_code == 404

    def test_private_recipe_edit_returns_404_and_preserves_data(self, client, secondary_household, secondary_user):
        """GET and POST on foreign recipe edit endpoint must return HTTP 404 without altering record."""
        foreign_recipe = Recipe.objects.create(
            household=secondary_household,
            created_by=secondary_user,
            title="Household B Original Dish",
            instructions="Original instructions.",
            user_notes="Original notes",
            rating=5,
            is_shared=False,
        )

        edit_url = reverse("recipes:edit_recipe", kwargs={"pk": foreign_recipe.pk})

        # GET attempt
        resp_get = client.get(edit_url)
        assert resp_get.status_code == 404

        # POST attempt
        malicious_payload = {
            "title": "Hacked Title",
            "instructions": "Hacked instructions",
            "user_notes": "Hacked notes",
            "rating": "1",
        }
        resp_post = client.post(edit_url, data=malicious_payload)
        assert resp_post.status_code == 404

        foreign_recipe.refresh_from_db()
        assert foreign_recipe.title == "Household B Original Dish"
        assert foreign_recipe.instructions == "Original instructions."
        assert foreign_recipe.user_notes == "Original notes"
        assert foreign_recipe.rating == 5

    def test_private_recipe_delete_returns_404_and_preserves_data(self, client, secondary_household, secondary_user):
        """POST on foreign recipe delete endpoint must return HTTP 404 and not delete the record."""
        foreign_recipe = Recipe.objects.create(
            household=secondary_household,
            created_by=secondary_user,
            title="Household B Indestructible Dish",
            is_shared=False,
        )

        delete_url = reverse("recipes:delete_recipe", kwargs={"pk": foreign_recipe.pk})
        resp = client.post(delete_url)
        assert resp.status_code == 404

        assert Recipe.objects.filter(pk=foreign_recipe.pk).exists()

    def test_private_recipe_actions_return_404(self, client, secondary_household, secondary_user):
        """State mutation actions on foreign recipes (move-to-recipes, toggle-menu, copy) must return HTTP 404."""
        foreign_recipe = Recipe.objects.create(
            household=secondary_household,
            created_by=secondary_user,
            title="Household B Actions Test",
            is_shared=False,
            is_future=True,
            is_on_menu=False,
        )

        # Move to recipes
        resp_move = client.post(reverse("recipes:move_to_recipes", kwargs={"pk": foreign_recipe.pk}))
        assert resp_move.status_code == 404

        # Toggle menu status API
        resp_toggle = client.post(
            reverse("recipes:toggle_menu_status"),
            data=json.dumps({"recipe_id": foreign_recipe.pk}),
            content_type="application/json",
        )
        assert resp_toggle.status_code == 404

        # Direct copy of private recipe
        resp_copy = client.post(reverse("recipes:copy_recipe", kwargs={"pk": foreign_recipe.pk}))
        assert resp_copy.status_code == 404

    def test_search_api_and_sidebar_strictly_isolated(self, client, secondary_household, secondary_user):
        """Search API and sidebar pagination API never leak foreign private recipes."""
        unique_secret_title = f"SecretDish_{secrets.token_hex(4)}"
        foreign_recipe = Recipe.objects.create(
            household=secondary_household,
            created_by=secondary_user,
            title=unique_secret_title,
            is_shared=False,
        )

        # Search API
        resp_search = client.get(f"{reverse('recipes:search_recipes_api')}?q={unique_secret_title}")
        assert resp_search.status_code == 200
        recipes_found = resp_search.json().get("recipes", [])
        assert not any(r["id"] == foreign_recipe.id for r in recipes_found)

        # Sidebar pagination API
        resp_sidebar = client.get(f"{reverse('recipes:sidebar_pagination_api')}?page=1")
        assert resp_sidebar.status_code == 200
        assert unique_secret_title not in resp_sidebar.content.decode()

    def test_meal_plan_views_isolated(self, client, secondary_household, secondary_user, recipe_factory):
        """Meal plan views do not leak foreign household entries."""
        foreign_recipe = recipe_factory(
            household=secondary_household,
            created_by=secondary_user,
            title="Foreign Secret Banquet",
            is_shared=False,
        )
        plan_date = timezone.now().date() + datetime.timedelta(days=3)

        MealPlan.objects.create(
            household=secondary_household,
            created_by=secondary_user,
            date=plan_date,
            meal_type="DINNER",
            recipe=foreign_recipe,
        )

        # Primary household checks meal plan calendar
        resp_plan = client.get(reverse("recipes:meal_plan"))
        assert resp_plan.status_code == 200
        assert "Foreign Secret Banquet" not in resp_plan.content.decode()

        # Primary household checks kiosk view
        resp_kiosk = client.get(reverse("recipes:meal_plan_kiosk"))
        assert resp_kiosk.status_code == 200
        assert "Foreign Secret Banquet" not in resp_kiosk.content.decode()

    def test_meal_plan_update_delete_isolation(self, client, secondary_household, secondary_user):
        """API delete request for a date/meal where foreign household has an entry must not delete foreign entry."""
        plan_date = timezone.now().date() + datetime.timedelta(days=4)
        plan_date_str = plan_date.strftime("%Y-%m-%d")

        foreign_plan = MealPlan.objects.create(
            household=secondary_household,
            created_by=secondary_user,
            date=plan_date,
            meal_type="LUNCH",
            custom_meal="Foreign Protected Sandwich",
        )

        # Client attempts delete on identical date and meal_type
        del_payload = {
            "date": plan_date_str,
            "meal_type": "LUNCH",
            "action": "delete",
        }
        resp = client.post(
            reverse("recipes:update_meal_plan"),
            data=json.dumps(del_payload),
            content_type="application/json",
        )
        assert resp.status_code == 200

        # Verify foreign plan is untouched
        assert MealPlan.objects.filter(pk=foreign_plan.pk).exists()

    def test_meal_plan_update_cannot_attach_foreign_private_recipe(self, client, secondary_household, secondary_user):
        """Meal plan API update must reject attaching a private recipe from another household (returns 404)."""
        foreign_private_recipe = Recipe.objects.create(
            household=secondary_household,
            created_by=secondary_user,
            title="Foreign Private Enchiladas",
            is_shared=False,
        )
        plan_date = timezone.now().date() + datetime.timedelta(days=5)

        payload = {
            "date": plan_date.strftime("%Y-%m-%d"),
            "meal_type": "DINNER",
            "recipe_id": foreign_private_recipe.id,
            "action": "update",
        }
        resp = client.post(
            reverse("recipes:update_meal_plan"),
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 404
        assert not MealPlan.objects.filter(recipe=foreign_private_recipe).exclude(household=secondary_household).exists()

    def test_tag_autocomplete_isolation(self, client, secondary_household):
        """Tag autocomplete must not expose private tags of other households."""
        RecipeTag.objects.create(
            household=secondary_household,
            name="TopSecretGlutenFreeTag",
            color="#FF0000",
        )

        resp = client.get(f"{reverse('recipes:tag_autocomplete')}?query=TopSecret")
        assert resp.status_code == 200
        tags = resp.json()
        assert not any(t.get("name") == "TopSecretGlutenFreeTag" for t in tags)


# =====================================================================
# 3. CROSS-HOUSEHOLD RECIPE SHARING & CLONING
# =====================================================================

@pytest.mark.django_db
class TestCrossHouseholdSharingAndCloningEmpirical:
    """Empirical stress tests verifying shared catalog, privacy suppression, and 1-click cloning."""

    def test_shared_catalog_browse_and_attribution(self, client, secondary_household, secondary_user):
        """Shared recipes appear in /recipes/shared/ with attribution, while private recipes remain hidden."""
        Recipe.objects.create(
            household=secondary_household,
            created_by=secondary_user,
            title="Community Chili",
            is_shared=True,
            is_future=False,
        )
        Recipe.objects.create(
            household=secondary_household,
            created_by=secondary_user,
            title="Family Secret Chili",
            is_shared=False,
            is_future=False,
        )

        resp = client.get(reverse("recipes:shared_recipe_list"))
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Community Chili" in content
        assert secondary_household.name in content
        assert "Family Secret Chili" not in content

    def test_shared_recipe_detail_suppresses_private_notes_and_ratings(self, client, secondary_client, secondary_household, secondary_user):
        """Shared recipe detail view hides private author notes and ratings from non-owners, but displays them to owner."""
        secret_note = "Secret spice mix: 3 parts paprika, 1 part cumin"
        shared_recipe = Recipe.objects.create(
            household=secondary_household,
            created_by=secondary_user,
            title="Authentic Paella",
            instructions="1. Heat olive oil.\n2. Add rice and saffron broth.",
            user_notes=secret_note,
            rating=5,
            is_shared=True,
            is_future=False,
        )

        # Viewer from Household A
        resp_foreign = client.get(reverse("recipes:detail_recipe", kwargs={"pk": shared_recipe.pk}))
        assert resp_foreign.status_code == 200
        foreign_content = resp_foreign.content.decode()

        assert "Authentic Paella" in foreign_content
        assert "Heat olive oil" in foreign_content
        assert resp_foreign.context["is_own_recipe"] is False
        assert secret_note not in foreign_content
        assert "Your Notes" not in foreign_content
        # Ensure author's rating is suppressed for non-owner
        assert "Rating:" not in foreign_content or resp_foreign.context["is_own_recipe"]

        # Owner from Household B
        resp_owner = secondary_client.get(reverse("recipes:detail_recipe", kwargs={"pk": shared_recipe.pk}))
        assert resp_owner.status_code == 200
        owner_content = resp_owner.content.decode()
        assert resp_owner.context["is_own_recipe"] is True
        assert secret_note in owner_content
        assert "Your Notes" in owner_content
        assert "5" in owner_content

    def test_one_click_copy_deep_clones_recipe_and_ingredients(self, client, test_household, test_user, secondary_household, secondary_user):
        """1-click 'Copy to My Household' deep-clones recipe, ingredients, and tags cleanly into target household."""
        shared_recipe = Recipe.objects.create(
            household=secondary_household,
            created_by=secondary_user,
            title="Shared Chocolate Chip Cookies",
            description="Chewy and buttery.",
            instructions="1. Cream butter and sugar.\n2. Fold in chocolate chips.\n3. Bake at 375F.",
            user_notes="Foreign private note",
            rating=5,
            is_shared=True,
        )

        ing1, _ = Ingredient.objects.get_or_create(name="all-purpose flour")
        ing2, _ = Ingredient.objects.get_or_create(name="semisweet chocolate chips")
        ing3, _ = Ingredient.objects.get_or_create(name="salted butter")

        RecipeIngredient.objects.create(
            recipe=shared_recipe,
            ingredient=ing1,
            raw_text="2 1/4 cups all-purpose flour",
            quantity="2.25",
            unit="cups",
            order=0,
        )
        RecipeIngredient.objects.create(
            recipe=shared_recipe,
            ingredient=ing2,
            raw_text="2 cups semisweet chocolate chips",
            quantity="2",
            unit="cups",
            order=1,
        )
        RecipeIngredient.objects.create(
            recipe=shared_recipe,
            ingredient=ing3,
            raw_text="1 cup salted butter, softened",
            quantity="1",
            unit="cup",
            preparation="softened",
            order=2,
        )

        tag = RecipeTag.objects.create(
            household=secondary_household,
            name="Baking",
            color="#E67E22",
        )
        shared_recipe.tags.add(tag)

        # Household A copies the recipe
        copy_url = reverse("recipes:copy_recipe", kwargs={"pk": shared_recipe.pk})
        resp = client.post(copy_url)
        assert resp.status_code == 302

        # Verify cloned recipe properties
        cloned = Recipe.objects.filter(household=test_household, title="Shared Chocolate Chip Cookies").first()
        assert cloned is not None
        assert cloned.pk != shared_recipe.pk
        assert cloned.household == test_household
        assert cloned.created_by == test_user
        assert cloned.is_shared is True  # Cloned copy defaults to shared
        assert cloned.description == "Chewy and buttery."
        assert cloned.instructions == shared_recipe.instructions
        assert cloned.user_notes == ""  # Source notes wiped
        assert cloned.rating is None    # Source rating wiped

        # Verify ingredients cloned with exact fidelity
        cloned_ingredients = list(cloned.recipe_ingredients.order_by("order"))
        assert len(cloned_ingredients) == 3
        assert cloned_ingredients[0].ingredient == ing1
        assert cloned_ingredients[0].quantity == "2.25"
        assert cloned_ingredients[0].unit == "cups"
        assert cloned_ingredients[1].ingredient == ing2
        assert cloned_ingredients[1].quantity == "2"
        assert cloned_ingredients[2].ingredient == ing3
        assert cloned_ingredients[2].preparation == "softened"

        # Verify tag cloned for Household A
        assert cloned.tags.filter(name="Baking", household=test_household).exists()

    def test_cloned_recipe_independent_mutation(self, client, test_household, secondary_household, secondary_user):
        """Mutating a cloned recipe has zero effect on the original author's recipe in the foreign household."""
        shared_recipe = Recipe.objects.create(
            household=secondary_household,
            created_by=secondary_user,
            title="Original Shared Pizza",
            instructions="Bake 15 min at 450F.",
            is_shared=True,
        )

        # Clone
        resp_copy = client.post(reverse("recipes:copy_recipe", kwargs={"pk": shared_recipe.pk}))
        assert resp_copy.status_code == 302

        cloned = Recipe.objects.get(household=test_household, title="Original Shared Pizza")

        # Household A edits cloned recipe
        edit_url = reverse("recipes:edit_recipe", kwargs={"pk": cloned.pk})
        client.post(edit_url, data={
            "title": "Modified Household A Pizza",
            "instructions": "Bake 20 min at 500F on pizza stone.",
            "user_notes": "Added garlic crust",
            "rating": "5",
        })

        cloned.refresh_from_db()
        assert cloned.title == "Modified Household A Pizza"
        assert cloned.instructions == "Bake 20 min at 500F on pizza stone."

        # Verify source recipe is 100% untouched
        shared_recipe.refresh_from_db()
        assert shared_recipe.title == "Original Shared Pizza"
        assert shared_recipe.instructions == "Bake 15 min at 450F."

    def test_revoking_shared_status_immediately_blocks_foreign_access(self, client, secondary_household, secondary_user):
        """Unchecking is_shared immediately removes recipe from catalog and returns 404 for foreign viewers."""
        recipe = Recipe.objects.create(
            household=secondary_household,
            created_by=secondary_user,
            title="Temporarily Shared Bread",
            is_shared=True,
        )

        # Accessible while shared
        assert client.get(reverse("recipes:detail_recipe", kwargs={"pk": recipe.pk})).status_code == 200

        # Owner revokes sharing
        recipe.is_shared = False
        recipe.save()

        # Catalog excludes it
        resp_cat = client.get(reverse("recipes:shared_recipe_list"))
        assert "Temporarily Shared Bread" not in resp_cat.content.decode()

        # Direct access returns 404
        assert client.get(reverse("recipes:detail_recipe", kwargs={"pk": recipe.pk})).status_code == 404

    def test_copy_own_recipe_informs_and_does_not_duplicate(self, client, test_household, test_user):
        """Attempting to copy a recipe that already belongs to user's household informs user and creates zero duplicates."""
        own_recipe = Recipe.objects.create(
            household=test_household,
            created_by=test_user,
            title="Own Household Brownies",
            is_shared=True,
        )

        initial_count = Recipe.objects.filter(household=test_household).count()

        resp = client.post(reverse("recipes:copy_recipe", kwargs={"pk": own_recipe.pk}))
        assert resp.status_code == 302
        assert resp.url == reverse("recipes:detail_recipe", kwargs={"pk": own_recipe.pk})

        final_count = Recipe.objects.filter(household=test_household).count()
        assert final_count == initial_count

    def test_copy_recipe_url_collision_disambiguation(self, client, test_household, test_user, secondary_household, secondary_user):
        """Cloning a recipe whose original_url already exists in target household disambiguates URL with #copy-<hex>."""
        target_url = "https://example.com/unique-apple-pie"

        # Household A already has a recipe with this URL
        Recipe.objects.create(
            household=test_household,
            created_by=test_user,
            title="Our Apple Pie",
            original_url=target_url,
        )

        # Household B shares their version from the same URL
        source_recipe = Recipe.objects.create(
            household=secondary_household,
            created_by=secondary_user,
            title="Their Gourmet Apple Pie",
            original_url=target_url,
            is_shared=True,
        )

        resp = client.post(reverse("recipes:copy_recipe", kwargs={"pk": source_recipe.pk}))
        assert resp.status_code == 302

        cloned = Recipe.objects.filter(household=test_household, title="Their Gourmet Apple Pie").first()
        assert cloned is not None
        assert cloned.original_url.startswith(f"{target_url}#copy-")


# =====================================================================
# 4. DUPLICATE URL SCRAPING DETECTION & ALERT BANNER
# =====================================================================

@pytest.mark.django_db
class TestDuplicateURLScrapingAlertEmpirical:
    """Empirical stress tests verifying duplicate URL detection, alert banner actions, and same-household rejection."""

    def test_cross_household_duplicate_url_renders_alert_banner(self, client, secondary_household, secondary_user):
        """Clipping a URL owned by another household renders the duplicate alert banner without scraping."""
        external_url = "https://www.seriouseats.com/the-best-chocolate-chip-cookies-recipe"
        Recipe.objects.create(
            household=secondary_household,
            created_by=secondary_user,
            title="SeriousEats Best Cookies",
            original_url=external_url,
            cook_time=15,
            total_time=45,
        )

        # Household A submits the same URL
        resp = client.post(reverse("recipes:add_recipe"), data={"original_url": external_url})
        assert resp.status_code == 200
        content = resp.content.decode()

        assert "duplicate-alert-banner" in content
        assert "Recipe Already Saved on KitchenClip" in content
        assert "SeriousEats Best Cookies" in content
        assert "btn-copy-existing" in content
        assert "btn-force-scrape" in content

        # Verify no new recipe created in Household A yet
        assert not Recipe.objects.filter(original_url=external_url).exclude(household=secondary_household).exists()

    def test_duplicate_banner_copy_existing_action(self, client, test_household, test_user, secondary_household, secondary_user):
        """Clicking 'Copy to My Household' on the duplicate banner clones recipe and preserves form metadata."""
        external_url = "https://www.seriouseats.com/the-best-chocolate-chip-cookies-recipe"
        source = Recipe.objects.create(
            household=secondary_household,
            created_by=secondary_user,
            title="SeriousEats Best Cookies",
            original_url=external_url,
            instructions="Bake at 375F.",
        )
        ing, _ = Ingredient.objects.get_or_create(name="dark chocolate")
        RecipeIngredient.objects.create(
            recipe=source,
            ingredient=ing,
            quantity="8",
            unit="oz",
        )

        copy_url = reverse("recipes:copy_duplicate", kwargs={"pk": source.pk})
        payload = {
            "original_url": external_url,
            "user_notes": "Custom notes from import form",
            "rating": "4",
            "tags": "dessert, weekend",
            "is_future": "0",
        }
        resp = client.post(copy_url, data=payload)
        assert resp.status_code == 302

        cloned = Recipe.objects.filter(household=test_household, original_url=external_url).first()
        assert cloned is not None
        assert cloned.title == "SeriousEats Best Cookies"
        assert cloned.user_notes == "Custom notes from import form"
        assert cloned.rating == 4
        assert cloned.recipe_ingredients.count() == 1
        assert cloned.tags.filter(name="dessert", household=test_household).exists()

    def test_duplicate_banner_force_scrape_action(self, client, test_household, secondary_household, secondary_user):
        """Clicking 'Scrape Fresh Anyway' passes force_scrape=1 and bypasses the duplicate alert banner."""
        external_url = "https://www.seriouseats.com/the-best-chocolate-chip-cookies-recipe"
        Recipe.objects.create(
            household=secondary_household,
            created_by=secondary_user,
            title="Old Version Cookies",
            original_url=external_url,
        )

        # Mock ParserRegistry for the force scrape
        mock_parser = MagicMock()
        mock_parser.title = "Fresh Scraped Cookies"
        mock_parser.description = "Newly scraped version"
        mock_parser.prep_time = 10
        mock_parser.cook_time = 15
        mock_parser.total_time = 25
        mock_parser.servings = 4
        mock_parser.instructions = "Fresh instructions"
        mock_parser.image_url = ""
        mock_parser.ingredients = ["2 cups flour", "1 cup sugar"]

        with patch("recipes.views.ParserRegistry.get_parser", return_value=mock_parser):
            resp = client.post(
                reverse("recipes:add_recipe"),
                data={"original_url": external_url, "force_scrape": "1"},
            )
            assert resp.status_code == 302

        # Both households independently own recipes matching the URL
        assert Recipe.objects.filter(household=secondary_household, original_url=external_url).exists()
        fresh = Recipe.objects.filter(household=test_household, title="Fresh Scraped Cookies").first()
        assert fresh is not None
        assert fresh.original_url in (external_url, "https://seriouseats.com/the-best-chocolate-chip-cookies-recipe")

    def test_same_household_duplicate_url_rejected_by_form_validation(self, client, spouse_client, test_household, test_user):
        """Clipping a URL already owned by the user's own household is rejected by form validation without alert banner."""
        external_url = "https://www.seriouseats.com/the-best-chocolate-chip-cookies-recipe"
        Recipe.objects.create(
            household=test_household,
            created_by=test_user,
            title="Our Cookies",
            original_url=external_url,
        )

        # User 1 attempts re-adding the same URL
        resp1 = client.post(reverse("recipes:add_recipe"), data={"original_url": external_url})
        assert resp1.status_code == 200
        content1 = resp1.content.decode()
        assert "This recipe is already in your household collection" in content1
        assert "duplicate-alert-banner" not in content1

        # Spouse in same household attempts adding the same URL
        resp2 = spouse_client.post(reverse("recipes:add_recipe"), data={"original_url": external_url})
        assert resp2.status_code == 200
        content2 = resp2.content.decode()
        assert "This recipe is already in your household collection" in content2
        assert "duplicate-alert-banner" not in content2

    def test_duplicate_url_normalization_permutations(self, client, secondary_household, secondary_user):
        """Duplicate detection correctly normalizes protocol, www, trailing slashes, and tracking query parameters."""
        saved_url = "https://example.com/hearty-stew/"
        Recipe.objects.create(
            household=secondary_household,
            created_by=secondary_user,
            title="Hearty Beef Stew",
            original_url=saved_url,
        )

        # Entered URL with http, www, no trailing slash, and UTM parameters
        entered_url = "http://www.example.com/hearty-stew?utm_source=feed&utm_campaign=winter"

        resp = client.post(reverse("recipes:add_recipe"), data={"original_url": entered_url})
        assert resp.status_code == 200
        assert "duplicate-alert-banner" in resp.content.decode()

    def test_copy_duplicate_anti_tampering_and_idor_protection(self, client, test_household, test_user, secondary_household, secondary_user):
        """Submitting copy_duplicate with tampered URL or manual recipe without URL returns HTTP 404."""
        recipe_with_url = Recipe.objects.create(
            household=secondary_household,
            created_by=secondary_user,
            title="Valid URL Recipe",
            original_url="https://example.com/valid-recipe",
        )
        recipe_manual = Recipe.objects.create(
            household=secondary_household,
            created_by=secondary_user,
            title="Manual Recipe No URL",
            original_url="",
        )

        # Tampered URL mismatch
        resp_tamper = client.post(
            reverse("recipes:copy_duplicate", kwargs={"pk": recipe_with_url.pk}),
            data={"original_url": "https://example.com/different-recipe"},
        )
        assert resp_tamper.status_code == 404

        # Missing URL
        resp_missing = client.post(
            reverse("recipes:copy_duplicate", kwargs={"pk": recipe_with_url.pk}),
            data={"original_url": ""},
        )
        assert resp_missing.status_code == 404

        # Recipe without URL
        resp_no_url = client.post(
            reverse("recipes:copy_duplicate", kwargs={"pk": recipe_manual.pk}),
            data={"original_url": "https://example.com/some-url"},
        )
        assert resp_no_url.status_code == 404

        # Copy own recipe via copy_duplicate redirects with info message
        own_recipe = Recipe.objects.create(
            household=test_household,
            created_by=test_user,
            title="Own Recipe",
            original_url="https://example.com/own-recipe",
        )
        resp_own = client.post(
            reverse("recipes:copy_duplicate", kwargs={"pk": own_recipe.pk}),
            data={"original_url": "https://example.com/own-recipe"},
        )
        assert resp_own.status_code == 302
        assert resp_own.url == reverse("recipes:detail_recipe", kwargs={"pk": own_recipe.pk})
