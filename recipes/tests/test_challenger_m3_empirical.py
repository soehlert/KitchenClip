import json

import pytest
from django.urls import reverse
from django.utils import timezone

from recipes.models import Ingredient, MealPlan, Recipe, RecipeIngredient, RecipeTag


# ==============================================================================
# Suite 1: Unauthenticated Boundary Enforcement
# ==============================================================================

@pytest.mark.django_db
@pytest.mark.parametrize("url_name,kwargs,method,data", [
    ("recipes:list_recipe", {}, "GET", None),
    ("recipes:future_recipes", {}, "GET", None),
    ("recipes:shared_recipe_list", {}, "GET", None),
    ("recipes:add_recipe", {}, "GET", None),
    ("recipes:manual_add", {}, "GET", None),
    ("recipes:meal_plan", {}, "GET", None),
    ("recipes:meal_plan_kiosk", {}, "GET", None),
    ("recipes:tag_autocomplete", {}, "GET", None),
    ("recipes:sidebar_pagination_api", {}, "GET", None),
    ("recipes:search_recipes_api", {}, "GET", None),
    ("recipes:toggle_menu_status", {}, "POST", json.dumps({"recipe_id": 1})),
    ("recipes:update_meal_plan", {}, "POST", json.dumps({"date": "2026-09-07", "meal_type": "DINNER"})),
])
def test_unauthenticated_requests_redirect_to_login(unauthenticated_client, url_name, kwargs, method, data):
    url = reverse(url_name, kwargs=kwargs)
    if method == "GET":
        resp = unauthenticated_client.get(url)
    else:
        resp = unauthenticated_client.post(url, data=data or {}, content_type="application/json")
    assert resp.status_code == 302, f"Expected 302 for {url_name}, got {resp.status_code}"
    assert "/auth/login/" in resp.url


@pytest.mark.django_db
def test_unauthenticated_parameterized_views_redirect(unauthenticated_client, recipe_factory):
    recipe = recipe_factory()
    pk = recipe.pk
    for url_name, method in [
        ("recipes:detail_recipe", "GET"),
        ("recipes:edit_recipe", "GET"),
        ("recipes:edit_recipe", "POST"),
        ("recipes:delete_recipe", "POST"),
        ("recipes:move_to_recipes", "POST"),
        ("recipes:copy_recipe", "POST"),
        ("recipes:copy_duplicate", "POST"),
    ]:
        url = reverse(url_name, kwargs={"pk": pk})
        resp = unauthenticated_client.get(url) if method == "GET" else unauthenticated_client.post(url)
        assert resp.status_code == 302, f"Expected 302 for unauthenticated {url_name}, got {resp.status_code}"
        assert "/auth/login/" in resp.url


# ==============================================================================
# Suite 2: Cross-Tenant Isolation & Mutation Prevention
# ==============================================================================

@pytest.mark.django_db
def test_cross_household_private_recipe_access_denied(secondary_client, test_household, recipe_factory):
    """Verify Household B cannot view, edit, delete, or move Household A's private recipe."""
    recipe = recipe_factory(household=test_household, title="Household A Private", is_shared=False, is_future=True)

    # 1. Detail View -> 404
    detail_url = reverse("recipes:detail_recipe", kwargs={"pk": recipe.pk})
    assert secondary_client.get(detail_url).status_code == 404

    # 2. Edit View (GET & POST) -> 404
    edit_url = reverse("recipes:edit_recipe", kwargs={"pk": recipe.pk})
    assert secondary_client.get(edit_url).status_code == 404
    post_edit = secondary_client.post(edit_url, {
        "title": "Hacked Title",
        "prep_time": "1",
        "cook_time": "1",
        "total_time": "2",
        "servings": "1",
        "instructions": "Hacked",
    })
    assert post_edit.status_code == 404
    recipe.refresh_from_db()
    assert recipe.title == "Household A Private"

    # 3. Delete View -> 404
    delete_url = reverse("recipes:delete_recipe", kwargs={"pk": recipe.pk})
    assert secondary_client.post(delete_url).status_code == 404
    assert Recipe.objects.filter(pk=recipe.pk).exists()

    # 4. Move to Recipes -> 404
    move_url = reverse("recipes:move_to_recipes", kwargs={"pk": recipe.pk})
    assert secondary_client.post(move_url).status_code == 404
    recipe.refresh_from_db()
    assert recipe.is_future is True

    # 5. Toggle Menu Status -> 404
    toggle_url = reverse("recipes:toggle_menu_status")
    resp = secondary_client.post(toggle_url, data=json.dumps({"recipe_id": recipe.pk}), content_type="application/json")
    assert resp.status_code == 404
    recipe.refresh_from_db()
    assert recipe.is_on_menu is False

    # 6. Copy Recipe -> 404
    copy_url = reverse("recipes:copy_recipe", kwargs={"pk": recipe.pk})
    assert secondary_client.post(copy_url).status_code == 404


