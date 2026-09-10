"""Milestone M4 Challenger 2: Empirical Authentication Security, Session, and Anti-IDOR Challenge Suite.

Empirically challenges:
1. Single-use token lifecycle:
   - Double-redemption replay attacks (sequential and concurrent race condition).
   - Expired token submission (landing, direct fallback, WebAuthn options & verify).
   - Malformed, non-existent, and injection tokens (HTTP 404 / 403 handling).
   - Crawler / preview bot GET idempotency and safety.
2. Persistent session duration:
   - Verification of SESSION_COOKIE_AGE = 31536000 (1 year), SESSION_EXPIRE_AT_BROWSER_CLOSE = False.
   - Cookie Max-Age and session backend expiry duration on invite redemption.
   - Replay of persistent session cookie across simulated browser restarts.
   - Open redirect defense (?next= sanitization).
3. Multi-device provisioning:
   - Independent second device enrollment for existing user via `create_invite --username <name>`.
   - Automatic household resolution without cloud sync requirement.
   - Concurrent multi-device session operation and data synchronization.
   - Independent session termination (logging out device 1 preserves device 2).
   - Rejection of conflicting household reassignment via CLI.
4. Anti-IDOR defenses on copy_duplicate_recipe:
   - Legitimate cross-household duplicate copy.
   - IDOR URL tampering rejection (HTTP 404).
   - IDOR foreign private recipe targeting with mismatched URL rejection (HTTP 404).
   - IDOR manual recipe (no URL) duplication rejection (HTTP 404).
   - Missing/blank URL parameter rejection (HTTP 404).
   - Non-existent recipe ID rejection (HTTP 404).
   - Unauthenticated access redirect to login (HTTP 302).
   - Same-household duplicate copy prevention without duplication.
   - Normalization fidelity and non-tracking parameter distinction.
"""

import io
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from recipes.models import Household, Ingredient, InviteToken, Recipe, RecipeIngredient, UserProfile

User = get_user_model()


# ==============================================================================
# 1. Single-Use Token Lifecycle Empirical Challenge
# ==============================================================================

