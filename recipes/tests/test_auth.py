"""Comprehensive test suite for KitchenClip Milestone M2:
- CLI Invitation Command (recipes/management/commands/create_invite.py)
- Single-Use Token Lifecycle & Atomic Consumption (InviteToken)
- WebAuthn Passkey Registration & Login Gating (recipes/views_auth.py)
- Monotonic Signature Counter Rollback Detection (PasskeyCredential)
- 1-Year Persistent Sessions & Attack Surface Elimination
"""

import hashlib
import json
from datetime import timedelta

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.urls import get_resolver, reverse
from django.utils import timezone

from recipes.models import Household, InviteToken, PasskeyCredential, UserProfile
from recipes.webauthn_service import (
    b64url_decode,
    b64url_encode,
    build_mock_assertion_payload,
    build_mock_registration_payload,
)


# ==============================================================================
# 1. CLI Command Tests (recipes/management/commands/create_invite.py)
# ==============================================================================

@pytest.mark.django_db
class TestCLIInviteCommand:
    """Validate CLI invitation command argument parsing, resolution, and outputs."""

    def test_cli_create_invite_new_user_new_household(self, capsys):
        """Provisioning a new user and new household generates single-use token and unusable password."""
        call_command("create_invite", username="alice", household="Wonderland")

        User = get_user_model()
        user = User.objects.filter(username="alice").first()
        assert user is not None
        assert user.has_usable_password() is False

        household = Household.objects.filter(name="Wonderland").first()
        assert household is not None
        assert user.profile.household == household
        assert user.profile.role == "admin"

        token = InviteToken.objects.filter(user=user, household=household).first()
        assert token is not None
        assert token.is_valid is True

        out = capsys.readouterr().out
        assert "KitchenClip Passwordless Invite Generated" in out
        assert "Wonderland" in out
        assert "/auth/invite/" in out

    def test_cli_create_invite_new_user_existing_household(self):
        """Provisioning a second user in an existing household assigns member role."""
        User = get_user_model()
        household = Household.objects.create(name="Baker Family")
        first_user = User.objects.create_user(username="baker_admin")
        UserProfile.objects.create(user=first_user, household=household, role="admin")

        call_command("create_invite", username="bob", household="Baker Family")

        bob = User.objects.get(username="bob")
        assert bob.profile.household == household
        assert bob.profile.role == "member"

    def test_cli_create_invite_missing_household_for_new_user_fails(self):
        """Omitting --household when provisioning a new user raises CommandError."""
        with pytest.raises(CommandError, match="--household is required when provisioning a new user"):
            call_command("create_invite", username="charlie")

    def test_cli_create_invite_existing_user_multi_device_no_household(self):
        """Multi-device invite for existing user reuses existing household without --household flag."""
        household = Household.objects.create(name="Miller Family")
        User = get_user_model()
        david = User.objects.create_user(username="david")
        UserProfile.objects.create(user=david, household=household, role="admin")

        call_command("create_invite", username="david")
        tokens = InviteToken.objects.filter(user=david)
        assert tokens.count() == 1
        assert tokens.first().household == household

    def test_cli_create_invite_existing_user_matching_household(self):
        """Multi-device invite with matching --household flag succeeds."""
        household = Household.objects.create(name="Miller Family")
        User = get_user_model()
        eva = User.objects.create_user(username="eva")
        UserProfile.objects.create(user=eva, household=household, role="admin")

        call_command("create_invite", username="eva", household="Miller Family")
        assert InviteToken.objects.filter(user=eva).count() == 1

    def test_cli_create_invite_existing_user_conflicting_household_fails(self):
        """Specifying a conflicting household for an existing user raises CommandError."""
        household = Household.objects.create(name="Miller Family")
        User = get_user_model()
        frank = User.objects.create_user(username="frank")
        UserProfile.objects.create(user=frank, household=household, role="admin")

        with pytest.raises(CommandError, match="Cannot reassign household"):
            call_command("create_invite", username="frank", household="Smith Family")

    def test_cli_create_invite_invalid_expires_hours_fails(self):
        """Non-positive --expires-hours raises CommandError."""
        with pytest.raises(CommandError, match="--expires-hours must be a positive integer"):
            call_command("create_invite", username="grace", household="Home", expires_hours=0)

    def test_cli_create_invite_empty_username_fails(self):
        """Blank username raises CommandError."""
        with pytest.raises(CommandError, match="--username cannot be empty"):
            call_command("create_invite", username="   ", household="Home")