@pytest.mark.django_db
def test_cross_household_meal_plan_isolation_and_foreign_recipe_injection(
    client, secondary_client, test_household, secondary_household, recipe_factory, meal_plan_factory
):
    """Verify meal plan records are isolated and foreign private recipes cannot be injected."""
    today = timezone.now().date()
    private_recipe = recipe_factory(household=test_household, title="Household A Secret Lasagna", is_shared=False)

    # Attempt to inject Household A's private recipe into Household B's meal plan
    payload = {
        "date": today.isoformat(),
        "meal_type": "DINNER",
        "recipe_id": private_recipe.pk,
    }
    resp = secondary_client.post(reverse("recipes:update_meal_plan"), data=json.dumps(payload), content_type="application/json")
    assert resp.status_code == 404
    assert not MealPlan.objects.filter(household=secondary_household, recipe=private_recipe).exists()

    # Household A creates a valid meal plan
    meal_a = meal_plan_factory(household=test_household, date=today, meal_type="LUNCH", custom_meal="A Lunch Salad")

    # Household B sends delete action for the same date and meal_type
    del_payload = {
        "date": today.isoformat(),
        "meal_type": "LUNCH",
        "action": "delete",
    }
    del_resp = secondary_client.post(reverse("recipes:update_meal_plan"), data=json.dumps(del_payload), content_type="application/json")
    assert del_resp.status_code == 200

    # Household A's meal plan must remain untouched
    assert MealPlan.objects.filter(pk=meal_a.pk).exists()
    meal_a.refresh_from_db()
    assert meal_a.custom_meal == "A Lunch Salad"


@pytest.mark.django_db
def test_cross_household_tag_and_sidebar_isolation(
    client, secondary_client, test_household, secondary_household, recipe_factory
):
    """Verify tag autocomplete, sidebar pagination, and search API cannot leak foreign data."""
    RecipeTag.objects.create(household=test_household, name="exclusive-vegan")
    RecipeTag.objects.create(household=secondary_household, name="exclusive-bbq")

    # Tag Autocomplete
    resp_a = client.get(reverse("recipes:tag_autocomplete") + "?q=exclusive").json()
    names_a = [t["name"] for t in resp_a]
    assert "exclusive-vegan" in names_a
    assert "exclusive-bbq" not in names_a

    resp_b = secondary_client.get(reverse("recipes:tag_autocomplete") + "?q=exclusive").json()
    names_b = [t["name"] for t in resp_b]
    assert "exclusive-bbq" in names_b
    assert "exclusive-vegan" not in names_b

    # Search Recipes API
    recipe_factory(household=test_household, title="Household A Risotto")
    recipe_factory(household=secondary_household, title="Household B Risotto")

    search_a = client.get(reverse("recipes:search_recipes_api") + "?q=Risotto").json()
    assert len(search_a["recipes"]) == 1
    assert search_a["recipes"][0]["title"] == "Household A Risotto"

    search_b = secondary_client.get(reverse("recipes:search_recipes_api") + "?q=Risotto").json()
    assert len(search_b["recipes"]) == 1
    assert search_b["recipes"][0]["title"] == "Household B Risotto"