@pytest.mark.django_db
class TestSingleUseTokenLifecycleChallenger:
    """Rigorous empirical challenge of single-use invite token lifecycle."""

    def test_double_redemption_sequential_replay_attack(self, unauthenticated_client):
        """Redeeming a single-use token once succeeds; replaying it is strictly rejected."""
        household = Household.objects.create(name="Replay Test Household")
        user = User.objects.create_user(username="replay_user@example.com")
        UserProfile.objects.create(user=user, household=household)

        invite, raw_token = InviteToken.create_token(
            user=user,
            household=household,
            expires_hours=48,
        )
        redeem_url = reverse("auth:invite_redeem", kwargs={"token": raw_token})

        # --- First Redemption (Legitimate) ---
        resp1 = unauthenticated_client.post(redeem_url)
        assert resp1.status_code == 302
        assert resp1.url == "/"

        # Verify DB state
        invite.refresh_from_db()
        assert invite.is_used is True
        assert invite.used_at is not None
        assert invite.is_valid is False

        # --- Second Redemption (Replay Attack) ---
        attacker_client = Client()
        resp2 = attacker_client.post(redeem_url)
        assert resp2.status_code == 400
        content2 = resp2.content.decode("utf-8")
        assert "This invite link has already been used." in content2
        assert attacker_client.session.get("_auth_user_id") is None

        # --- Third Redemption (Repeated Replay) ---
        resp3 = attacker_client.post(redeem_url)
        assert resp3.status_code == 400

        # --- Attempt WebAuthn Register Options with Consumed Token ---
        options_url = reverse("auth:webauthn_register_options")
        resp_opt = attacker_client.post(
            options_url,
            data=json.dumps({"token": raw_token}),
            content_type="application/json",
        )
        assert resp_opt.status_code == 403
        assert "already used" in resp_opt.json().get("error", "")

    def test_expired_token_submission_all_endpoints(self, unauthenticated_client):
        """Expired tokens must be rejected across GET landing, POST redeem, and WebAuthn endpoints."""
        household = Household.objects.create(name="Expired Test Household")
        user = User.objects.create_user(username="expired_user@example.com")
        UserProfile.objects.create(user=user, household=household)

        # Create token that expired 2 hours ago
        past_time = timezone.now() - timedelta(hours=2)
        invite, raw_token = InviteToken.create_token(
            user=user,
            household=household,
            expires_hours=48,
        )
        InviteToken.objects.filter(pk=invite.pk).update(expires_at=past_time)
        invite.refresh_from_db()
        assert invite.is_expired is True
        assert invite.is_valid is False

        # 1. Landing page GET returns 400
        landing_url = reverse("auth:invite_landing", kwargs={"token": raw_token})
        resp_get = unauthenticated_client.get(landing_url)
        assert resp_get.status_code == 400
        assert "This invite link has expired" in resp_get.content.decode("utf-8")

        # 2. Direct fallback POST returns 400
        redeem_url = reverse("auth:invite_redeem", kwargs={"token": raw_token})
        resp_post = unauthenticated_client.post(redeem_url)
        assert resp_post.status_code == 400
        assert "This invite link has expired" in resp_post.content.decode("utf-8")
        assert unauthenticated_client.session.get("_auth_user_id") is None

        # 3. WebAuthn register options returns 403
        options_url = reverse("auth:webauthn_register_options")
        resp_opt = unauthenticated_client.post(
            options_url,
            data=json.dumps({"token": raw_token}),
            content_type="application/json",
        )
        assert resp_opt.status_code == 403
        assert "expired" in resp_opt.json().get("error", "")

        # 4. WebAuthn register verify returns 403
        verify_url = reverse("auth:webauthn_register_verify")
        resp_ver = unauthenticated_client.post(
            verify_url,
            data=json.dumps({"token": raw_token, "credential": {"id": "fake"}}),
            content_type="application/json",
        )
        assert resp_ver.status_code == 403
        assert "expired" in resp_ver.json().get("error", "")

        # In DB, token was never redeemed
        invite.refresh_from_db()
        assert invite.is_used is False
        assert invite.used_at is None

    def test_malformed_and_boundary_tokens(self, unauthenticated_client):
        """Malformed, non-existent, and adversarial tokens return strict 404 / 403."""
        malformed_tokens = [
            "completely-nonexistent-token-1234567890",
            "A" * 512,
            "token_with_special_chars_!@$",
            "token_with_sql_injection_'OR'1'='1",
        ]

        for token in malformed_tokens:
            # Landing GET -> 404
            resp_get = unauthenticated_client.get(f"/auth/invite/{token}/")
            assert resp_get.status_code == 404
            assert "Invalid or non-existent invite link" in resp_get.content.decode("utf-8")

            # Redeem POST -> 404
            resp_post = unauthenticated_client.post(f"/auth/invite/{token}/redeem/")
            assert resp_post.status_code == 404

            # WebAuthn options -> 403
            options_url = reverse("auth:webauthn_register_options")
            resp_opt = unauthenticated_client.post(
                options_url,
                data=json.dumps({"token": token}),
                content_type="application/json",
            )
            assert resp_opt.status_code == 403

        # WebAuthn options with empty token or invalid JSON
        options_url = reverse("auth:webauthn_register_options")
        resp_empty = unauthenticated_client.post(
            options_url,
            data=json.dumps({"token": "   "}),
            content_type="application/json",
        )
        assert resp_empty.status_code == 403

        resp_invalid_json = unauthenticated_client.post(
            options_url,
            data="not a json payload",
            content_type="application/json",
        )
        assert resp_invalid_json.status_code == 400

    def test_crawler_get_safety_and_idempotency(self, unauthenticated_client):
        """Automated scanners/crawlers sending GET requests do NOT consume the single-use token."""
        household = Household.objects.create(name="Crawler Test Household")
        user = User.objects.create_user(username="crawler_user@example.com")
        UserProfile.objects.create(user=user, household=household)

        invite, raw_token = InviteToken.create_token(
            user=user,
            household=household,
            expires_hours=48,
        )
        landing_url = reverse("auth:invite_landing", kwargs={"token": raw_token})

        crawler_user_agents = [
            "Googlebot/2.1 (+http://www.google.com/bot.html)",
            "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
            "Slackbot-LinkExpanding 1.0 (+https://api.slack.com/robots)",
            "Twitterbot/1.0",
            "Mozilla/5.0 (compatible; Discordbot/2.0; +https://discordapp.com)",
            "Applebot/0.1",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        ]

        # Simulate 10 crawler GET requests
        for ua in crawler_user_agents + crawler_user_agents[:3]:
            crawler_client = Client()
            resp = crawler_client.get(landing_url, HTTP_USER_AGENT=ua)
            assert resp.status_code == 200
            assert "Welcome to KitchenClip" in resp.content.decode("utf-8")
            assert crawler_client.session.get("_auth_user_id") is None

            # Token must remain valid and unredeemed in DB
            invite.refresh_from_db()
            assert invite.is_used is False
            assert invite.used_at is None
            assert invite.is_valid is True

        # Now legitimate user visits and redeems via POST
        legitimate_client = Client()
        redeem_url = reverse("auth:invite_redeem", kwargs={"token": raw_token})
        resp_redeem = legitimate_client.post(redeem_url)
        assert resp_redeem.status_code == 302
        assert legitimate_client.session.get("_auth_user_id") == str(user.pk)

        invite.refresh_from_db()
        assert invite.is_used is True
        assert invite.used_at is not None


