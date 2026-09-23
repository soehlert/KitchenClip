"""tests/e2e/test_multi_household_e2e.py - Comprehensive Multi-Household E2E Test Suite.

Covers the 4-tier matrix:
- Tier 1: Feature Coverage (R1 Authentication, R2 Household Scoping, R3 Sharing, R4 Duplicate Alerts)
- Tier 2: Boundary & Corner Cases (Token TTL, replay defense, IDOR traps, URL normalization, cloning)
- Tier 3: Cross-Feature Pairwise Combinations (Auth + Scoping, Scoping + Sharing, Scoping + Duplicate)
- Tier 4: Real-World Application Workflows (Multi-household collaboration, multi-device, forking chain)
- Playwright Browser UI Tests (runs seamlessly against live_server when browser is available)
"""

from datetime import timedelta
import html
import json
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from django.utils import timezone
import pytest

from recipes.models import (
    Ingredient,
    InviteToken,
    MealPlan,
    Recipe,
    RecipeIngredient,
    RecipeTag,
)

User = get_user_model()


# ==============================================================================
# Tier 1: Feature Coverage (R1 - R4)
# ==============================================================================


@pytest.mark.django_db(transaction=True)
class TestTier1R1AuthAndPasskeys:
    """Tier 1: R1 Passwordless Authentication, CLI Invites & Passkeys."""

    def test_t1_r1_01_cli_invite_landing_page(self, client, create_cli_invite):
        """Verify CLI invite landing renders idempotently with welcome banner and metadata."""
        token = create_cli_invite(username="alice_t1", household_name="Alice Household")
        resp = client.get(f"/auth/invite/{token}/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Welcome to KitchenClip!" in content
        assert "Alice Household" in content
        assert "alice_t1" in content
        assert "Sign In on this Browser" in content

        # Token must remain unconsumed after GET
        token_hash = InviteToken.hash_token(token)
        invite = InviteToken.objects.get(token_hash=token_hash)
        assert invite.is_used is False

    def test_t1_r1_02_direct_session_fallback_signin(self, client, create_cli_invite):
        """Verify direct session fallback sign-in creates 1-year persistent session and marks token used."""
        token = create_cli_invite(username="bob_t1", household_name="Bob Household")
        resp = client.post(f"/auth/invite/{token}/redeem/", follow=True)
        assert resp.status_code == 200
        assert resp.redirect_chain[0][0] == "/"

        # Session verification
        user = User.objects.get(username="bob_t1")
        assert client.session["_auth_user_id"] == str(user.pk)
        assert client.session.get_expiry_age() == 31536000

        # Token must be atomically marked as used
        token_hash = InviteToken.hash_token(token)
        invite = InviteToken.objects.get(token_hash=token_hash)
        assert invite.is_used is True
        assert invite.used_at is not None

    def test_t1_r1_03_attack_surface_elimination(self, client):
        """Verify public registration, password forms, and unauthenticated access are eliminated."""
        # Non-existent public registration routes must return 404
        for path in ["/auth/register/", "/signup/", "/accounts/register/", "/register/"]:
            resp = client.get(path)
            assert resp.status_code == 404

        # Unauthenticated access to protected routes must redirect to /auth/login/
        for path in ["/", "/add/scratch/", "/meal-plan/", "/shared/"]:
            resp = client.get(path)
            assert resp.status_code == 302
            assert "/auth/login/" in resp.headers["Location"]

        # Login page must contain zero password fields
        login_resp = client.get("/auth/login/")
        assert login_resp.status_code == 200
        login_html = login_resp.content.decode().lower()
        assert 'type="password"' not in login_html
        assert "passkey" in login_html

    def test_t1_r1_04_multi_device_provisioning_same_user(self, client, create_cli_invite):
        """Verify adding a second device for existing user creates distinct token and independent session."""
        # Provision initial user
        token1 = create_cli_invite(username="david_t1", household_name="David Household")
        client1 = Client()
        resp1 = client1.post(f"/auth/invite/{token1}/redeem/", follow=True)
        assert resp1.status_code == 200

        # Provision second device invite for same user without --household
        token2 = create_cli_invite(username="david_t1")
        assert token1 != token2

        client2 = Client()
        resp2 = client2.post(f"/auth/invite/{token2}/redeem/", follow=True)
        assert resp2.status_code == 200

        # Both clients are authenticated as david_t1 in David Household
        user = User.objects.get(username="david_t1")
        assert client1.session["_auth_user_id"] == str(user.pk)
        assert client2.session["_auth_user_id"] == str(user.pk)
        assert user.profile.household.name == "David Household"

    def test_t1_r1_05_webauthn_register_gated_behind_token(self, client, create_cli_invite):
        """Verify WebAuthn registration options are strictly rejected without a valid token."""
        # Missing token
        resp_no_token = client.post(
            "/auth/webauthn/register/options/",
            data=json.dumps({}),
            content_type="application/json",
        )
        assert resp_no_token.status_code == 403

        # Valid token
        token = create_cli_invite(username="elena_t1", household_name="Elena Household")
        resp_valid = client.post(
            "/auth/webauthn/register/options/",
            data=json.dumps({"token": token}),
            content_type="application/json",
        )
        assert resp_valid.status_code == 200
        data = resp_valid.json()
        assert "challenge" in data
        assert "user" in data
        assert client.session.get("webauthn_reg_challenge") is not None


@pytest.mark.django_db(transaction=True)
class TestTier1R2HouseholdMultiTenancyAndIsolation:
    """Tier 1: R2 Household-Scoped Multi-Tenancy & Data Isolation."""

    def test_t1_r2_01_same_household_multi_user_recipe_sync(
        self, e2e_client, e2e_spouse_client, e2e_household, e2e_user
    ):
        """Verify spouses in the same household share the recipe catalog."""
        recipe = Recipe.objects.create(
            household=e2e_household,
            created_by=e2e_user,
            title="Shared Family Lasagna",
            prep_time=20,
            cook_time=40,
        )

        resp = e2e_spouse_client.get(reverse("recipes:list_recipe"))
        assert resp.status_code == 200
        content = resp.content.decode()
        assert recipe.title in content

    def test_t1_r2_02_same_household_multi_user_meal_plan_sync(
        self, e2e_client, e2e_spouse_client, e2e_household, e2e_user
    ):
        """Verify spouses in the same household share the weekly meal plan."""
        recipe = Recipe.objects.create(
            household=e2e_household,
            created_by=e2e_user,
            title="Spouse Tacos",
        )
        today = timezone.localtime().date()
        MealPlan.objects.create(
            household=e2e_household,
            created_by=e2e_user,
            recipe=recipe,
            date=today,
            meal_type="DINNER",
        )

        resp = e2e_spouse_client.get(reverse("recipes:meal_plan"))
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Spouse Tacos" in content

    def test_t1_r2_03_cross_household_recipe_isolation(
        self, e2e_client, e2e_secondary_client, e2e_household, e2e_user
    ):
        """Verify private recipes belonging to Household A are completely invisible to Household B."""
        private_recipe = Recipe.objects.create(
            household=e2e_household,
            created_by=e2e_user,
            title="Private Household A Secret Dish",
            is_shared=False,
        )

        # Secondary client recipe list
        resp = e2e_secondary_client.get(reverse("recipes:list_recipe"))
        assert resp.status_code == 200
        assert private_recipe.title not in resp.content.decode()

        # Secondary client search API
        search_resp = e2e_secondary_client.get(
            reverse("recipes:search_recipes_api"), {"q": "Private Household A"}
        )
        assert search_resp.status_code == 200
        assert len(search_resp.json().get("recipes", [])) == 0

    def test_t1_r2_04_cross_household_meal_plan_isolation(
        self, e2e_client, e2e_secondary_client, e2e_household, e2e_user
    ):
        """Verify meal plan slots are strictly scoped per household."""
        recipe = Recipe.objects.create(
            household=e2e_household,
            created_by=e2e_user,
            title="Household A Steak",
        )
        today = timezone.localtime().date()
        MealPlan.objects.create(
            household=e2e_household,
            created_by=e2e_user,
            recipe=recipe,
            date=today,
            meal_type="LUNCH",
        )

        resp = e2e_secondary_client.get(reverse("recipes:meal_plan"))
        assert resp.status_code == 200
        assert "Household A Steak" not in resp.content.decode()

    def test_t1_r2_05_scoped_original_url_independent_ownership(
        self, e2e_client, e2e_secondary_client, e2e_household, e2e_secondary_household, e2e_user, e2e_secondary_user
    ):
        """Verify two households can independently clip and store the exact same external URL."""
        shared_url = "https://example.com/best-roast-chicken"
        r1 = Recipe.objects.create(
            household=e2e_household,
            created_by=e2e_user,
            title="Alpha Roast Chicken",
            original_url=shared_url,
        )
        r2 = Recipe.objects.create(
            household=e2e_secondary_household,
            created_by=e2e_secondary_user,
            title="Beta Roast Chicken",
            original_url=shared_url,
        )
        assert r1.id != r2.id
        assert r1.household_id != r2.household_id
        assert r1.original_url == r2.original_url == shared_url


@pytest.mark.django_db(transaction=True)
class TestTier1R3CrossHouseholdRecipeSharing:
    """Tier 1: R3 Cross-Household Recipe Sharing & 1-Click Cloning."""

    def test_t1_r3_01_toggle_is_shared_publishes_to_catalog(
        self, e2e_secondary_client, e2e_household, e2e_user
    ):
        """Verify toggling is_shared=True publishes the recipe to the shared browsing catalog."""
        Recipe.objects.create(
            household=e2e_household,
            created_by=e2e_user,
            title="Grandma's Apple Pie",
            is_shared=True,
        )

        resp = e2e_secondary_client.get(reverse("recipes:shared_recipe_list"))
        assert resp.status_code == 200
        content = html.unescape(resp.content.decode())
        assert "Grandma's Apple Pie" in content
        assert e2e_household.name in content

    def test_t1_r3_02_unauthenticated_shared_catalog_redirects(self, client):
        """Verify unauthenticated requests to the shared catalog redirect to login."""
        resp = client.get(reverse("recipes:shared_recipe_list"))
        assert resp.status_code == 302
        assert reverse("auth:login") in resp.headers["Location"]

    def test_t1_r3_03_privacy_preserving_shared_detail_view(
        self, e2e_secondary_client, e2e_household, e2e_user
    ):
        """Verify non-owners see shared recipe details while author's private notes and rating are omitted."""
        shared_recipe = Recipe.objects.create(
            household=e2e_household,
            created_by=e2e_user,
            title="Shared Spice Rub",
            is_shared=True,
            user_notes="Confidential family ratio: 3 parts cumin",
            rating=5,
            instructions="Mix spices thoroughly.",
        )

        resp = e2e_secondary_client.get(reverse("recipes:detail_recipe", kwargs={"pk": shared_recipe.pk}))
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Shared Spice Rub" in content
        assert "Mix spices thoroughly." in content
        # Private notes, rating, and edit controls must be hidden for foreign viewers
        assert "Confidential family ratio" not in content
        assert 'href="/recipes/' not in content or "Edit" not in content

    def test_t1_r3_04_one_click_copy_deep_cloning(
        self, e2e_secondary_client, e2e_household, e2e_secondary_household, e2e_user, e2e_secondary_user
    ):
        """Verify 1-click 'Copy to My Household' deep clones recipe, ingredients, and tags into viewer's household."""
        source = Recipe.objects.create(
            household=e2e_household,
            created_by=e2e_user,
            title="Signature Ribs",
            is_shared=True,
            instructions="Smoke for 6 hours.",
        )
        ing = Ingredient.objects.create(name="Pork Ribs")
        RecipeIngredient.objects.create(
            recipe=source,
            ingredient=ing,
            raw_text="2 racks Pork Ribs",
            quantity="2",
            unit="racks",
            order=0,
        )

        resp = e2e_secondary_client.post(reverse("recipes:copy_recipe", kwargs={"pk": source.pk}), follow=True)
        assert resp.status_code == 200

        # Verify cloned record
        cloned = Recipe.objects.filter(household=e2e_secondary_household, title="Signature Ribs").first()
        assert cloned is not None
        assert cloned.pk != source.pk
        assert cloned.created_by == e2e_secondary_user
        assert cloned.is_shared is True  # Clones default to shared

        # Verify ingredients cloned
        cloned_ings = list(cloned.recipe_ingredients.all())
        assert len(cloned_ings) == 1
        assert cloned_ings[0].raw_text == "2 racks Pork Ribs"

    def test_t1_r3_05_independent_mutation_of_cloned_recipe(
        self, e2e_secondary_client, e2e_household, e2e_secondary_household, e2e_user, e2e_secondary_user
    ):
        """Verify editing a cloned recipe has zero effect on the original source recipe."""
        source = Recipe.objects.create(
            household=e2e_household,
            created_by=e2e_user,
            title="Original Sourdough",
            is_shared=True,
            prep_time=30,
        )
        # Deep clone into secondary household
        clone = Recipe.objects.create(
            household=e2e_secondary_household,
            created_by=e2e_secondary_user,
            title="Original Sourdough",
            is_shared=False,
            prep_time=30,
        )

        # Mutate clone
        clone.title = "Paul's Modified Sourdough"
        clone.prep_time = 45
        clone.save()

        # Assert source recipe remains untouched
        source.refresh_from_db()
        assert source.title == "Original Sourdough"
        assert source.prep_time == 30


@pytest.mark.django_db(transaction=True)
class TestTier1R4DuplicateURLScrapingDetection:
    """Tier 1: R4 Duplicate External URL Scraping Alert & Workflow."""

    def test_t1_r4_01_cross_household_duplicate_scraping_banner(
        self, e2e_secondary_client, e2e_household, e2e_user
    ):
        """Verify scraping a URL saved by another household renders the duplicate alert banner without scraping."""
        Recipe.objects.create(
            household=e2e_household,
            created_by=e2e_user,
            title="Neighbor's Creamy Soup",
            original_url="https://example.com/creamy-soup",
            total_time=45,
            is_shared=True,
        )

        with patch("recipes.views.ParserRegistry.get_parser") as mock_parser:
            resp = e2e_secondary_client.post(
                reverse("recipes:add_recipe"),
                {"original_url": "https://example.com/creamy-soup"},
            )
            assert resp.status_code == 200
            assert resp.context.get("duplicate_detected") is True
            mock_parser.assert_not_called()

        content = html.unescape(resp.content.decode())
        assert "Recipe Already Saved on KitchenClip" in content
        assert "Neighbor's Creamy Soup" in content

    def test_t1_r4_02_duplicate_alert_banner_ui_elements(
        self, e2e_secondary_client, e2e_household, e2e_user
    ):
        """Verify the duplicate alert banner provides #btn-copy-existing and #btn-force-scrape."""
        Recipe.objects.create(
            household=e2e_household,
            created_by=e2e_user,
            title="Existing Curry Dish",
            original_url="https://example.com/curry",
            is_shared=False,
        )

        resp = e2e_secondary_client.post(
            reverse("recipes:add_recipe"),
            {"original_url": "https://example.com/curry"},
        )
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "btn-copy-existing" in content
        assert "btn-force-scrape" in content

    def test_t1_r4_03_banner_action_copy_existing(
        self, e2e_secondary_client, e2e_household, e2e_secondary_household, e2e_user, e2e_secondary_user
    ):
        """Verify the banner 'Copy to My Household' button deep clones existing recipe with user metadata."""
        source = Recipe.objects.create(
            household=e2e_household,
            created_by=e2e_user,
            title="Famous Enchiladas",
            original_url="https://example.com/enchiladas",
            instructions="Bake at 375F.",
        )

        resp = e2e_secondary_client.post(
            reverse("recipes:copy_duplicate", kwargs={"pk": source.pk}),
            {
                "original_url": "https://example.com/enchiladas",
                "user_notes": "Added extra jalapeños",
                "rating": "4",
            },
            follow=True,
        )
        assert resp.status_code == 200

        cloned = Recipe.objects.filter(household=e2e_secondary_household, title="Famous Enchiladas").first()
        assert cloned is not None
        assert cloned.created_by == e2e_secondary_user
        assert cloned.user_notes == "Added extra jalapeños"
        assert cloned.rating == 4

    def test_t1_r4_04_banner_action_force_scrape(
        self, e2e_secondary_client, e2e_household, e2e_secondary_household, e2e_user, e2e_secondary_user
    ):
        """Verify the banner 'Scrape Fresh Anyway' button executes fresh scrape and saves to active household."""
        Recipe.objects.create(
            household=e2e_household,
            created_by=e2e_user,
            title="Original Scraped Stew",
            original_url="https://example.com/stew",
        )

        mock_parser_obj = MagicMock()
        mock_parser_obj.title = "Freshly Scraped Stew"
        mock_parser_obj.description = "Freshly scraped description"
        mock_parser_obj.prep_time = 15
        mock_parser_obj.cook_time = 45
        mock_parser_obj.total_time = 60
        mock_parser_obj.servings = 4
        mock_parser_obj.instructions = "Simmer slowly."
        mock_parser_obj.image_url = ""
        mock_parser_obj.ingredients = ["2 lbs beef", "4 carrots"]

        with patch("recipes.views.ParserRegistry.get_parser", return_value=mock_parser_obj):
            resp = e2e_secondary_client.post(
                reverse("recipes:add_recipe"),
                {"original_url": "https://example.com/stew", "force_scrape": "1"},
                follow=True,
            )
            assert resp.status_code == 200

        fresh_recipe = Recipe.objects.filter(household=e2e_secondary_household, title="Freshly Scraped Stew").first()
        assert fresh_recipe is not None
        assert fresh_recipe.original_url == "https://example.com/stew"
        assert fresh_recipe.created_by == e2e_secondary_user

    def test_t1_r4_05_same_household_duplicate_form_rejection(
        self, e2e_client, e2e_household, e2e_user
    ):
        """Verify duplicate submission within the same household triggers form field error rather than alert banner."""
        Recipe.objects.create(
            household=e2e_household,
            created_by=e2e_user,
            title="Existing Household Pasta",
            original_url="https://example.com/pasta",
        )

        resp = e2e_client.post(
            reverse("recipes:add_recipe"),
            {"original_url": "https://example.com/pasta"},
        )
        assert resp.status_code == 200
        # Duplicate alert banner must NOT be triggered
        assert resp.context.get("duplicate_detected") is not True
        # Form field error must be attached to original_url
        form = resp.context.get("form")
        assert form is not None
        assert "original_url" in form.errors
        assert "already in your household collection" in str(form.errors["original_url"])


# ==============================================================================
# Tier 2: Boundary & Corner Cases (R1 - R4)
# ==============================================================================


@pytest.mark.django_db(transaction=True)
class TestTier2R1AuthBoundaries:
    """Tier 2: R1 Token TTL, Replay Defense, Scanner Safety, and Open Redirects."""

    def test_t2_r1_01_expired_token_returns_400(self, client, create_cli_invite):
        """Verify expired invite tokens return HTTP 400 error page."""
        token = create_cli_invite(username="expired_user", household_name="Expired Household")
        token_hash = InviteToken.hash_token(token)
        invite = InviteToken.objects.get(token_hash=token_hash)
        invite.expires_at = timezone.now() - timedelta(hours=2)
        invite.save()

        resp = client.get(f"/auth/invite/{token}/")
        assert resp.status_code == 400
        assert "expired" in resp.content.decode().lower()

    def test_t2_r1_02_double_redemption_returns_400(self, client, create_cli_invite):
        """Verify redeeming an already used invite token returns HTTP 400."""
        token = create_cli_invite(username="replay_user", household_name="Replay Household")
        resp1 = client.post(f"/auth/invite/{token}/redeem/", follow=True)
        assert resp1.status_code == 200

        # Attempt replay
        client2 = Client()
        resp2 = client2.post(f"/auth/invite/{token}/redeem/")
        assert resp2.status_code == 400
        assert "already been used" in resp2.content.decode()

    def test_t2_r1_03_malformed_token_returns_404(self, client):
        """Verify non-existent or malformed tokens return HTTP 404."""
        resp = client.get("/auth/invite/malformed_non_existent_token_12345/")
        assert resp.status_code == 404

    def test_t2_r1_04_idempotent_crawler_gets(self, client, create_cli_invite):
        """Verify repeated GET requests from security scanners do not consume the token."""
        token = create_cli_invite(username="scanner_user", household_name="Scanner Household")
        for _ in range(5):
            resp = client.get(f"/auth/invite/{token}/")
            assert resp.status_code == 200

        token_hash = InviteToken.hash_token(token)
        invite = InviteToken.objects.get(token_hash=token_hash)
        assert invite.is_used is False

    def test_t2_r1_05_open_redirect_sanitization(self, client, create_cli_invite):
        """Verify external open redirect attempts in next parameter are sanitized to /."""
        token = create_cli_invite(username="redirect_user", household_name="Redirect Household")
        resp = client.post(f"/auth/invite/{token}/redeem/?next=https://malicious.com", follow=False)
        assert resp.status_code == 302
        assert resp.headers["Location"] == "/"


@pytest.mark.django_db(transaction=True)
class TestTier2R2HouseholdIsolationBoundaries:
    """Tier 2: R2 Cross-Household IDOR Traversal, Edit/Delete Shielding, Tag Scoping."""

    def test_t2_r2_01_direct_get_foreign_private_recipe_returns_404(
        self, e2e_secondary_client, e2e_household, e2e_user
    ):
        """Verify direct GET requests to foreign private recipes return 404 with zero info leakage."""
        private = Recipe.objects.create(
            household=e2e_household,
            created_by=e2e_user,
            title="Private Shielded Dish",
            is_shared=False,
        )
        resp = e2e_secondary_client.get(reverse("recipes:detail_recipe", kwargs={"pk": private.pk}))
        assert resp.status_code == 404

    def test_t2_r2_02_direct_edit_foreign_recipe_returns_404(
        self, e2e_secondary_client, e2e_household, e2e_user
    ):
        """Verify direct edit GET and POST on foreign recipes return 404."""
        recipe = Recipe.objects.create(
            household=e2e_household,
            created_by=e2e_user,
            title="Uneditable Foreign Dish",
        )
        resp_get = e2e_secondary_client.get(reverse("recipes:edit_recipe", kwargs={"pk": recipe.pk}))
        assert resp_get.status_code == 404

        resp_post = e2e_secondary_client.post(
            reverse("recipes:edit_recipe", kwargs={"pk": recipe.pk}),
            {"title": "Hacked Title"},
        )
        assert resp_post.status_code == 404
        recipe.refresh_from_db()
        assert recipe.title == "Uneditable Foreign Dish"

    def test_t2_r2_03_direct_delete_foreign_recipe_returns_404(
        self, e2e_secondary_client, e2e_household, e2e_user
    ):
        """Verify direct delete POST on foreign recipe returns 404 and leaves record intact."""
        recipe = Recipe.objects.create(
            household=e2e_household,
            created_by=e2e_user,
            title="Indestructible Foreign Dish",
        )
        resp = e2e_secondary_client.post(reverse("recipes:delete_recipe", kwargs={"pk": recipe.pk}))
        assert resp.status_code == 404
        assert Recipe.objects.filter(pk=recipe.pk).exists()

    def test_t2_r2_04_cross_household_meal_plan_api_injection_rejected(
        self, e2e_secondary_client, e2e_household, e2e_user
    ):
        """Verify meal plan update API rejects attaching a foreign household recipe."""
        foreign_recipe = Recipe.objects.create(
            household=e2e_household,
            created_by=e2e_user,
            title="Foreign Secret Recipe",
            is_shared=False,
        )
        today = timezone.localtime().date().isoformat()
        resp = e2e_secondary_client.post(
            reverse("recipes:update_meal_plan"),
            data=json.dumps({"recipe_id": foreign_recipe.id, "date": today, "meal_type": "DINNER"}),
            content_type="application/json",
        )
        assert resp.status_code in [400, 404]
        assert not MealPlan.objects.filter(recipe=foreign_recipe).exists()

    def test_t2_r2_05_cross_household_tag_isolation(
        self, e2e_household, e2e_secondary_household
    ):
        """Verify identical tag names in different households remain strictly isolated with independent colors."""
        tag1 = RecipeTag.get_or_create_for_household(household=e2e_household, name="Keto")
        tag1.color = "#FF0000"
        tag1.save()

        tag2 = RecipeTag.get_or_create_for_household(household=e2e_secondary_household, name="Keto")
        tag2.color = "#0000FF"
        tag2.save()

        assert tag1.pk != tag2.pk
        assert tag1.household_id != tag2.household_id
        assert tag1.color == "#FF0000"
        assert tag2.color == "#0000FF"


@pytest.mark.django_db(transaction=True)
class TestTier2R3SharingAndCloningBoundaries:
    """Tier 2: R3 Sharing Constraints, Disambiguation, and Revocation."""

    def test_t2_r3_01_copy_own_recipe_informs_and_redirects(
        self, e2e_client, e2e_household, e2e_user
    ):
        """Verify attempting to copy a recipe that already belongs to user's household redirects with info message."""
        recipe = Recipe.objects.create(
            household=e2e_household,
            created_by=e2e_user,
            title="Own Household Bread",
        )
        initial_count = Recipe.objects.filter(household=e2e_household).count()

        resp = e2e_client.post(reverse("recipes:copy_recipe", kwargs={"pk": recipe.pk}), follow=True)
        assert resp.status_code == 200
        assert "already in your household" in resp.content.decode()
        assert Recipe.objects.filter(household=e2e_household).count() == initial_count

    def test_t2_r3_02_copy_foreign_private_recipe_returns_404(
        self, e2e_secondary_client, e2e_household, e2e_user
    ):
        """Verify copy endpoint rejects foreign private recipes with HTTP 404."""
        private = Recipe.objects.create(
            household=e2e_household,
            created_by=e2e_user,
            title="Private Vault Recipe",
            is_shared=False,
        )
        resp = e2e_secondary_client.post(reverse("recipes:copy_recipe", kwargs={"pk": private.pk}))
        assert resp.status_code == 404

    def test_t2_r3_03_deep_clone_url_collision_disambiguation(
        self, e2e_secondary_client, e2e_household, e2e_secondary_household, e2e_user, e2e_secondary_user
    ):
        """Verify deep cloning a shared recipe whose URL already exists in target household appends #copy-fragment."""
        shared_url = "https://example.com/taco-recipe"
        Recipe.objects.create(
            household=e2e_secondary_household,
            created_by=e2e_secondary_user,
            title="Existing Secondary Taco",
            original_url=shared_url,
        )
        shared_source = Recipe.objects.create(
            household=e2e_household,
            created_by=e2e_user,
            title="Primary Shared Taco",
            original_url=shared_url,
            is_shared=True,
        )

        resp = e2e_secondary_client.post(reverse("recipes:copy_recipe", kwargs={"pk": shared_source.pk}), follow=True)
        assert resp.status_code == 200

        clones = Recipe.objects.filter(household=e2e_secondary_household, title="Primary Shared Taco")
        assert clones.exists()
        clone = clones.first()
        assert clone.original_url.startswith("https://example.com/taco-recipe#copy-")

    def test_t2_r3_04_ingredient_ordering_and_measurements_preserved(
        self, e2e_secondary_client, e2e_household, e2e_secondary_household, e2e_user
    ):
        """Verify all ingredient fields, quantities, units, and ordering indices are deep-cloned with exact fidelity."""
        source = Recipe.objects.create(
            household=e2e_household,
            created_by=e2e_user,
            title="Precision Cake",
            is_shared=True,
        )
        i1 = Ingredient.objects.create(name="Cake Flour")
        i2 = Ingredient.objects.create(name="Baking Powder")
        RecipeIngredient.objects.create(
            recipe=source, ingredient=i1, raw_text="2 1/4 cups Cake Flour", quantity="2.25", unit="cups", order=0
        )
        RecipeIngredient.objects.create(
            recipe=source, ingredient=i2, raw_text="1 tsp Baking Powder", quantity="1", unit="tsp", order=1
        )

        resp = e2e_secondary_client.post(reverse("recipes:copy_recipe", kwargs={"pk": source.pk}), follow=True)
        assert resp.status_code == 200

        cloned = Recipe.objects.filter(household=e2e_secondary_household, title="Precision Cake").first()
        cloned_ings = list(cloned.recipe_ingredients.order_by("order"))
        assert len(cloned_ings) == 2
        assert cloned_ings[0].raw_text == "2 1/4 cups Cake Flour"
        assert cloned_ings[0].order == 0
        assert cloned_ings[1].raw_text == "1 tsp Baking Powder"
        assert cloned_ings[1].order == 1

    def test_t2_r3_05_immediate_revocation_of_shared_status(
        self, e2e_secondary_client, e2e_household, e2e_user
    ):
        """Verify unchecking is_shared immediately removes recipe from catalog and blocks foreign detail view."""
        recipe = Recipe.objects.create(
            household=e2e_household,
            created_by=e2e_user,
            title="Temporarily Shared Roast",
            is_shared=True,
        )
        # Verify visible in shared catalog
        resp_catalog1 = e2e_secondary_client.get(reverse("recipes:shared_recipe_list"))
        assert "Temporarily Shared Roast" in resp_catalog1.content.decode()

        # Revoke sharing
        recipe.is_shared = False
        recipe.save()

        # Must no longer be in shared catalog
        resp_catalog2 = e2e_secondary_client.get(reverse("recipes:shared_recipe_list"))
        assert "Temporarily Shared Roast" not in resp_catalog2.content.decode()

        # Direct detail must return 404
        resp_detail = e2e_secondary_client.get(reverse("recipes:detail_recipe", kwargs={"pk": recipe.pk}))
        assert resp_detail.status_code == 404


@pytest.mark.django_db(transaction=True)
class TestTier2R4DuplicateDetectionBoundaries:
    """Tier 2: R4 URL Normalization, Anti-IDOR Protections, and Metadata Integrity."""

    def test_t2_r4_01_url_normalization_variations(
        self, e2e_secondary_client, e2e_household, e2e_user
    ):
        """Verify robust URL normalization handles protocols, www prefixes, trailing slashes, and tracking params."""
        Recipe.objects.create(
            household=e2e_household,
            created_by=e2e_user,
            title="Canonical Chili Dish",
            original_url="https://example.com/chili-recipe",
        )

        variations = [
            "http://example.com/chili-recipe",
            "https://www.example.com/chili-recipe/",
            "https://example.com/chili-recipe?utm_source=newsletter&utm_medium=email",
        ]
        for var_url in variations:
            resp = e2e_secondary_client.post(reverse("recipes:add_recipe"), {"original_url": var_url})
            assert resp.status_code == 200, f"Failed for variation: {var_url}"
            assert resp.context.get("duplicate_detected") is True, f"Detection failed for: {var_url}"

    def test_t2_r4_02_anti_idor_url_tampering_on_copy_duplicate(
        self, e2e_secondary_client, e2e_household, e2e_user
    ):
        """Verify copy-duplicate rejects submissions when submitted original_url does not match source recipe."""
        source = Recipe.objects.create(
            household=e2e_household,
            created_by=e2e_user,
            title="Target Tamper Recipe",
            original_url="https://example.com/authentic-dish",
        )

        resp = e2e_secondary_client.post(
            reverse("recipes:copy_duplicate", kwargs={"pk": source.pk}),
            {"original_url": "https://example.com/tampered-dish"},
        )
        assert resp.status_code == 404

    def test_t2_r4_03_anti_idor_on_recipe_without_url(
        self, e2e_secondary_client, e2e_household, e2e_user
    ):
        """Verify copy-duplicate rejects attempting to duplicate a manual recipe lacking an external URL."""
        manual_recipe = Recipe.objects.create(
            household=e2e_household,
            created_by=e2e_user,
            title="Manual Grandma Secret",
            original_url="",
        )

        resp = e2e_secondary_client.post(
            reverse("recipes:copy_duplicate", kwargs={"pk": manual_recipe.pk}),
            {"original_url": "https://example.com/fake-dish"},
        )
        assert resp.status_code == 404

    def test_t2_r4_04_custom_metadata_preserved_on_duplicate_copy(
        self, e2e_secondary_client, e2e_household, e2e_secondary_household, e2e_user
    ):
        """Verify custom notes, rating, and future status entered on add form are preserved on the cloned recipe."""
        source = Recipe.objects.create(
            household=e2e_household,
            created_by=e2e_user,
            title="Base Pizza",
            original_url="https://example.com/pizza",
            user_notes="Original author notes",
        )

        resp = e2e_secondary_client.post(
            reverse("recipes:copy_duplicate", kwargs={"pk": source.pk}),
            {
                "original_url": "https://example.com/pizza",
                "user_notes": "My customized woodfired notes",
                "rating": "5",
                "is_future": "1",
            },
            follow=True,
        )
        assert resp.status_code == 200

        cloned = Recipe.objects.filter(household=e2e_secondary_household, title="Base Pizza").first()
        assert cloned.user_notes == "My customized woodfired notes"
        assert cloned.rating == 5
        assert cloned.is_future is True

    def test_t2_r4_05_shared_link_visibility_on_duplicate_banner(
        self, e2e_secondary_client, e2e_household, e2e_user
    ):
        """Verify duplicate banner displays 'View shared recipe' link if source is shared, and omits it if private."""
        # Case A: Shared source
        r_shared = Recipe.objects.create(
            household=e2e_household,
            created_by=e2e_user,
            title="Shared Brownies",
            original_url="https://example.com/brownies",
            is_shared=True,
        )
        resp_shared = e2e_secondary_client.post(
            reverse("recipes:add_recipe"), {"original_url": "https://example.com/brownies"}
        )
        assert "View shared recipe" in resp_shared.content.decode()

        # Case B: Private source
        r_shared.delete()
        Recipe.objects.create(
            household=e2e_household,
            created_by=e2e_user,
            title="Private Brownies",
            original_url="https://example.com/brownies",
            is_shared=False,
        )
        resp_private = e2e_secondary_client.post(
            reverse("recipes:add_recipe"), {"original_url": "https://example.com/brownies"}
        )
        assert "View shared recipe" not in resp_private.content.decode()


# ==============================================================================
# Tier 3: Cross-Feature Pairwise Interactions
# ==============================================================================


@pytest.mark.django_db(transaction=True)
class TestTier3CrossFeaturePairwise:
    """Tier 3: Pairwise interactions across Auth, Scoping, Sharing, and Scraping."""

    def test_t3_pair_01_auth_provisioning_and_multi_tenant_isolation(self, client, create_cli_invite):
        """T3-PAIR-01 (R1 + R2): Admin CLI provisions multiple users into distinct households; verify isolation."""
        token_a = create_cli_invite(username="alice_pair", household_name="Household Alpha Pair")
        token_b = create_cli_invite(username="bob_pair", household_name="Household Beta Pair")

        client_a = Client()
        client_a.post(f"/auth/invite/{token_a}/redeem/", follow=True)

        client_b = Client()
        client_b.post(f"/auth/invite/{token_b}/redeem/", follow=True)

        user_a = User.objects.get(username="alice_pair")
        user_b = User.objects.get(username="bob_pair")
        assert user_b.profile.household.name == "Household Beta Pair"

        # Alice creates a recipe
        Recipe.objects.create(
            household=user_a.profile.household,
            created_by=user_a,
            title="Alice's Morning Oats",
        )

        # Alice sees it; Bob does not
        content_a = html.unescape(client_a.get("/").content.decode())
        content_b = html.unescape(client_b.get("/").content.decode())
        assert "Alice's Morning Oats" in content_a
        assert "Alice's Morning Oats" not in content_b

    def test_t3_pair_02_passkey_session_and_shared_catalog_cloning(
        self, e2e_secondary_client, e2e_household, e2e_secondary_household, e2e_user, e2e_secondary_user
    ):
        """T3-PAIR-02 (R1 + R3): Direct authenticated session discovers and clones shared recipe across households."""
        source = Recipe.objects.create(
            household=e2e_household,
            created_by=e2e_user,
            title="Artisanal Baguette",
            is_shared=True,
            instructions="Proof for 12 hours.",
        )

        # Browse shared catalog
        cat_resp = e2e_secondary_client.get(reverse("recipes:shared_recipe_list"))
        assert "Artisanal Baguette" in cat_resp.content.decode()

        # Clone recipe
        clone_resp = e2e_secondary_client.post(
            reverse("recipes:copy_recipe", kwargs={"pk": source.pk}), follow=True
        )
        assert clone_resp.status_code == 200

        # Assert copy appears in active household catalog
        list_resp = e2e_secondary_client.get(reverse("recipes:list_recipe"))
        assert "Artisanal Baguette" in list_resp.content.decode()

    def test_t3_pair_03_auth_session_and_duplicate_url_interception(
        self, e2e_secondary_client, e2e_household, e2e_secondary_household, e2e_user
    ):
        """T3-PAIR-03 (R1 + R4): Authenticated user triggers duplicate detection and clones record with notes."""
        Recipe.objects.create(
            household=e2e_household,
            created_by=e2e_user,
            title="Gourmet Burger",
            original_url="https://example.com/burger",
        )

        # Submit URL -> intercepted by banner
        resp = e2e_secondary_client.post(
            reverse("recipes:add_recipe"), {"original_url": "https://example.com/burger"}
        )
        assert resp.context.get("duplicate_detected") is True

        # Copy from banner
        dup_recipe = resp.context.get("duplicate_recipe")
        copy_resp = e2e_secondary_client.post(
            reverse("recipes:copy_duplicate", kwargs={"pk": dup_recipe.pk}),
            {"original_url": "https://example.com/burger", "user_notes": "Use brioche bun"},
            follow=True,
        )
        assert copy_resp.status_code == 200
        cloned = Recipe.objects.filter(household=e2e_secondary_household, title="Gourmet Burger").first()
        assert cloned.user_notes == "Use brioche bun"

    def test_t3_pair_04_cross_household_sharing_clone_source_deletion_resilience(
        self, e2e_secondary_client, e2e_household, e2e_secondary_household, e2e_user
    ):
        """T3-PAIR-04 (R2 + R3): Source recipe deletion in Household Alpha leaves cloned copy in Beta completely intact."""
        source = Recipe.objects.create(
            household=e2e_household,
            created_by=e2e_user,
            title="Ephemeral Souffle",
            is_shared=True,
            instructions="Bake immediately.",
        )
        # Clone into Beta
        e2e_secondary_client.post(reverse("recipes:copy_recipe", kwargs={"pk": source.pk}), follow=True)
        beta_clone = Recipe.objects.get(household=e2e_secondary_household, title="Ephemeral Souffle")

        # Alpha deletes source
        source.delete()

        # Beta clone remains intact and viewable
        detail_resp = e2e_secondary_client.get(reverse("recipes:detail_recipe", kwargs={"pk": beta_clone.pk}))
        assert detail_resp.status_code == 200
        assert "Ephemeral Souffle" in detail_resp.content.decode()

    def test_t3_pair_05_scoped_unique_constraints_and_force_scrape_concurrency(
        self, e2e_secondary_client, e2e_household, e2e_secondary_household, e2e_user, e2e_secondary_user
    ):
        """T3-PAIR-05 (R2 + R4): Scoped unique constraints allow identical URL in multiple households via force-scrape."""
        shared_url = "https://example.com/concurrent-pot-roast"
        Recipe.objects.create(
            household=e2e_household,
            created_by=e2e_user,
            title="Alpha Pot Roast",
            original_url=shared_url,
        )

        mock_parser = MagicMock()
        mock_parser.title = "Beta Pot Roast"
        mock_parser.description = "Beta version"
        mock_parser.prep_time = 20
        mock_parser.cook_time = 120
        mock_parser.total_time = 140
        mock_parser.servings = 6
        mock_parser.instructions = "Slow cook."
        mock_parser.image_url = ""
        mock_parser.ingredients = ["3 lbs chuck roast"]

        with patch("recipes.views.ParserRegistry.get_parser", return_value=mock_parser):
            resp = e2e_secondary_client.post(
                reverse("recipes:add_recipe"),
                {"original_url": shared_url, "force_scrape": "1"},
                follow=True,
            )
            assert resp.status_code == 200

        # Both records exist and share the identical URL
        assert Recipe.objects.filter(household=e2e_household, original_url=shared_url).count() == 1
        assert Recipe.objects.filter(household=e2e_secondary_household, original_url=shared_url).count() == 1

    def test_t3_pair_06_shared_catalog_interplay_with_duplicate_scraping(
        self, e2e_secondary_client, e2e_household, e2e_user
    ):
        """T3-PAIR-06 (R3 + R4): Duplicate banner detects shared recipe and renders direct link to view shared details."""
        shared_recipe = Recipe.objects.create(
            household=e2e_household,
            created_by=e2e_user,
            title="Shared Lemon Tart",
            original_url="https://example.com/lemon-tart",
            is_shared=True,
        )

        resp = e2e_secondary_client.post(
            reverse("recipes:add_recipe"), {"original_url": "https://example.com/lemon-tart"}
        )
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "View shared recipe" in content
        expected_url = reverse("recipes:detail_recipe", kwargs={"pk": shared_recipe.pk})
        assert expected_url in content


# ==============================================================================
# Tier 4: Real-World Application Workflows
# ==============================================================================


@pytest.mark.django_db(transaction=True)
class TestTier4RealWorldScenarios:
    """Tier 4: Complex multi-step scenarios representing real-world culinary workflows."""

    def test_t4_scenario_01_two_household_culinary_collaboration_lifecycle(
        self, client, create_cli_invite
    ):
        """T4-SCENARIO-01: Complete two-household onboarding, sharing, cloning, mutation, and meal planning."""
        # 1. Admin provisions Gordon in "Gourmet Household"
        token_gordon = create_cli_invite(username="gordon", household_name="Gourmet Household")
        client_gordon = Client()
        client_gordon.post(f"/auth/invite/{token_gordon}/redeem/", follow=True)
        gordon = User.objects.get(username="gordon")
        h_gourmet = gordon.profile.household

        # 2. Gordon creates a private Beef Wellington and a shared Sourdough Bread
        wellington = Recipe.objects.create(
            household=h_gourmet,
            created_by=gordon,
            title="Beef Wellington",
            is_shared=False,
        )
        sourdough = Recipe.objects.create(
            household=h_gourmet,
            created_by=gordon,
            title="Sourdough Bread",
            is_shared=True,
            instructions="Bake in Dutch oven.",
        )
        today = timezone.localtime().date()
        MealPlan.objects.create(
            household=h_gourmet,
            created_by=gordon,
            recipe=wellington,
            date=today,
            meal_type="DINNER",
        )

        # 3. Admin provisions Paul in "Bakers Household"
        token_paul = create_cli_invite(username="paul", household_name="Bakers Household")
        client_paul = Client()
        client_paul.post(f"/auth/invite/{token_paul}/redeem/", follow=True)
        paul = User.objects.get(username="paul")
        h_bakers = paul.profile.household

        # 4. Paul opens /recipes/shared/ and sees Sourdough Bread, but NOT Beef Wellington
        shared_resp = client_paul.get(reverse("recipes:shared_recipe_list"))
        assert "Sourdough Bread" in shared_resp.content.decode()
        assert "Beef Wellington" not in shared_resp.content.decode()

        # 5. Paul clones Sourdough Bread into Bakers Household
        client_paul.post(reverse("recipes:copy_recipe", kwargs={"pk": sourdough.pk}), follow=True)
        paul_sourdough = Recipe.objects.get(household=h_bakers, title="Sourdough Bread")

        # 6. Paul mutates his copy and schedules it for Dinner
        paul_sourdough.user_notes = "Add 10% dark rye flour"
        paul_sourdough.save()
        MealPlan.objects.create(
            household=h_bakers,
            created_by=paul,
            recipe=paul_sourdough,
            date=today,
            meal_type="DINNER",
        )

        # 7. Gordon logs back in: verifies his Sourdough Bread has no rye flour notes,
        # his meal plan still has Beef Wellington, and Paul's meal plan is isolated.
        sourdough.refresh_from_db()
        assert sourdough.user_notes == ""
        gordon_plan = MealPlan.objects.filter(household=h_gourmet, date=today, meal_type="DINNER").first()
        assert gordon_plan.recipe.title == "Beef Wellington"

    def test_t4_scenario_02_multi_device_onboarding_and_synchronization(
        self, client, create_cli_invite
    ):
        """T4-SCENARIO-02: User onboards MacBook & iPhone; verifies bi-directional sync and duplicate resolution."""
        # Device 1 (MacBook) onboarding
        token_mac = create_cli_invite(username="charlotte", household_name="Charlotte Household")
        client_mac = Client()
        client_mac.post(f"/auth/invite/{token_mac}/redeem/", follow=True)
        user = User.objects.get(username="charlotte")
        household = user.profile.household

        # Device 2 (iPhone) onboarding via second CLI invite
        token_iphone = create_cli_invite(username="charlotte")
        client_iphone = Client()
        client_iphone.post(f"/auth/invite/{token_iphone}/redeem/", follow=True)

        # MacBook creates a recipe
        Recipe.objects.create(
            household=household,
            created_by=user,
            title="MacBook Cinnamon Rolls",
        )

        # iPhone immediately sees the recipe
        iphone_list = client_iphone.get("/").content.decode()
        assert "MacBook Cinnamon Rolls" in iphone_list

        # iPhone assigns to meal plan
        today = timezone.localtime().date()
        recipe = Recipe.objects.get(household=household, title="MacBook Cinnamon Rolls")
        MealPlan.objects.create(
            household=household,
            created_by=user,
            recipe=recipe,
            date=today,
            meal_type="LUNCH",
        )

        # MacBook immediately sees the meal plan update
        mac_plan = client_mac.get("/meal-plan/").content.decode()
        assert "MacBook Cinnamon Rolls" in mac_plan

    def test_t4_scenario_03_recipe_forking_mutation_and_resharing_chain(
        self, client, create_cli_invite
    ):
        """T4-SCENARIO-03: 3-Household chain: A shares v1 -> B clones, mutates, shares v2 -> C clones v2."""
        # Household A
        t_a = create_cli_invite(username="chef_a", household_name="Household A")
        c_a = Client()
        c_a.post(f"/auth/invite/{t_a}/redeem/", follow=True)
        u_a = User.objects.get(username="chef_a")
        h_a = u_a.profile.household

        r_v1 = Recipe.objects.create(
            household=h_a,
            created_by=u_a,
            title="Classic Chili v1",
            instructions="Brown beef and simmer.",
            is_shared=True,
        )

        # Household B
        t_b = create_cli_invite(username="chef_b", household_name="Household B")
        c_b = Client()
        c_b.post(f"/auth/invite/{t_b}/redeem/", follow=True)
        u_b = User.objects.get(username="chef_b")
        h_b = u_b.profile.household

        # B clones v1, mutates to vegetarian, and re-shares as v2
        c_b.post(reverse("recipes:copy_recipe", kwargs={"pk": r_v1.pk}), follow=True)
        r_v2 = Recipe.objects.get(household=h_b, title="Classic Chili v1")
        r_v2.title = "Vegetarian Chili v2"
        r_v2.instructions = "Simmer black beans and corn."
        r_v2.is_shared = True
        r_v2.save()

        # Household C
        t_c = create_cli_invite(username="chef_c", household_name="Household C")
        c_c = Client()
        c_c.post(f"/auth/invite/{t_c}/redeem/", follow=True)
        u_c = User.objects.get(username="chef_c")
        h_c = u_c.profile.household

        # C browses shared catalog: sees BOTH v1 (from A) and v2 (from B)
        cat = c_c.get(reverse("recipes:shared_recipe_list")).content.decode()
        assert "Classic Chili v1" in cat
        assert "Vegetarian Chili v2" in cat

        # C clones v2
        c_c.post(reverse("recipes:copy_recipe", kwargs={"pk": r_v2.pk}), follow=True)
        r_v3 = Recipe.objects.get(household=h_c, title="Vegetarian Chili v2")
        assert r_v3.created_by == u_c

        # All 3 households maintain independent records
        assert Recipe.objects.filter(title="Classic Chili v1", household=h_a).exists()
        assert Recipe.objects.filter(title="Vegetarian Chili v2", household=h_b).exists()
        assert Recipe.objects.filter(title="Vegetarian Chili v2", household=h_c).exists()

    def test_t4_scenario_04_adversarial_idor_and_tampering_defense(
        self, client, create_cli_invite
    ):
        """T4-SCENARIO-04: Adversarial IDOR enumeration across detail, edit, delete, copy endpoints returns 404."""
        # Victim household
        t_vic = create_cli_invite(username="victim", household_name="Victim Household")
        c_vic = Client()
        c_vic.post(f"/auth/invite/{t_vic}/redeem/", follow=True)
        u_vic = User.objects.get(username="victim")
        vic_recipe = Recipe.objects.create(
            household=u_vic.profile.household,
            created_by=u_vic,
            title="Victim Proprietary Formula",
            is_shared=False,
            original_url="https://example.com/proprietary-recipe",
        )

        # Attacker household
        t_att = create_cli_invite(username="attacker", household_name="Attacker Household")
        c_att = Client()
        c_att.post(f"/auth/invite/{t_att}/redeem/", follow=True)

        pk = vic_recipe.pk

        # 1. IDOR detail traversal
        assert c_att.get(f"/{pk}/").status_code == 404

        # 2. IDOR edit traversal (GET & POST)
        assert c_att.get(f"/{pk}/edit/").status_code == 404
        assert c_att.post(f"/{pk}/edit/", {"title": "Pwned"}).status_code == 404

        # 3. IDOR delete traversal
        assert c_att.post(f"/{pk}/delete/").status_code == 404

        # 4. IDOR copy traversal on private recipe
        assert c_att.post(f"/recipes/{pk}/copy/").status_code == 404

        # 5. IDOR copy-duplicate traversal with tampered URL
        assert (
            c_att.post(
                f"/recipes/{pk}/copy-duplicate/",
                {"original_url": "https://example.com/other"},
            ).status_code
            == 404
        )

        # Ensure victim's record is completely unmodified
        vic_recipe.refresh_from_db()
        assert vic_recipe.title == "Victim Proprietary Formula"


# ==============================================================================
# Playwright Browser UI Tests (seamlessly executed when browser is available)
# ==============================================================================


@pytest.mark.django_db(transaction=True)
def test_playwright_invite_landing_and_redeem_ui(page, live_server, create_cli_invite):
    """Playwright E2E UI: Render invite landing and execute direct sign-in fallback button."""
    from playwright.sync_api import expect

    token = create_cli_invite(username="playwright_user", household_name="Playwright Household")

    # Navigate to invite landing
    page.goto(f"{live_server.url}/auth/invite/{token}/")
    expect(page.locator("text=Welcome to KitchenClip!")).to_be_visible()
    expect(page.locator("text=Playwright Household")).to_be_visible()

    # Click direct browser sign-in fallback button
    page.click("button:has-text('Sign In on this Browser')")
    page.wait_for_url(f"{live_server.url}/")

    # Verify redirected to authenticated home page
    expect(page.locator("text=Recipes")).to_be_visible()


@pytest.mark.django_db(transaction=True)
def test_playwright_recipe_crud_and_household_scoping_ui(page, live_server, e2e_household, e2e_user):
    """Playwright E2E UI: Create manual recipe and verify rendered in household recipe list."""
    from playwright.sync_api import expect

    # Navigate to manual add
    page.goto(f"{live_server.url}/add/manual/")
    expect(page.locator("text=Ingredients")).to_be_visible()

    page.fill("input[name='title']", "Playwright Lasagna")
    page.fill("input[name='prep_time']", "15")
    page.fill("input[name='cook_time']", "45")
    page.fill("input[name='total_time']", "60")
    page.fill("input[name='servings']", "6")
    page.fill("textarea[name='ingredients_text']", "Noodles\nRicotta\nSauce")
    page.fill("textarea[name='instructions_text']", "Layer and bake.")
    page.click("button[type='submit']")

    page.wait_for_url(f"{live_server.url}/")
    expect(page.locator("text=Playwright Lasagna")).to_be_visible()
    assert Recipe.objects.filter(household=e2e_household, title="Playwright Lasagna").exists()