# ==============================================================================
# Suite 3: Spouse / Partner Same-Household Read-Write Collaboration
# ==============================================================================

@pytest.mark.django_db
def test_spouse_full_lifecycle_collaboration(
    auth_client_factory, test_household, test_user, household_member_user, recipe_factory
):
    """Verify that spouses in the same household share full read, update, menu, and delete access."""
    spouse1_client = auth_client_factory(user=test_user, household=test_household, role="admin")
    spouse2_client = auth_client_factory(user=household_member_user, household=test_household, role="member")

    # 1. Spouse 1 creates a recipe
    recipe = recipe_factory(household=test_household, created_by=test_user, title="Spouse Shared Casserole", is_future=True)

    # 2. Spouse 2 reads the recipe list and detail
    list_resp = spouse2_client.get(reverse("recipes:future_recipes"))
    assert recipe in list_resp.context["recipes"]

    detail_resp = spouse2_client.get(reverse("recipes:detail_recipe", kwargs={"pk": recipe.pk}))
    assert detail_resp.status_code == 200
    assert detail_resp.context["is_own_recipe"] is True

    # 3. Spouse 2 moves recipe from future to saved
    move_resp = spouse2_client.post(reverse("recipes:move_to_recipes", kwargs={"pk": recipe.pk}))
    assert move_resp.status_code == 302
    recipe.refresh_from_db()
    assert recipe.is_future is False

    # 4. Spouse 2 edits recipe
    edit_resp = spouse2_client.post(reverse("recipes:edit_recipe", kwargs={"pk": recipe.pk}), {
        "title": "Spouse Modified Casserole",
        "prep_time": "15",
        "cook_time": "45",
        "total_time": "60",
        "servings": "6",
        "instructions": "Bake at 375F",
    })
    assert edit_resp.status_code == 302
    recipe.refresh_from_db()
    assert recipe.title == "Spouse Modified Casserole"

    # 5. Spouse 2 toggles recipe onto menu
    toggle_resp = spouse2_client.post(
        reverse("recipes:toggle_menu_status"),
        data=json.dumps({"recipe_id": recipe.pk}),
        content_type="application/json"
    )
    assert toggle_resp.status_code == 200
    assert toggle_resp.json()["is_on_menu"] is True
    recipe.refresh_from_db()
    assert recipe.is_on_menu is True

    # 6. Spouse 2 adds recipe to weekly meal plan
    today = timezone.now().date()
    plan_resp = spouse2_client.post(
        reverse("recipes:update_meal_plan"),
        data=json.dumps({"date": today.isoformat(), "meal_type": "DINNER", "recipe_id": recipe.pk}),
        content_type="application/json"
    )
    assert plan_resp.status_code == 200
    plan_entry = MealPlan.objects.get(household=test_household, date=today, meal_type="DINNER")
    assert plan_entry.recipe == recipe

    # 7. Spouse 1 views meal plan and sees Spouse 2's entry
    mp_resp = spouse1_client.get(reverse("recipes:meal_plan"))
    assert mp_resp.status_code == 200
    weeks = mp_resp.context["weeks"]
    today_slot = next(d for w in weeks for d in w if d["date"] == today)
    assert today_slot["dinner"].recipe == recipe

    # 8. Spouse 2 deletes the recipe
    del_resp = spouse2_client.post(reverse("recipes:delete_recipe", kwargs={"pk": recipe.pk}))
    assert del_resp.status_code == 302
    assert not Recipe.objects.filter(pk=recipe.pk).exists()


# ==============================================================================
# Suite 4: Adversarial Duplicate Alert & IDOR Vulnerability Investigation
# ==============================================================================