class TestConcurrentDoubleRedemptionChallenger(TransactionTestCase):
    """Rigorous empirical challenge of concurrent double-redemption race conditions."""

    def test_concurrent_double_redemption_race_condition(self):
        """Simulate concurrent threads attempting to redeem the exact same token simultaneously."""
        household = Household.objects.create(name="Concurrent Redeem Household")
        user = User.objects.create_user(username="concurrent_redeem_user@example.com")
        UserProfile.objects.create(user=user, household=household)

        invite, raw_token = InviteToken.create_token(
            user=user,
            household=household,
            expires_hours=48,
        )
        redeem_url = f"/auth/invite/{raw_token}/redeem/"

        results = []

        def worker_redeem(worker_id):
            client = Client(raise_request_exception=False)
            response = client.post(redeem_url)
            return response.status_code

        # Run 5 concurrent threads
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(worker_redeem, i) for i in range(5)]
            for f in futures:
                results.append(f.result())

        # In transactional SQLite/Postgres with select_for_update, exactly 1 request wins (302)
        # and other requests receive 400 (already used), 409 (database busy), or 500 (lock timeout).
        # In NO situation may more than one 302 winner occur.
        winners = [code for code in results if code == 302]
        assert len(winners) == 1, f"Expected exactly 1 winner (302), got {results}"

        # DB invariant check
        invite.refresh_from_db()
        assert invite.is_used is True
        assert invite.used_at is not None
        assert invite.is_valid is False


# ==============================================================================
# 2. Persistent Session Duration Empirical Challenge
# ==============================================================================