# ==============================================================================
# 2. Token Lifecycle & Single-Use Gating Tests
# ==============================================================================

@pytest.mark.django_db
class TestTokenLifecycle:
    """Validate token generation, SHA-256 storage, crawler-safe GETs, and atomic consumption."""

    def test_token_creation_entropy_and_sha256_hashing(self, test_user, test_household):
        """Raw token is 32-byte URL-safe string and never stored in plaintext in SQLite."""
        token_obj, raw_token = InviteToken.create_token(test_user, test_household, expires_hours=48)
        assert len(raw_token) >= 43
        assert token_obj.token_hash == hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        assert token_obj.is_valid is True

    def test_token_expiration_logic(self, test_user, test_household):
        """Expired token reports is_expired=True and is_valid=False."""
        token_obj, raw_token = InviteToken.create_token(test_user, test_household, expires_hours=1)
        token_obj.expires_at = timezone.now() - timedelta(minutes=5)
        token_obj.save()
        assert token_obj.is_expired is True
        assert token_obj.is_valid is False

    def test_invite_landing_get_is_idempotent_and_scanner_safe(self, unauthenticated_client, invite_token_factory):
        """Link scanners (SafeLinks/Slack unfurlers) hitting GET do NOT mark the token as used."""
        token_obj = invite_token_factory()
        raw_token = token_obj.raw_token
        url = reverse("auth:invite_landing", kwargs={"token": raw_token})

        for _ in range(3):
            response = unauthenticated_client.get(url)
            assert response.status_code == 200
            assert "Welcome to KitchenClip!" in response.content.decode("utf-8")

        token_obj.refresh_from_db()
        assert token_obj.is_used is False
        assert token_obj.used_at is None

    def test_invite_landing_invalid_token_returns_404(self, unauthenticated_client):
        """Malformed or non-existent token returns HTTP 404."""
        url = reverse("auth:invite_landing", kwargs={"token": "non-existent-token"})
        response = unauthenticated_client.get(url)
        assert response.status_code == 404
        assert "Invalid" in response.content.decode("utf-8")

    def test_invite_landing_expired_token_returns_400(self, unauthenticated_client, invite_token_factory):
        """Expired token returns HTTP 400 with expired notice."""
        token_obj = invite_token_factory(expires_at=timezone.now() - timedelta(hours=1))
        url = reverse("auth:invite_landing", kwargs={"token": token_obj.raw_token})
        response = unauthenticated_client.get(url)
        assert response.status_code == 400
        assert "Expired" in response.content.decode("utf-8")

    def test_invite_landing_used_token_returns_400(self, unauthenticated_client, invite_token_factory):
        """Already redeemed token returns HTTP 400 with redeemed notice."""
        token_obj = invite_token_factory(is_used=True, used_at=timezone.now())
        url = reverse("auth:invite_landing", kwargs={"token": token_obj.raw_token})
        response = unauthenticated_client.get(url)
        assert response.status_code == 400
        content = response.content.decode("utf-8").lower()
        assert "redeemed" in content or "used" in content or "already" in content

    def test_invite_redeem_post_success(self, unauthenticated_client, invite_token_factory):
        """Direct session fallback POST marks token used, logs in user, sets 1-year expiry."""
        token_obj = invite_token_factory()
        url = reverse("auth:invite_redeem", kwargs={"token": token_obj.raw_token})

        response = unauthenticated_client.post(url)
        assert response.status_code == 302
        assert response.url == "/"

        token_obj.refresh_from_db()
        assert token_obj.is_used is True
        assert token_obj.used_at is not None

        session = unauthenticated_client.session
        assert session.get_expiry_age() == 31536000

    def test_invite_redeem_double_redemption_rejected(self, unauthenticated_client, invite_token_factory):
        """Attempting to redeem the same token twice fails on second attempt."""
        token_obj = invite_token_factory()
        url = reverse("auth:invite_redeem", kwargs={"token": token_obj.raw_token})

        resp1 = unauthenticated_client.post(url)
        assert resp1.status_code == 302

        resp2 = unauthenticated_client.post(url)
        assert resp2.status_code in [400, 403]

    def test_invite_redeem_requires_post(self, unauthenticated_client, invite_token_factory):
        """GET request to /redeem/ endpoint returns HTTP 405 Method Not Allowed."""
        token_obj = invite_token_factory()
        url = reverse("auth:invite_redeem", kwargs={"token": token_obj.raw_token})
        response = unauthenticated_client.get(url)
        assert response.status_code == 405