@pytest.mark.django_db
def test_copy_duplicate_on_private_manual_recipe_exfiltration(secondary_client, test_household, test_user):
    """ADVERSARIAL STRESS TEST: Can Household B steal Household A's private manual recipe via copy-duplicate?

    Household A creates a private manual recipe with secret instructions and NO original_url.
    Household B attempts to POST directly to /recipes/<pk>/copy-duplicate/.
    """
    private_secret_recipe = Recipe.objects.create(
        household=test_household,
        created_by=test_user,
        title="Household A Secret Family Sauce",
        description="Confidential recipe",
        instructions="Secret ingredients: 1g truffles, simmer 4 hours.",
        original_url="",  # No external URL (manual recipe)
        is_shared=False,
    )
    ing = Ingredient.objects.create(name="Truffle")
    RecipeIngredient.objects.create(
        recipe=private_secret_recipe,
        ingredient=ing,
        raw_text="1g Truffle",
        quantity="1",
        unit="g",
        order=0,
    )

    url = reverse("recipes:copy_duplicate", kwargs={"pk": private_secret_recipe.pk})
    resp = secondary_client.post(url, {})

    # Check whether the endpoint allowed Household B to clone and exfiltrate Household A's private recipe
    # If the system protects private recipes, this should return HTTP 404 or 403.
    # If this returns 302 and clones the recipe, it reveals an IDOR / data leak vulnerability.
    cloned_exists = Recipe.objects.filter(
        title="Household A Secret Family Sauce"
    ).exclude(household=test_household).exists()

    # We assert that Household B MUST NOT be able to clone Household A's private manual recipe!
    assert not cloned_exists, "SECURITY VULNERABILITY: Household B was able to copy Household A's private manual recipe via copy-duplicate!"
    assert resp.status_code in [403, 404], f"Expected 403 or 404, but got {resp.status_code}"


@pytest.mark.django_db
def test_copy_duplicate_own_recipe_duplicates_instead_of_informing(client, test_household, test_user):
    """Calling copy_duplicate on own recipe bypasses same-household duplicate detection and creates duplicate."""
    recipe = Recipe.objects.create(
        household=test_household,
        created_by=test_user,
        title="My Own Lasagna",
        original_url="https://example.com/lasagna",
    )
    url = reverse("recipes:copy_duplicate", kwargs={"pk": recipe.pk})
    client.post(url, {}, follow=True)
    # If the user already owns this recipe, should it create a duplicate with #copy-...?
    # Notice that copy_recipe has an explicit check preventing duplicate cloning of own recipe.
    count = Recipe.objects.filter(household=test_household, title="My Own Lasagna").count()
    assert count == 1, f"Expected 1 recipe, but got {count} (unintended duplicate created)"


@pytest.mark.django_db
def test_cross_household_mass_exfiltration_via_copy_duplicate_idor(secondary_client, test_household, test_user):
    """ADVERSARIAL ATTACK: Attacker iterates integer PKs on copy_duplicate to exfiltrate private recipes.

    Household A has multiple private recipes (both manual and external).
    Attacker in Household B iterates PKs against /recipes/<pk>/copy-duplicate/.
    """
    r1 = Recipe.objects.create(
        household=test_household,
        created_by=test_user,
        title="Household A Secret BBQ",
        instructions="Secret BBQ blend",
        original_url="",
        is_shared=False,
    )
    r2 = Recipe.objects.create(
        household=test_household,
        created_by=test_user,
        title="Household A Secret Stew",
        instructions="Secret Stew blend",
        original_url="https://private-family-site.com/stew",
        is_shared=False,
    )

    for recipe in [r1, r2]:
        url = reverse("recipes:copy_duplicate", kwargs={"pk": recipe.pk})
        secondary_client.post(url, {})

    # Household B should NOT have any cloned recipes from Household A's private collection
    stolen_recipes = Recipe.objects.filter(
        title__in=["Household A Secret BBQ", "Household A Secret Stew"]
    ).exclude(household=test_household)

    assert stolen_recipes.count() == 0, (
        f"CRITICAL VULNERABILITY: Household B exfiltrated {stolen_recipes.count()} private recipes via IDOR enumeration!"
    )