@pytest.mark.django_db
class TestPersistentSessionDurationChallenger:
    """Rigorous empirical challenge of 1-year persistent session settings and cookie lifecycle."""

    def test_settings_persistent_session_configuration(self):
        """Verify Django settings enforce 1-year persistent sessions and secure cookie attributes."""
        expected_seconds = 365 * 24 * 60 * 60  # 31,536,000 seconds
        assert settings.SESSION_COOKIE_AGE == expected_seconds
        assert settings.SESSION_COOKIE_AGE == 31536000
        assert settings.SESSION_EXPIRE_AT_BROWSER_CLOSE is False
        assert settings.SESSION_COOKIE_HTTPONLY is True
        assert settings.SESSION_COOKIE_SAMESITE in ("Lax", "Strict")

    def test_session_cookie_age_and_expiry_on_invite_redeem(self, unauthenticated_client):
        """Redeeming an invite sets session expiry to exactly 31,536,000 seconds."""
        household = Household.objects.create(name="Session Test Household")
        user = User.objects.create_user(username="session_user@example.com")
        UserProfile.objects.create(user=user, household=household)

        invite, raw_token = InviteToken.create_token(
            user=user,
            household=household,
            expires_hours=48,
        )
        redeem_url = reverse("auth:invite_redeem", kwargs={"token": raw_token})

        resp = unauthenticated_client.post(redeem_url)
        assert resp.status_code == 302

        # Verify sessionid cookie in response
        assert settings.SESSION_COOKIE_NAME in resp.cookies
        cookie = resp.cookies[settings.SESSION_COOKIE_NAME]
        assert cookie["max-age"] == 31536000
        assert cookie["httponly"] is True

        # Verify session backend state
        session = unauthenticated_client.session
        assert session.get_expiry_age() == 31536000
        assert session.get_expire_at_browser_close() is False

    def test_session_persistence_across_simulated_browser_restarts(self, unauthenticated_client):
        """Simulate browser restart by loading only the persistent session cookie in a fresh client."""
        household = Household.objects.create(name="Restart Test Household")
        user = User.objects.create_user(username="restart_user@example.com")
        UserProfile.objects.create(user=user, household=household)

        recipe = Recipe.objects.create(
            household=household,
            created_by=user,
            title="Private Family Recipe",
            instructions="Cook it well.",
        )

        invite, raw_token = InviteToken.create_token(
            user=user,
            household=household,
            expires_hours=48,
        )
        redeem_url = reverse("auth:invite_redeem", kwargs={"token": raw_token})

        # Browser 1: redeem invite
        resp = unauthenticated_client.post(redeem_url)
        assert resp.status_code == 302
        session_id = unauthenticated_client.cookies[settings.SESSION_COOKIE_NAME].value

        # Browser 2 (simulating restart after days): fresh client with only the persistent session cookie
        fresh_browser = Client()
        fresh_browser.cookies[settings.SESSION_COOKIE_NAME] = session_id

        # Access protected home page
        home_resp = fresh_browser.get(reverse("recipes:list_recipe"))
        assert home_resp.status_code == 200
        assert home_resp.context["user"].is_authenticated
        assert home_resp.context["user"].username == "restart_user@example.com"
        assert recipe.title in home_resp.content.decode("utf-8")

    def test_open_redirect_sanitization_on_redeem(self, unauthenticated_client):
        """Attempting open redirects via ?next= parameter must be sanitized to safe default."""
        household = Household.objects.create(name="Redirect Test Household")
        user = User.objects.create_user(username="redirect_user@example.com")
        UserProfile.objects.create(user=user, household=household)

        malicious_next_urls = [
            "https://evil.com/phishing",
            "http://malicious-site.org",
            "//attacker.com/steal-session",
            "javascript:alert(1)",
        ]

        for bad_next in malicious_next_urls:
            invite, raw_token = InviteToken.create_token(
                user=user,
                household=household,
                expires_hours=48,
            )
            client = Client()
            redeem_url = f"{reverse('auth:invite_redeem', kwargs={'token': raw_token})}?next={bad_next}"
            resp = client.post(redeem_url)
            assert resp.status_code == 302
            # Must redirect safely to /
            assert resp.url == "/"


# ==============================================================================
# 3. Multi-Device Provisioning Empirical Challenge
# ==============================================================================