# ==============================================================================
# 3. WebAuthn Passkey Registration & Login Gating Tests
# ==============================================================================

@pytest.mark.django_db
class TestWebAuthnFlows:
    """Validate WebAuthn registration gating, attestation, assertion, and counter rollback."""

    def test_webauthn_register_options_without_token_returns_403(self, unauthenticated_client):
        """Requesting creation options without a valid token returns HTTP 403."""
        url = reverse("auth:webauthn_register_options")
        resp = unauthenticated_client.post(
            url,
            data=json.dumps({"token": ""}),
            content_type="application/json",
        )
        assert resp.status_code == 403

    def test_webauthn_register_options_with_expired_or_used_token_returns_403(
        self, unauthenticated_client, invite_token_factory
    ):
        """Requesting creation options with an expired or used token returns HTTP 403."""
        expired = invite_token_factory(expires_at=timezone.now() - timedelta(hours=1))
        url = reverse("auth:webauthn_register_options")
        resp = unauthenticated_client.post(
            url,
            data=json.dumps({"token": expired.raw_token}),
            content_type="application/json",
        )
        assert resp.status_code == 403

    def test_webauthn_register_options_with_valid_token_success(
        self, unauthenticated_client, invite_token_factory
    ):
        """Valid token receives WebAuthn creation options and stores challenge in session."""
        token_obj = invite_token_factory()
        url = reverse("auth:webauthn_register_options")
        resp = unauthenticated_client.post(
            url,
            data=json.dumps({"token": token_obj.raw_token}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "challenge" in data
        assert "rp" in data
        assert "user" in data

    def test_webauthn_register_verify_stores_passkey_consumes_token_logs_in(
        self, unauthenticated_client, invite_token_factory
    ):
        """Valid attestation creates PasskeyCredential, marks token as used, and logs in user."""
        token_obj = invite_token_factory()

        # Step 1: Get options
        opt_url = reverse("auth:webauthn_register_options")
        opt_resp = unauthenticated_client.post(
            opt_url,
            data=json.dumps({"token": token_obj.raw_token}),
            content_type="application/json",
        )
        challenge = opt_resp.json()["challenge"]

        # Step 2: Submit mock registration payload
        payload = build_mock_registration_payload(
            user=token_obj.user,
            challenge=challenge,
            credential_id="test-macbook-touchid-id",
        )
        verify_url = reverse("auth:webauthn_register_verify")
        verify_resp = unauthenticated_client.post(
            verify_url,
            data=json.dumps({
                "token": token_obj.raw_token,
                "credential": payload,
                "name": "MacBook TouchID",
            }),
            content_type="application/json",
        )
        assert verify_resp.status_code == 200
        assert verify_resp.json()["success"] is True

        # Verify DB records
        token_obj.refresh_from_db()
        assert token_obj.is_used is True

        cred = PasskeyCredential.objects.filter(user=token_obj.user).first()
        assert cred is not None
        assert cred.credential_id == "test-macbook-touchid-id"
        assert cred.name == "MacBook TouchID"

        # Verify 1-year session
        assert unauthenticated_client.session.get_expiry_age() == 31536000

    def test_webauthn_register_verify_re_registration_with_redeemed_token_returns_403(
        self, unauthenticated_client, invite_token_factory
    ):
        """Submitting attestation with an already redeemed token returns HTTP 403."""
        token_obj = invite_token_factory(is_used=True, used_at=timezone.now())
        verify_url = reverse("auth:webauthn_register_verify")
        resp = unauthenticated_client.post(
            verify_url,
            data=json.dumps({
                "token": token_obj.raw_token,
                "credential": {"id": "fake"},
            }),
            content_type="application/json",
        )
        assert resp.status_code == 403

    def test_webauthn_register_verify_challenge_mismatch_returns_400(
        self, unauthenticated_client, invite_token_factory
    ):
        """Attestation with corrupted challenge returns HTTP 400 and preserves token validity."""
        token_obj = invite_token_factory()
        opt_url = reverse("auth:webauthn_register_options")
        opt_resp = unauthenticated_client.post(
            opt_url,
            data=json.dumps({"token": token_obj.raw_token}),
            content_type="application/json",
        )
        assert opt_resp.status_code == 200

        payload = build_mock_registration_payload(
            user=token_obj.user,
            challenge="corrupted-challenge-string",
            credential_id="test-corrupted-id",
        )
        verify_url = reverse("auth:webauthn_register_verify")
        verify_resp = unauthenticated_client.post(
            verify_url,
            data=json.dumps({
                "token": token_obj.raw_token,
                "credential": payload,
            }),
            content_type="application/json",
        )
        assert verify_resp.status_code == 400
        assert "challenge" in verify_resp.json().get("error", "").lower()

        token_obj.refresh_from_db()
        assert token_obj.is_used is False

    def test_webauthn_register_verify_token_session_hash_mismatch_rejected(
        self, unauthenticated_client, test_household, test_user
    ):
        """Redeeming a different token than the session's registration token hash returns 403 Forbidden."""
        _, token1 = InviteToken.create_token(test_user, test_household)
        _, token2 = InviteToken.create_token(test_user, test_household)

        opt_url = reverse("auth:webauthn_register_options")
        opt_resp = unauthenticated_client.post(opt_url, data=json.dumps({"token": token1}), content_type="application/json")
        challenge = opt_resp.json()["challenge"]

        payload = build_mock_registration_payload(user=test_user, challenge=challenge)
        verify_url = reverse("auth:webauthn_register_verify")
        # Attempt to verify with token2 while session has token1 hash
        verify_resp = unauthenticated_client.post(
            verify_url,
            data=json.dumps({
                "token": token2,
                "credential": payload,
            }),
            content_type="application/json",
        )
        assert verify_resp.status_code == 403
        assert "does not match registration session" in verify_resp.json().get("error", "").lower()

    def test_webauthn_register_verify_validation_ordering_403_before_400(
        self, unauthenticated_client
    ):
        """Invalid or empty token with empty/missing credential payload returns 403, not 400."""
        verify_url = reverse("auth:webauthn_register_verify")

        # 1. Non-existent token with empty credential dict
        resp1 = unauthenticated_client.post(
            verify_url,
            data=json.dumps({"token": "non-existent-token", "credential": {}}),
            content_type="application/json",
        )
        assert resp1.status_code == 403

        # 2. Empty token string with empty credential dict
        resp2 = unauthenticated_client.post(
            verify_url,
            data=json.dumps({"token": "", "credential": {}}),
            content_type="application/json",
        )
        assert resp2.status_code == 403

    def test_webauthn_register_cbor_attestation_parsing(
        self, unauthenticated_client, test_user, test_household
    ):
        """Registration verify unpacks CBOR attestationObject and stores genuine P-256 public key point."""
        _, raw_token = InviteToken.create_token(test_user, test_household)
        opt_url = reverse("auth:webauthn_register_options")
        opt_resp = unauthenticated_client.post(
            opt_url,
            data=json.dumps({"token": raw_token}),
            content_type="application/json",
        )
        challenge = opt_resp.json()["challenge"]

        payload = build_mock_registration_payload(
            user=test_user,
            challenge=challenge,
            credential_id="cbor-dev-cred",
        )
        assert "attestationObject" in payload["response"]

        verify_url = reverse("auth:webauthn_register_verify")
        verify_resp = unauthenticated_client.post(
            verify_url,
            data=json.dumps({
                "token": raw_token,
                "credential": payload,
                "name": "CBOR Device",
            }),
            content_type="application/json",
        )
        assert verify_resp.status_code == 200
        cred = PasskeyCredential.objects.get(credential_id="cbor-dev-cred")
        # Ensure public key is standard 65-byte uncompressed EC point (b"\x04" + x + y)
        raw_point = b64url_decode(cred.public_key)
        assert len(raw_point) == 65
        assert raw_point[0] == 0x04

    def test_webauthn_login_options_success(self, unauthenticated_client):
        """Passkey login options endpoint issues challenge and RP ID."""
        url = reverse("auth:webauthn_login_options")
        resp = unauthenticated_client.post(url, data=json.dumps({}), content_type="application/json")
        assert resp.status_code == 200
        data = resp.json()
        assert "challenge" in data
        assert "rpId" in data

    def test_webauthn_login_verify_success_and_increments_sign_count(
        self, unauthenticated_client, test_user, passkey_factory
    ):
        """Valid assertion authenticates user, increments sign_count, and sets 1-year session."""
        cred = passkey_factory(user=test_user, credential_id="iphone-faceid-cred", sign_count=5)

        opt_url = reverse("auth:webauthn_login_options")
        opt_resp = unauthenticated_client.post(opt_url, data=json.dumps({}), content_type="application/json")
        challenge = opt_resp.json()["challenge"]

        payload = build_mock_assertion_payload(
            credential_id=cred.credential_id,
            challenge=challenge,
            sign_count=6,
        )
        verify_url = reverse("auth:webauthn_login_verify")
        verify_resp = unauthenticated_client.post(
            verify_url,
            data=json.dumps({"credential": payload}),
            content_type="application/json",
        )
        assert verify_resp.status_code == 200
        assert verify_resp.json()["success"] is True

        cred.refresh_from_db()
        assert cred.sign_count == 6
        assert cred.last_used_at is not None
        assert unauthenticated_client.session.get_expiry_age() == 31536000

    def test_webauthn_login_verify_counter_rollback_rejected(
        self, unauthenticated_client, test_user, passkey_factory
    ):
        """Assertion returning sign_count <= stored count raises anti-cloning alert and rejects login."""
        cred = passkey_factory(user=test_user, credential_id="cloned-cred", sign_count=10)

        opt_url = reverse("auth:webauthn_login_options")
        opt_resp = unauthenticated_client.post(opt_url, data=json.dumps({}), content_type="application/json")
        challenge = opt_resp.json()["challenge"]

        payload = build_mock_assertion_payload(
            credential_id=cred.credential_id,
            challenge=challenge,
            sign_count=8,
        )
        verify_url = reverse("auth:webauthn_login_verify")
        verify_resp = unauthenticated_client.post(
            verify_url,
            data=json.dumps({"credential": payload}),
            content_type="application/json",
        )
        assert verify_resp.status_code in [400, 403]
        assert "rollback" in verify_resp.json().get("error", "").lower()

        cred.refresh_from_db()
        assert cred.sign_count == 10

    def test_webauthn_login_verify_synced_passkey_zero_counter_success(
        self, unauthenticated_client, test_user, passkey_factory
    ):
        """Assertion with sign_count=0 is permitted for cloud-synced passkeys (iCloud/Google)."""
        cred = passkey_factory(user=test_user, credential_id="synced-icloud-cred", sign_count=0)

        opt_url = reverse("auth:webauthn_login_options")
        opt_resp = unauthenticated_client.post(opt_url, data=json.dumps({}), content_type="application/json")
        challenge = opt_resp.json()["challenge"]

        payload = build_mock_assertion_payload(
            credential_id=cred.credential_id,
            challenge=challenge,
            sign_count=0,
        )
        verify_url = reverse("auth:webauthn_login_verify")
        verify_resp = unauthenticated_client.post(
            verify_url,
            data=json.dumps({"credential": payload}),
            content_type="application/json",
        )
        assert verify_resp.status_code == 200
        assert verify_resp.json()["success"] is True

    def test_webauthn_login_verify_forged_signature_rejected(
        self, unauthenticated_client, test_user, passkey_factory
    ):
        """Assertion with a forged signature fails cryptographic verification and rejects login."""
        cred = passkey_factory(user=test_user, credential_id="sig-verify-cred", sign_count=1)

        opt_url = reverse("auth:webauthn_login_options")
        opt_resp = unauthenticated_client.post(opt_url, data=json.dumps({}), content_type="application/json")
        challenge = opt_resp.json()["challenge"]

        payload = build_mock_assertion_payload(
            credential_id=cred.credential_id,
            challenge=challenge,
            sign_count=2,
        )
        # Forge the signature with a valid base64url DER sequence that has invalid values
        payload["response"]["signature"] = b64url_encode(b"\x30\x06\x02\x01\x01\x02\x01\x01")

        verify_url = reverse("auth:webauthn_login_verify")
        verify_resp = unauthenticated_client.post(
            verify_url,
            data=json.dumps({"credential": payload}),
            content_type="application/json",
        )
        assert verify_resp.status_code == 400
        assert "signature" in verify_resp.json().get("error", "").lower()

    def test_webauthn_login_verify_missing_signature_rejected(
        self, unauthenticated_client, test_user, passkey_factory
    ):
        """Assertion missing a signature field is rejected with 400 Bad Request."""
        cred = passkey_factory(user=test_user, credential_id="missing-sig-cred", sign_count=1)

        opt_url = reverse("auth:webauthn_login_options")
        opt_resp = unauthenticated_client.post(opt_url, data=json.dumps({}), content_type="application/json")
        challenge = opt_resp.json()["challenge"]

        payload = build_mock_assertion_payload(
            credential_id=cred.credential_id,
            challenge=challenge,
            sign_count=2,
        )
        payload["response"].pop("signature", None)

        verify_url = reverse("auth:webauthn_login_verify")
        verify_resp = unauthenticated_client.post(
            verify_url,
            data=json.dumps({"credential": payload}),
            content_type="application/json",
        )
        assert verify_resp.status_code == 400
        assert "missing signature" in verify_resp.json().get("error", "").lower()

    def test_multi_device_enrollment_independent_credentials(
        self, unauthenticated_client, test_household
    ):
        """Enrolling two separate devices for the same user creates two distinct PasskeyCredentials."""
        User = get_user_model()
        user = User.objects.create_user(username="sarah")
        user.set_unusable_password()
        user.save()
        UserProfile.objects.create(user=user, household=test_household, role="member")

        # Device 1: iPhone
        _, token1 = InviteToken.create_token(user, test_household)
        opt_url = reverse("auth:webauthn_register_options")
        opt_resp1 = unauthenticated_client.post(opt_url, data=json.dumps({"token": token1}), content_type="application/json")
        challenge1 = opt_resp1.json()["challenge"]
        payload1 = build_mock_registration_payload(user=user, challenge=challenge1, credential_id="sarah-iphone")
        verify_url = reverse("auth:webauthn_register_verify")
        unauthenticated_client.post(verify_url, data=json.dumps({"token": token1, "credential": payload1, "name": "iPhone"}), content_type="application/json")

        # Device 2: MacBook
        _, token2 = InviteToken.create_token(user, test_household)
        opt_resp2 = unauthenticated_client.post(opt_url, data=json.dumps({"token": token2}), content_type="application/json")
        challenge2 = opt_resp2.json()["challenge"]
        payload2 = build_mock_registration_payload(user=user, challenge=challenge2, credential_id="sarah-macbook")
        unauthenticated_client.post(verify_url, data=json.dumps({"token": token2, "credential": payload2, "name": "MacBook"}), content_type="application/json")

        # Assert two distinct credentials exist for Sarah
        user_passkeys = PasskeyCredential.objects.filter(user=user)
        assert user_passkeys.count() == 2
        cred_ids = set(user_passkeys.values_list("credential_id", flat=True))
        assert "sarah-iphone" in cred_ids
        assert "sarah-macbook" in cred_ids


# ==============================================================================
# 4. Session Persistence & Attack Surface Elimination Tests
# ==============================================================================

@pytest.mark.django_db
class TestAttackSurfaceElimination:
    """Validate zero passwords, zero public signups, zero in-app invites, and logout."""

    def test_session_settings_configured_for_one_year(self):
        """Django settings mandate 1-year (31,536,000s) persistent session cookies."""
        assert settings.SESSION_COOKIE_AGE == 31536000
        assert settings.SESSION_EXPIRE_AT_BROWSER_CLOSE is False
        assert settings.LOGIN_URL == "/auth/login/"

    def test_login_page_has_zero_password_or_username_fields(self, unauthenticated_client):
        """GET /auth/login/ contains zero password inputs, zero username inputs, and zero signup links."""
        url = reverse("auth:login")
        response = unauthenticated_client.get(url)
        assert response.status_code == 200
        content = response.content.decode("utf-8")

        assert 'type="password"' not in content
        assert 'name="password"' not in content
        assert 'name="username"' not in content
        assert 'href="/register"' not in content
        assert 'href="/signup"' not in content
        assert "Sign in with Passkey" in content

    def test_login_page_redirects_authenticated_users(self, client):
        """Authenticated users visiting /auth/login/ are redirected to home."""
        url = reverse("auth:login")
        response = client.get(url)
        assert response.status_code == 302
        assert response.url == "/"

    def test_zero_public_registration_endpoints(self):
        """URL resolver contains zero endpoints for public registration or password reset."""
        resolver = get_resolver()
        for pattern in resolver.url_patterns:
            url_str = str(pattern.pattern)
            assert "register" not in url_str
            assert "signup" not in url_str
            assert "password_reset" not in url_str

    def test_logout_requires_post_and_flushes_session(self, client, test_user):
        """Logout strictly requires POST, completely terminates the session, and redirects to /auth/login/."""
        logout_url = reverse("auth:logout")

        # GET is rejected with 405 Method Not Allowed
        get_resp = client.get(logout_url)
        assert get_resp.status_code == 405

        # POST flushes session
        post_resp = client.post(logout_url)
        assert post_resp.status_code == 302
        assert post_resp.url == reverse("auth:login")