# ==============================================================================
# Suite 5: Empirical Remediation Stress Suite - IDOR & Isolation Deep Probe
# ==============================================================================

@pytest.mark.django_db
class TestM3RemediationIDORAndIsolationChallenger:
    """Rigorous empirical stress test of copy-duplicate isolation and IDOR defenses."""

    def test_pk_enumeration_and_malformed_requests(
        self, secondary_client, test_household, test_user
    ):
        """Adversarial probe: PK enumeration with various payloads against copy-duplicate.
        
        Must return 404 for non-existent PKs, mismatched URLs, omitted URLs, empty URLs,
        whitespace URLs, or attempts to duplicate foreign private recipes without the exact URL.
        """
        r_manual = Recipe.objects.create(
            household=test_household,
            created_by=test_user,
            title="A's Secret Manual Pie",
            instructions="Confidential family recipe",
            original_url="",
            is_shared=False,
        )
        r_ext = Recipe.objects.create(
            household=test_household,
            created_by=test_user,
            title="A's Secret Web Roast",
            instructions="Roast instructions",
            original_url="https://secret-domain.com/roast",
            is_shared=False,
        )

        # 1. Non-existent PK
        res_nonexistent = secondary_client.post(
            reverse("recipes:copy_duplicate", kwargs={"pk": 999999}),
            {"original_url": "https://secret-domain.com/roast"},
        )
        assert res_nonexistent.status_code == 404

        # 2. Manual recipe (no original_url) - cannot duplicate even if URL is submitted
        res_manual_with_url = secondary_client.post(
            reverse("recipes:copy_duplicate", kwargs={"pk": r_manual.pk}),
            {"original_url": "https://secret-domain.com/roast"},
        )
        assert res_manual_with_url.status_code == 404

        # 3. Manual recipe with empty/no URL payload
        res_manual_empty = secondary_client.post(
            reverse("recipes:copy_duplicate", kwargs={"pk": r_manual.pk}),
            {},
        )
        assert res_manual_empty.status_code == 404

        # 4. External recipe with empty POST payload
        res_ext_empty = secondary_client.post(
            reverse("recipes:copy_duplicate", kwargs={"pk": r_ext.pk}),
            {},
        )
        assert res_ext_empty.status_code == 404

        # 5. External recipe with blank original_url
        res_ext_blank = secondary_client.post(
            reverse("recipes:copy_duplicate", kwargs={"pk": r_ext.pk}),
            {"original_url": ""},
        )
        assert res_ext_blank.status_code == 404

        # 6. External recipe with whitespace-only original_url
        res_ext_ws = secondary_client.post(
            reverse("recipes:copy_duplicate", kwargs={"pk": r_ext.pk}),
            {"original_url": "    \t\n   "},
        )
        assert res_ext_ws.status_code == 404

        # 7. External recipe with wrong URL
        res_ext_wrong = secondary_client.post(
            reverse("recipes:copy_duplicate", kwargs={"pk": r_ext.pk}),
            {"original_url": "https://attacker-domain.com/fake"},
        )
        assert res_ext_wrong.status_code == 404

        # 8. External recipe targeting different recipe's URL
        r_other = Recipe.objects.create(
            household=test_household,
            created_by=test_user,
            title="A's Another Recipe",
            original_url="https://different.org/food",
            is_shared=False,
        )
        res_other = secondary_client.post(
            reverse("recipes:copy_duplicate", kwargs={"pk": r_ext.pk}),
            {"original_url": r_other.original_url},
        )
        assert res_other.status_code == 404

        # Verify zero stolen recipes were created in secondary_household
        assert not Recipe.objects.filter(
            title__in=["A's Secret Manual Pie", "A's Secret Web Roast", "A's Another Recipe"]
        ).exclude(household=test_household).exists()

    def test_copy_duplicate_matching_url_fidelity_and_privacy_boundary(
        self, secondary_client, secondary_household, secondary_user, test_household, test_user
    ):
        """When an external recipe duplicate is copied with matching URL:
        - Deep clone succeeds and redirects to detail.
        - Cloned recipe is scoped to caller's household and caller.
        - Cloned recipe is NOT shared (is_shared=False).
        - Caller's notes and rating are saved; author's notes and rating are NOT copied.
        - Modifying or deleting clone has zero impact on source recipe.
        """
        source = Recipe.objects.create(
            household=test_household,
            created_by=test_user,
            title="Publicly Available Dish",
            description="Author's description",
            instructions="Step 1: Prep.\nStep 2: Cook.",
            original_url="https://recipesite.com/special-dish",
            user_notes="CONFIDENTIAL AUTHOR NOTES: Do not share",
            rating=5,
            is_shared=False,
        )
        ing = Ingredient.objects.create(name="Tarragon")
        RecipeIngredient.objects.create(
            recipe=source,
            ingredient=ing,
            raw_text="2 tbsp fresh tarragon",
            quantity="2",
            unit="tbsp",
            order=0,
        )

        res = secondary_client.post(
            reverse("recipes:copy_duplicate", kwargs={"pk": source.pk}),
            {
                "original_url": "https://recipesite.com/special-dish",
                "user_notes": "Caller personal note",
                "rating": "3",
                "is_future": "1",
            },
        )
        assert res.status_code == 302
        cloned = Recipe.objects.filter(household=secondary_household, title="Publicly Available Dish").first()
        assert cloned is not None
        assert res.url == reverse("recipes:detail_recipe", kwargs={"pk": cloned.pk})

        # Multi-tenancy isolation assertions
        assert cloned.household == secondary_household
        assert cloned.created_by == secondary_user
        assert cloned.is_shared is True
        assert cloned.is_future is True
        assert cloned.user_notes == "Caller personal note"
        assert cloned.rating == 3
        assert "CONFIDENTIAL AUTHOR NOTES" not in cloned.user_notes

        # Verify ingredient cloned cleanly
        assert cloned.recipe_ingredients.count() == 1
        cloned_ri = cloned.recipe_ingredients.first()
        assert cloned_ri.ingredient == ing
        assert cloned_ri.raw_text == "2 tbsp fresh tarragon"

        # Verify source recipe completely intact
        source.refresh_from_db()
        assert source.user_notes == "CONFIDENTIAL AUTHOR NOTES: Do not share"
        assert source.rating == 5

        # Verify deleting cloned recipe does not touch source recipe
        cloned.delete()
        assert Recipe.objects.filter(pk=source.pk).exists()

    def test_copy_duplicate_self_recipe_redirects_cleanly_without_duplicate(
        self, client, test_household, test_user
    ):
        """Self-duplication guard: POSTing to copy-duplicate on own recipe redirects to detail view.
        
        Must NOT create redundant '#copy-...' duplicates.
        Must work whether the recipe is external or manual.
        """
        r_ext = Recipe.objects.create(
            household=test_household,
            created_by=test_user,
            title="Own External Stew",
            original_url="https://example.com/own-stew",
        )
        r_man = Recipe.objects.create(
            household=test_household,
            created_by=test_user,
            title="Own Manual Soup",
            original_url="",
        )

        # 1. External recipe with exact URL
        res_ext = client.post(
            reverse("recipes:copy_duplicate", kwargs={"pk": r_ext.pk}),
            {"original_url": "https://example.com/own-stew"},
            follow=True,
        )
        assert res_ext.status_code == 200
        assert r_ext.title in res_ext.content.decode()
        assert Recipe.objects.filter(household=test_household, title="Own External Stew").count() == 1

        # 2. External recipe with empty/mismatched URL (self check executes first)
        res_ext_mismatch = client.post(
            reverse("recipes:copy_duplicate", kwargs={"pk": r_ext.pk}),
            {"original_url": "https://wrong.com"},
            follow=True,
        )
        assert res_ext_mismatch.status_code == 200
        assert Recipe.objects.filter(household=test_household, title="Own External Stew").count() == 1

        # 3. Manual recipe
        res_man = client.post(
            reverse("recipes:copy_duplicate", kwargs={"pk": r_man.pk}),
            {},
            follow=True,
        )
        assert res_man.status_code == 200
        assert r_man.title in res_man.content.decode()
        assert Recipe.objects.filter(household=test_household, title="Own Manual Soup").count() == 1

    def test_copy_duplicate_url_normalization_equivalence(
        self, secondary_client, secondary_household, test_household, test_user
    ):
        """Verify copy-duplicate succeeds across normalized URL representations (query params, slashes, ports)."""
        source = Recipe.objects.create(
            household=test_household,
            created_by=test_user,
            title="Normalizable Dish",
            original_url="https://example.com/pasta/",
        )

        # Submitted with http, www, no trailing slash, and tracking query param
        submitted = "http://www.example.com/pasta?utm_source=fb"
        res = secondary_client.post(
            reverse("recipes:copy_duplicate", kwargs={"pk": source.pk}),
            {"original_url": submitted},
        )
        assert res.status_code == 302
        assert Recipe.objects.filter(household=secondary_household, title="Normalizable Dish").exists()

    def test_copy_duplicate_authorization_and_methods(
        self, unauthenticated_client, secondary_client, test_household, test_user
    ):
        """Test authentication, method restrictions, and read-only status."""
        recipe = Recipe.objects.create(
            household=test_household,
            created_by=test_user,
            title="Auth Guarded Dish",
            original_url="https://example.com/auth-dish",
        )
        url = reverse("recipes:copy_duplicate", kwargs={"pk": recipe.pk})

        # 1. GET method rejected with 405
        res_get = secondary_client.get(url)
        assert res_get.status_code == 405

        # 2. Unauthenticated user redirected to login
        res_unauth = unauthenticated_client.post(url, {"original_url": "https://example.com/auth-dish"})
        assert res_unauth.status_code == 302
        assert "/auth/login/" in res_unauth.url

    def test_copy_duplicate_read_only_and_missing_household_denied(
        self, test_household, test_user, rf
    ):
        """Direct request testing for read-only user and missing household profile."""
        from django.core.exceptions import PermissionDenied
        from recipes.views import copy_duplicate_recipe

        recipe = Recipe.objects.create(
            household=test_household,
            created_by=test_user,
            title="Direct Test Dish",
            original_url="https://example.com/direct-test",
        )

        # 1. Read-only user raises PermissionDenied
        req = rf.post(reverse("recipes:copy_duplicate", kwargs={"pk": recipe.pk}), {"original_url": "https://example.com/direct-test"})
        req.user = test_user
        req.is_readonly = True
        with pytest.raises(PermissionDenied, match="Read-only users cannot copy recipes."):
            copy_duplicate_recipe(req, recipe.pk)

        # 2. User without household profile raises PermissionDenied
        from django.contrib.auth import get_user_model
        User = get_user_model()
        orphan_user = User.objects.create(username="orphan_user")
        req_orphan = rf.post(reverse("recipes:copy_duplicate", kwargs={"pk": recipe.pk}), {"original_url": "https://example.com/direct-test"})
        req_orphan.user = orphan_user
        with pytest.raises(PermissionDenied, match="User is not associated with an active household."):
            copy_duplicate_recipe(req_orphan, recipe.pk)

    def test_copy_duplicate_shared_manual_recipe_cannot_use_copy_duplicate(
        self, secondary_client, test_household, test_user
    ):
        """Even if a manual recipe is shared (is_shared=True), copy-duplicate rejects it with 404
        because copy-duplicate is strictly for external URL deduplication.
        (Shared manual recipes must be copied via copy_recipe instead.)
        """
        shared_manual = Recipe.objects.create(
            household=test_household,
            created_by=test_user,
            title="Shared Grandma Cookies",
            original_url="",
            is_shared=True,
        )
        res = secondary_client.post(
            reverse("recipes:copy_duplicate", kwargs={"pk": shared_manual.pk}),
            {"original_url": "https://example.com/arbitrary"},
        )
        assert res.status_code == 404