@pytest.mark.django_db
class TestMultiDeviceProvisioningChallenger:
    """Rigorous empirical challenge of multi-device provisioning and coexistence."""

    def test_multidevice_provisioning_for_existing_user(self):
        """CLI create_invite for existing user provisions second device in identical household without cloud sync."""
        out = io.StringIO()

        # Step 1: Initial user provisioning for device 1
        call_command(
            "create_invite",
            username="diana",
            household="Diana Household",
            stdout=out,
        )
        output1 = out.getvalue()
        assert "KitchenClip Passwordless Invite Generated" in output1
        assert "Username:    diana" in output1
        assert "Household:   Diana Household" in output1

        # Extract token 1
        diana = User.objects.get(username="diana")
        token1_obj = InviteToken.objects.filter(user=diana, is_used=False).latest("created_at")
        assert token1_obj is not None

        # Device 1 redeems token 1
        device1_client = Client()
        url_line1 = [line for line in output1.splitlines() if "Invite URL:" in line][0]
        raw_token1 = url_line1.split("/auth/invite/")[1].rstrip("/")

        resp1 = device1_client.post(reverse("auth:invite_redeem", kwargs={"token": raw_token1}))
        assert resp1.status_code == 302
        assert device1_client.session.get("_auth_user_id") == str(diana.pk)

        # Step 2: Second device provisioning for diana without --household flag
        out2 = io.StringIO()
        call_command(
            "create_invite",
            username="diana",
            stdout=out2,
        )
        output2 = out2.getvalue()
        assert "Username:    diana" in output2
        assert "Household:   Diana Household" in output2

        url_line2 = [line for line in output2.splitlines() if "Invite URL:" in line][0]
        raw_token2 = url_line2.split("/auth/invite/")[1].rstrip("/")
        assert raw_token1 != raw_token2

        # Device 2 redeems token 2
        device2_client = Client()
        resp2 = device2_client.post(reverse("auth:invite_redeem", kwargs={"token": raw_token2}))
        assert resp2.status_code == 302
        assert device2_client.session.get("_auth_user_id") == str(diana.pk)

        # Both tokens are now redeemed
        assert InviteToken.objects.filter(user=diana, is_used=True).count() == 2

    def test_multidevice_data_coexistence_and_independent_sessions(self):
        """Device 1 and Device 2 operate concurrently, see shared household updates, and have independent sessions."""
        household = Household.objects.create(name="Coexist Household")
        user = User.objects.create_user(username="dual_device_user@example.com")
        UserProfile.objects.create(user=user, household=household)

        _, raw1 = InviteToken.create_token(user=user, household=household)
        _, raw2 = InviteToken.create_token(user=user, household=household)

        dev1_client = Client()
        dev2_client = Client()

        # Redeem both devices
        dev1_client.post(reverse("auth:invite_redeem", kwargs={"token": raw1}))
        dev2_client.post(reverse("auth:invite_redeem", kwargs={"token": raw2}))

        # Device 1 creates a recipe
        Recipe.objects.create(
            household=household,
            created_by=user,
            title="MacBook Apple Pie",
            instructions="Bake crust.",
        )

        # Device 2 immediately queries recipe catalog and sees it
        resp2 = dev2_client.get(reverse("recipes:list_recipe"))
        assert resp2.status_code == 200
        assert "MacBook Apple Pie" in resp2.content.decode("utf-8")

        # Device 2 logs out
        dev2_client.post(reverse("auth:logout"))
        # Device 2 is logged out
        resp2_after = dev2_client.get(reverse("recipes:list_recipe"))
        assert resp2_after.status_code == 302
        assert "/auth/login/" in resp2_after.url

        # Device 1 remains logged in and fully functional!
        resp1_after = dev1_client.get(reverse("recipes:list_recipe"))
        assert resp1_after.status_code == 200
        assert "MacBook Apple Pie" in resp1_after.content.decode("utf-8")

    def test_create_invite_conflicting_household_rejection(self):
        """Running create_invite with conflicting household for an existing user raises CommandError."""
        household1 = Household.objects.create(name="Household Alpha")
        Household.objects.create(name="Household Beta")
        user = User.objects.create_user(username="locked_user")
        UserProfile.objects.create(user=user, household=household1)

        with pytest.raises(CommandError) as exc_info:
            call_command(
                "create_invite",
                username="locked_user",
                household="Household Beta",
            )
        assert "already belongs to household 'Household Alpha'" in str(exc_info.value)
        assert "Cannot reassign household" in str(exc_info.value)

        # Verify user still belongs strictly to Household Alpha
        user.refresh_from_db()
        assert user.profile.household == household1


# ==============================================================================
# 4. Anti-IDOR Defenses on copy_duplicate_recipe Empirical Challenge
# ==============================================================================

@pytest.mark.django_db
class TestAntiIDORCopyDuplicateRecipeChallenger:
    """Rigorous empirical challenge of anti-IDOR defenses on copy_duplicate_recipe."""

    def test_legitimate_cross_household_copy_duplicate(
        self, client, test_household, test_user, secondary_household, secondary_user
    ):
        """Legitimate duplicate copy with matching URL clones recipe into target household."""
        source_recipe = Recipe.objects.create(
            household=secondary_household,
            created_by=secondary_user,
            title="Authentic Tuscan Ribollita",
            original_url="https://example.com/recipes/ribollita",
            instructions="Simmer beans and kale.",
        )
        ing = Ingredient.objects.create(name="Cannellini Beans")
        RecipeIngredient.objects.create(
            recipe=source_recipe,
            ingredient=ing,
            raw_text="2 cups Cannellini Beans",
            quantity="2",
            unit="cups",
            order=0,
        )

        copy_url = reverse("recipes:copy_duplicate", kwargs={"pk": source_recipe.pk})
        post_data = {
            "original_url": "https://example.com/recipes/ribollita",
            "user_notes": "Our family variation",
            "rating": "5",
        }

        resp = client.post(copy_url, data=post_data)
        assert resp.status_code == 302

        # Verify cloned recipe in test_household
        cloned = Recipe.objects.filter(household=test_household, title="Authentic Tuscan Ribollita").first()
        assert cloned is not None
        assert cloned.pk != source_recipe.pk
        assert cloned.created_by == test_user
        assert cloned.user_notes == "Our family variation"
        assert cloned.rating == 5
        assert cloned.recipe_ingredients.count() == 1
        assert cloned.recipe_ingredients.first().ingredient.name == "Cannellini Beans"

    def test_idor_url_tampering_different_url_returns_404(
        self, client, test_household, secondary_household, secondary_user
    ):
        """Tampering with original_url in POST body to mismatch target recipe returns strict HTTP 404."""
        target_recipe = Recipe.objects.create(
            household=secondary_household,
            created_by=secondary_user,
            title="Foreign Recipe",
            original_url="https://example.com/recipes/pasta",
            instructions="Boil water.",
        )

        copy_url = reverse("recipes:copy_duplicate", kwargs={"pk": target_recipe.pk})
        tampered_urls = [
            "https://example.com/recipes/different-pasta",
            "https://attacker.com/malicious-url",
            "https://example.com/recipes/pasta-bake",
            "https://example.com/recipes/pasta?extra_param=123",  # non-tracking query parameter differs
        ]

        for tampered in tampered_urls:
            resp = client.post(copy_url, data={"original_url": tampered})
            assert resp.status_code == 404

        # Zero recipes cloned into test_household
        assert Recipe.objects.filter(household=test_household, title="Foreign Recipe").count() == 0

    def test_idor_target_private_recipe_with_arbitrary_url_returns_404(
        self, client, test_household, secondary_household, secondary_user
    ):
        """Attacker knowing foreign recipe PK attempts to clone using arbitrary URL. Strict HTTP 404."""
        secret_recipe = Recipe.objects.create(
            household=secondary_household,
            created_by=secondary_user,
            title="Top Secret Recipe",
            original_url="https://secret-vault.internal/classified-pie",
            instructions="Secret steps.",
        )

        copy_url = reverse("recipes:copy_duplicate", kwargs={"pk": secret_recipe.pk})
        resp = client.post(copy_url, data={"original_url": "https://example.com/public-recipe"})
        assert resp.status_code == 404

        # Zero recipes cloned
        assert Recipe.objects.filter(household=test_household, title="Top Secret Recipe").count() == 0

    def test_idor_manual_recipe_without_url_returns_404(
        self, client, test_household, secondary_household, secondary_user
    ):
        """Targeting a foreign manual recipe (empty original_url) returns strict HTTP 404."""
        manual_recipe = Recipe.objects.create(
            household=secondary_household,
            created_by=secondary_user,
            title="Grandma's Hand-Written Bread",
            original_url="",
            instructions="Hand knead.",
        )

        copy_url = reverse("recipes:copy_duplicate", kwargs={"pk": manual_recipe.pk})
        resp = client.post(copy_url, data={"original_url": "https://example.com/bread"})
        assert resp.status_code == 404

        assert Recipe.objects.filter(household=test_household, title="Grandma's Hand-Written Bread").count() == 0

    def test_idor_missing_or_blank_url_parameter_returns_404(
        self, client, test_household, secondary_household, secondary_user
    ):
        """Submitting copy_duplicate without original_url or with blank value returns strict HTTP 404."""
        recipe = Recipe.objects.create(
            household=secondary_household,
            created_by=secondary_user,
            title="Valid Foreign Recipe",
            original_url="https://example.com/valid",
            instructions="Step 1.",
        )

        copy_url = reverse("recipes:copy_duplicate", kwargs={"pk": recipe.pk})

        # Missing parameter
        resp_missing = client.post(copy_url, data={})
        assert resp_missing.status_code == 404

        # Blank parameter
        resp_blank = client.post(copy_url, data={"original_url": "   "})
        assert resp_blank.status_code == 404

        assert Recipe.objects.filter(household=test_household, title="Valid Foreign Recipe").count() == 0

    def test_idor_nonexistent_recipe_pk_returns_404(self, client):
        """Targeting non-existent recipe PK returns strict HTTP 404."""
        copy_url = reverse("recipes:copy_duplicate", kwargs={"pk": 999999})
        resp = client.post(copy_url, data={"original_url": "https://example.com/valid"})
        assert resp.status_code == 404

    def test_idor_unauthenticated_request_redirects_to_login(
        self, unauthenticated_client, test_household, secondary_household, secondary_user
    ):
        """Unauthenticated attacker POSTing to copy_duplicate is redirected to login."""
        recipe = Recipe.objects.create(
            household=secondary_household,
            created_by=secondary_user,
            title="Foreign Recipe",
            original_url="https://example.com/valid",
            instructions="Step 1.",
        )

        copy_url = reverse("recipes:copy_duplicate", kwargs={"pk": recipe.pk})
        resp = unauthenticated_client.post(copy_url, data={"original_url": "https://example.com/valid"})
        assert resp.status_code == 302
        assert "/auth/login/" in resp.url

    def test_copy_duplicate_same_household_prevents_duplication(
        self, client, test_household, test_user
    ):
        """Attempting to copy_duplicate a recipe that is already in own household does NOT clone."""
        existing_recipe = Recipe.objects.create(
            household=test_household,
            created_by=test_user,
            title="Own Household Soup",
            original_url="https://example.com/own-soup",
            instructions="Stir gently.",
        )

        copy_url = reverse("recipes:copy_duplicate", kwargs={"pk": existing_recipe.pk})
        resp = client.post(copy_url, data={"original_url": "https://example.com/own-soup"})
        assert resp.status_code == 302
        assert resp.url == reverse("recipes:detail_recipe", kwargs={"pk": existing_recipe.pk})

        # No duplicate created in test_household
        assert Recipe.objects.filter(household=test_household, title="Own Household Soup").count() == 1

    def test_copy_duplicate_url_normalization_fidelity(
        self, client, test_household, secondary_household, secondary_user
    ):
        """URL normalization accurately matches equivalent URLs and strips tracking parameters."""
        source = Recipe.objects.create(
            household=secondary_household,
            created_by=secondary_user,
            title="Normalized Stew",
            original_url="https://example.com/recipes/beef-stew",
            instructions="Slow cook.",
        )

        copy_url = reverse("recipes:copy_duplicate", kwargs={"pk": source.pk})

        # Equivalent URL with scheme variation, www, trailing slash, and tracking query params
        equivalent_url = "http://www.example.com/recipes/beef-stew/?utm_source=twitter&fbclid=98765#section"
        resp = client.post(copy_url, data={"original_url": equivalent_url})
        assert resp.status_code == 302

        # Verify cloned
        cloned = Recipe.objects.filter(household=test_household, title="Normalized Stew").first()
        assert cloned is not None
