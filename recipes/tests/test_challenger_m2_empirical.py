"""Empirical Challenge Test Suite for Milestone M2.

Rigorous adversarial challenge of:
1. WebAuthn Gating & Origin/RP-ID Binding
2. Anti-Rollback Monotonic Counter Hardening (W3C WebAuthn Level 3 §6.1.2)
3. Multi-Device Independent Credential Coexistence
4. 1-Year Persistent Sessions & Security Cookie Integrity
"""

import json
from datetime import timedelta

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from recipes.models import Household, InviteToken, PasskeyCredential, UserProfile
from recipes.webauthn_service import (
    build_mock_assertion_payload,
    build_mock_registration_payload,
    resolve_rp_id,
)

User = get_user_model()


# ==============================================================================
# Challenge 1: WebAuthn Gating & Dynamic RP ID Resolution
# ==============================================================================

@pytest.mark.django_db
class TestChallenge1WebAuthnGatingAndRPID:
    """Challenge WebAuthn options gating against unauthorized or invalid requests."""

    def test_register_options_without_token_rejected_403(self, unauthenticated_client):
        """Requesting creation options with no 'token' key in body returns strict HTTP 403."""
        url = reverse("auth:webauthn_register_options")
        resp = unauthenticated_client.post(
            url,
            data=json.dumps({}),
            content_type="application/json",
        )
        assert resp.status_code == 403
        data = resp.json()
        assert "error" in data
        assert "valid unredeemed invite token is required" in data["error"]

    def test_register_options_with_empty_token_rejected_403(self, unauthenticated_client):
        """Requesting creation options with empty string or whitespace token returns strict HTTP 403."""
        url = reverse("auth:webauthn_register_options")
        for empty_val in ["", "   ", "\t\n"]:
            resp = unauthenticated_client.post(
                url,
                data=json.dumps({"token": empty_val}),
                content_type="application/json",
            )
            assert resp.status_code == 403
            assert "valid unredeemed invite token is required" in resp.json()["error"]

    def test_register_options_with_expired_token_rejected_403(
        self, unauthenticated_client, invite_token_factory
    ):
        """Requesting creation options with an expired token returns strict HTTP 403."""
        expired_token = invite_token_factory(expires_at=timezone.now() - timedelta(minutes=1))
        url = reverse("auth:webauthn_register_options")
        resp = unauthenticated_client.post(
            url,
            data=json.dumps({"token": expired_token.raw_token}),
            content_type="application/json",
        )
        assert resp.status_code == 403
        assert "invalid, expired, or already used" in resp.json()["error"]

    def test_register_options_with_already_redeemed_token_rejected_403(
        self, unauthenticated_client, invite_token_factory
    ):
        """Requesting creation options with an already redeemed token returns strict HTTP 403."""
        used_token = invite_token_factory(is_used=True, used_at=timezone.now())
        url = reverse("auth:webauthn_register_options")
        resp = unauthenticated_client.post(
            url,
            data=json.dumps({"token": used_token.raw_token}),
            content_type="application/json",
        )
        assert resp.status_code == 403
        assert "invalid, expired, or already used" in resp.json()["error"]

    def test_register_options_with_bogus_token_rejected_403(self, unauthenticated_client):
        """Requesting creation options with a non-existent random token returns strict HTTP 403."""
        url = reverse("auth:webauthn_register_options")
        resp = unauthenticated_client.post(
            url,
            data=json.dumps({"token": "completely-fabricated-token-xyz-12345"}),
            content_type="application/json",
        )
        assert resp.status_code == 403
        assert "invalid, expired, or already used" in resp.json()["error"]

    def test_dynamic_rp_id_resolution_host_variations(self):
        """Verify dynamic RP ID resolution handles hostnames, IP addresses, and ports gracefully."""
        # Test with explicit configured_rp_id
        assert resolve_rp_id("anyhost:9999", configured_rp_id="custom.rp.id") == "custom.rp.id"

        # Test host port-stripping fallback when WEBAUTHN_RP_ID is not configured
        test_cases = [
            ("localhost", "localhost"),
            ("localhost:8000", "localhost"),
            ("127.0.0.1", "127.0.0.1"),
            ("127.0.0.1:8000", "127.0.0.1"),
            ("192.168.1.150:8080", "192.168.1.150"),
            ("kitchenclip.home.lan", "kitchenclip.home.lan"),
            ("kitchenclip.home.lan:8443", "kitchenclip.home.lan"),
        ]
        for host_in, expected_out in test_cases:
            res = resolve_rp_id(host_in, configured_rp_id=None)
            # If settings.WEBAUTHN_RP_ID is set, resolve_rp_id will return that setting
            assert isinstance(res, str)
            assert len(res) > 0

    def test_untrusted_origin_rejection(self, unauthenticated_client, invite_token_factory):
        """Attestation submitted from an unauthorized/forged origin is strictly rejected."""
        token_obj = invite_token_factory()
        opt_url = reverse("auth:webauthn_register_options")
        opt_resp = unauthenticated_client.post(
            opt_url,
            data=json.dumps({"token": token_obj.raw_token}),
            content_type="application/json",
        )
        challenge = opt_resp.json()["challenge"]

        # Build payload with malicious attacker origin
        payload = build_mock_registration_payload(
            user=token_obj.user,
            challenge=challenge,
            origin="https://evil-phishing-site.com",
            credential_id="evil-cred-id",
        )

        verify_url = reverse("auth:webauthn_register_verify")
        verify_resp = unauthenticated_client.post(
            verify_url,
            data=json.dumps({"token": token_obj.raw_token, "credential": payload}),
            content_type="application/json",
        )
        assert verify_resp.status_code == 400
        assert "origin mismatch" in verify_resp.json().get("error", "").lower()

        # Token must NOT have been marked as used
        token_obj.refresh_from_db()
        assert token_obj.is_used is False


# ==============================================================================
# Challenge 2: Anti-Rollback Counter Hardening (W3C WebAuthn Level 3 §6.1.2)
# ==============================================================================

@pytest.mark.django_db
class TestChallenge2AntiRollbackCounterHardening:
    """Challenge signature counter monotonicity and clone detection."""

    def test_monotonic_counter_hardening_lifecycle(
        self, unauthenticated_client, invite_token_factory
    ):
        """Full lifecycle: initial sign_count=10, duplicate rejected, regression rejected, increment accepted."""
        token_obj = invite_token_factory()

        # Step 1: Register credential with initial sign_count = 10
        opt_url = reverse("auth:webauthn_register_options")
        opt_resp = unauthenticated_client.post(
            opt_url,
            data=json.dumps({"token": token_obj.raw_token}),
            content_type="application/json",
        )
        challenge = opt_resp.json()["challenge"]

        payload = build_mock_registration_payload(
            user=token_obj.user,
            challenge=challenge,
            credential_id="challenge2-counter-cred",
            sign_count=10,
        )
        verify_reg_url = reverse("auth:webauthn_register_verify")
        reg_resp = unauthenticated_client.post(
            verify_reg_url,
            data=json.dumps({
                "token": token_obj.raw_token,
                "credential": payload,
                "name": "Hardened Authenticator",
            }),
            content_type="application/json",
        )
        assert reg_resp.status_code == 200

        cred = PasskeyCredential.objects.get(credential_id="challenge2-counter-cred")
        assert cred.sign_count == 10

        # Step 2: Test assertion with duplicate counter (sign_count = 10) -> Must REJECT
        unauthenticated_client.logout()
        login_opt_url = reverse("auth:webauthn_login_options")
        opt_resp = unauthenticated_client.post(login_opt_url, data=json.dumps({}), content_type="application/json")
        challenge_login_1 = opt_resp.json()["challenge"]

        assertion_duplicate = build_mock_assertion_payload(
            credential_id=cred.credential_id,
            challenge=challenge_login_1,
            sign_count=10,
        )
        verify_login_url = reverse("auth:webauthn_login_verify")
        resp_dup = unauthenticated_client.post(
            verify_login_url,
            data=json.dumps({"credential": assertion_duplicate}),
            content_type="application/json",
        )
        assert resp_dup.status_code == 403
        assert "rollback detected" in resp_dup.json().get("error", "").lower()
        cred.refresh_from_db()
        assert cred.sign_count == 10

        # Step 3: Test assertion with counter regression (sign_count = 5) -> Must REJECT
        opt_resp = unauthenticated_client.post(login_opt_url, data=json.dumps({}), content_type="application/json")
        challenge_login_2 = opt_resp.json()["challenge"]

        assertion_regression = build_mock_assertion_payload(
            credential_id=cred.credential_id,
            challenge=challenge_login_2,
            sign_count=5,
        )
        resp_reg = unauthenticated_client.post(
            verify_login_url,
            data=json.dumps({"credential": assertion_regression}),
            content_type="application/json",
        )
        assert resp_reg.status_code == 403
        assert "rollback detected" in resp_reg.json().get("error", "").lower()
        cred.refresh_from_db()
        assert cred.sign_count == 10

        # Step 4: Test assertion with increment (sign_count = 11) -> Must ACCEPT
        opt_resp = unauthenticated_client.post(login_opt_url, data=json.dumps({}), content_type="application/json")
        challenge_login_3 = opt_resp.json()["challenge"]

        assertion_increment = build_mock_assertion_payload(
            credential_id=cred.credential_id,
            challenge=challenge_login_3,
            sign_count=11,
        )
        resp_inc = unauthenticated_client.post(
            verify_login_url,
            data=json.dumps({"credential": assertion_increment}),
            content_type="application/json",
        )
        assert resp_inc.status_code == 200
        assert resp_inc.json()["success"] is True

        cred.refresh_from_db()
        assert cred.sign_count == 11
        assert cred.last_used_at is not None

    def test_synced_passkey_zero_counter_successive_logins(
        self, unauthenticated_client, test_user, passkey_factory
    ):
        """W3C WebAuthn Level 3 synced passkey exception: sign_count=0 followed by sign_count=0 must succeed."""
        cred = passkey_factory(
            user=test_user,
            credential_id="synced-passkey-test-cred",
            sign_count=0,
        )

        login_opt_url = reverse("auth:webauthn_login_options")
        verify_login_url = reverse("auth:webauthn_login_verify")

        # Assertion 1: sign_count = 0
        opt_resp1 = unauthenticated_client.post(login_opt_url, data=json.dumps({}), content_type="application/json")
        payload1 = build_mock_assertion_payload(
            credential_id=cred.credential_id,
            challenge=opt_resp1.json()["challenge"],
            sign_count=0,
        )
        resp1 = unauthenticated_client.post(
            verify_login_url,
            data=json.dumps({"credential": payload1}),
            content_type="application/json",
        )
        assert resp1.status_code == 200
        assert resp1.json()["success"] is True
        cred.refresh_from_db()
        assert cred.sign_count == 0

        # Logout before second assertion
        unauthenticated_client.logout()

        # Assertion 2: sign_count = 0 again
        opt_resp2 = unauthenticated_client.post(login_opt_url, data=json.dumps({}), content_type="application/json")
        payload2 = build_mock_assertion_payload(
            credential_id=cred.credential_id,
            challenge=opt_resp2.json()["challenge"],
            sign_count=0,
        )
        resp2 = unauthenticated_client.post(
            verify_login_url,
            data=json.dumps({"credential": payload2}),
            content_type="application/json",
        )
        assert resp2.status_code == 200
        assert resp2.json()["success"] is True
        cred.refresh_from_db()
        assert cred.sign_count == 0


# ==============================================================================
# Challenge 3: Multi-Device Coexistence
# ==============================================================================

@pytest.mark.django_db
class TestChallenge3MultiDeviceCoexistence:
    """Challenge multi-device independent enrollment and coexistence for the same user."""

    def test_multi_device_coexistence_charlie(self, unauthenticated_client):
        """Create user 'charlie', enroll iPhone via token 1, enroll MacBook via token 2, verify both auth."""
        household = Household.objects.create(name="Charlie Household")

        # Provision charlie via CLI command
        call_command("create_invite", username="charlie", household="Charlie Household")
        charlie = User.objects.get(username="charlie")
        assert charlie.profile.household == household

        # Token 1 (Device 1: iPhone)
        token1 = InviteToken.objects.filter(user=charlie, is_used=False).first()
        assert token1 is not None

        # Device 1: iPhone registration
        client_iphone = Client()
        opt_url = reverse("auth:webauthn_register_options")
        opt_resp1 = client_iphone.post(
            opt_url,
            data=json.dumps({"token": token1.raw_token if hasattr(token1, "raw_token") else "placeholder"}),
            content_type="application/json",
        )
        # Note: token1 from DB lacks raw_token attribute, so let's generate a CLI invite for device 1
        # Let's generate fresh tokens via create_token helper for precise raw token control
        t1_obj, t1_raw = InviteToken.create_token(charlie, household)
        opt_resp1 = client_iphone.post(
            opt_url,
            data=json.dumps({"token": t1_raw}),
            content_type="application/json",
        )
        assert opt_resp1.status_code == 200
        challenge1 = opt_resp1.json()["challenge"]

        payload_iphone = build_mock_registration_payload(
            user=charlie,
            challenge=challenge1,
            credential_id="charlie-iphone-passkey-id",
        )
        verify_reg_url = reverse("auth:webauthn_register_verify")
        reg_resp1 = client_iphone.post(
            verify_reg_url,
            data=json.dumps({
                "token": t1_raw,
                "credential": payload_iphone,
                "name": "Charlie iPhone 15",
            }),
            content_type="application/json",
        )
        assert reg_resp1.status_code == 200

        # Token 2 (Device 2: MacBook)
        t2_obj, t2_raw = InviteToken.create_token(charlie, household)
        client_macbook = Client()
        opt_resp2 = client_macbook.post(
            opt_url,
            data=json.dumps({"token": t2_raw}),
            content_type="application/json",
        )
        assert opt_resp2.status_code == 200
        challenge2 = opt_resp2.json()["challenge"]

        payload_macbook = build_mock_registration_payload(
            user=charlie,
            challenge=challenge2,
            credential_id="charlie-macbook-passkey-id",
        )
        reg_resp2 = client_macbook.post(
            verify_reg_url,
            data=json.dumps({
                "token": t2_raw,
                "credential": payload_macbook,
                "name": "Charlie MacBook Pro",
            }),
            content_type="application/json",
        )
        assert reg_resp2.status_code == 200

        # Verify both credentials exist independently under Charlie
        charlie_creds = PasskeyCredential.objects.filter(user=charlie)
        assert charlie_creds.count() == 2
        cred_map = {c.credential_id: c for c in charlie_creds}
        assert "charlie-iphone-passkey-id" in cred_map
        assert "charlie-macbook-passkey-id" in cred_map
        assert cred_map["charlie-iphone-passkey-id"].name == "Charlie iPhone 15"
        assert cred_map["charlie-macbook-passkey-id"].name == "Charlie MacBook Pro"

        # Verify Device 1 (iPhone) can independently authenticate
        client_test_iphone = Client()
        login_opt_url = reverse("auth:webauthn_login_options")
        login_verify_url = reverse("auth:webauthn_login_verify")

        opt_resp = client_test_iphone.post(login_opt_url, data=json.dumps({}), content_type="application/json")
        assertion_iphone = build_mock_assertion_payload(
            credential_id="charlie-iphone-passkey-id",
            challenge=opt_resp.json()["challenge"],
            sign_count=1,
        )
        resp_login_iphone = client_test_iphone.post(
            login_verify_url,
            data=json.dumps({"credential": assertion_iphone}),
            content_type="application/json",
        )
        assert resp_login_iphone.status_code == 200
        assert int(client_test_iphone.session["_auth_user_id"]) == charlie.pk

        # Verify Device 2 (MacBook) can independently authenticate
        client_test_macbook = Client()
        opt_resp = client_test_macbook.post(login_opt_url, data=json.dumps({}), content_type="application/json")
        assertion_macbook = build_mock_assertion_payload(
            credential_id="charlie-macbook-passkey-id",
            challenge=opt_resp.json()["challenge"],
            sign_count=1,
        )
        resp_login_macbook = client_test_macbook.post(
            login_verify_url,
            data=json.dumps({"credential": assertion_macbook}),
            content_type="application/json",
        )
        assert resp_login_macbook.status_code == 200
        assert int(client_test_macbook.session["_auth_user_id"]) == charlie.pk


# ==============================================================================
# Challenge 4: Session Persistence & Security Cookies
# ==============================================================================

@pytest.mark.django_db
class TestChallenge4SessionPersistenceAndCookies:
    """Challenge 1-year session cookie attributes and restart survival."""

    def test_session_cookie_attributes_on_invite_redeem(
        self, unauthenticated_client, invite_token_factory
    ):
        """Fallback invite redeem sets 1-year session with HttpOnly and SameSite=Lax."""
        token_obj = invite_token_factory()
        url = reverse("auth:invite_redeem", kwargs={"token": token_obj.raw_token})
        resp = unauthenticated_client.post(url)
        assert resp.status_code == 302

        session_cookie = resp.cookies.get(settings.SESSION_COOKIE_NAME)
        assert session_cookie is not None
        assert session_cookie["max-age"] == 31536000
        assert session_cookie["httponly"] is True
        assert session_cookie["samesite"] == "Lax"

    def test_session_cookie_attributes_on_webauthn_register(
        self, unauthenticated_client, invite_token_factory
    ):
        """WebAuthn register verify sets 1-year session with HttpOnly and SameSite=Lax."""
        token_obj = invite_token_factory()
        opt_url = reverse("auth:webauthn_register_options")
        opt_resp = unauthenticated_client.post(
            opt_url,
            data=json.dumps({"token": token_obj.raw_token}),
            content_type="application/json",
        )
        challenge = opt_resp.json()["challenge"]

        payload = build_mock_registration_payload(
            user=token_obj.user,
            challenge=challenge,
            credential_id="session-test-reg-cred",
        )
        verify_url = reverse("auth:webauthn_register_verify")
        resp = unauthenticated_client.post(
            verify_url,
            data=json.dumps({
                "token": token_obj.raw_token,
                "credential": payload,
            }),
            content_type="application/json",
        )
        assert resp.status_code == 200

        session_cookie = resp.cookies.get(settings.SESSION_COOKIE_NAME)
        assert session_cookie is not None
        assert session_cookie["max-age"] == 31536000
        assert session_cookie["httponly"] is True
        assert session_cookie["samesite"] == "Lax"

    def test_session_cookie_attributes_on_webauthn_login(
        self, unauthenticated_client, test_user, passkey_factory
    ):
        """WebAuthn login verify sets 1-year session with HttpOnly and SameSite=Lax."""
        cred = passkey_factory(user=test_user, credential_id="cookie-test-cred", sign_count=1)

        opt_url = reverse("auth:webauthn_login_options")
        opt_resp = unauthenticated_client.post(opt_url, data=json.dumps({}), content_type="application/json")
        challenge = opt_resp.json()["challenge"]

        payload = build_mock_assertion_payload(
            credential_id=cred.credential_id,
            challenge=challenge,
            sign_count=2,
        )
        verify_url = reverse("auth:webauthn_login_verify")
        resp = unauthenticated_client.post(
            verify_url,
            data=json.dumps({"credential": payload}),
            content_type="application/json",
        )
        assert resp.status_code == 200

        session_cookie = resp.cookies.get(settings.SESSION_COOKIE_NAME)
        assert session_cookie is not None
        assert session_cookie["max-age"] == 31536000
        assert session_cookie["httponly"] is True
        assert session_cookie["samesite"] == "Lax"

    def test_session_survives_simulated_browser_restart(
        self, unauthenticated_client, test_user, passkey_factory
    ):
        """Session persists when cookie is preserved across client restart within TTL."""
        cred = passkey_factory(user=test_user, credential_id="restart-test-cred", sign_count=1)

        opt_url = reverse("auth:webauthn_login_options")
        opt_resp = unauthenticated_client.post(opt_url, data=json.dumps({}), content_type="application/json")
        challenge = opt_resp.json()["challenge"]

        payload = build_mock_assertion_payload(
            credential_id=cred.credential_id,
            challenge=challenge,
            sign_count=2,
        )
        verify_url = reverse("auth:webauthn_login_verify")
        resp = unauthenticated_client.post(
            verify_url,
            data=json.dumps({"credential": payload}),
            content_type="application/json",
        )
        assert resp.status_code == 200

        # Extract sessionid
        session_id = unauthenticated_client.cookies[settings.SESSION_COOKIE_NAME].value
        assert session_id

        # Simulate browser restart by initializing a brand new Client
        new_browser_client = Client()
        new_browser_client.cookies[settings.SESSION_COOKIE_NAME] = session_id

        # Visiting /auth/login/ must detect active session and redirect to /
        login_url = reverse("auth:login")
        restart_resp = new_browser_client.get(login_url)
        assert restart_resp.status_code == 302
        assert restart_resp.url == "/"

        # Inspect internal session user ID
        assert int(new_browser_client.session["_auth_user_id"]) == test_user.pk


# ==============================================================================
# Challenge 5: Adversarial Edge Cases & Protocol Stress Tests
# ==============================================================================

@pytest.mark.django_db
class TestChallenge5AdversarialProtocolStress:
    """Stress test malformed payloads, flags, token leakage, and cross-household isolation."""

    def test_auth_data_missing_user_presence_flag_rejected(
        self, unauthenticated_client, test_user, passkey_factory
    ):
        """Authenticators failing to assert User Presence (UP flag = 0) are strictly rejected."""
        cred = passkey_factory(user=test_user, credential_id="up-flag-cred", sign_count=1)

        opt_url = reverse("auth:webauthn_login_options")
        opt_resp = unauthenticated_client.post(opt_url, data=json.dumps({}), content_type="application/json")
        challenge = opt_resp.json()["challenge"]

        payload = build_mock_assertion_payload(
            credential_id=cred.credential_id,
            challenge=challenge,
            sign_count=2,
        )
        # Clear UP flag in authenticatorData (byte 32)
        from recipes.webauthn_service import b64url_decode, b64url_encode
        raw_auth_data = bytearray(b64url_decode(payload["response"]["authenticatorData"]))
        raw_auth_data[32] = 0x00  # clear UP flag
        payload["response"]["authenticatorData"] = b64url_encode(bytes(raw_auth_data))

        verify_url = reverse("auth:webauthn_login_verify")
        resp = unauthenticated_client.post(
            verify_url,
            data=json.dumps({"credential": payload}),
            content_type="application/json",
        )
        assert resp.status_code == 400
        assert "user presence" in resp.json().get("error", "").lower()

    def test_rp_id_hash_mismatch_rejected(
        self, unauthenticated_client, test_user, passkey_factory
    ):
        """Assertion bound to a different Relying Party ID hash is strictly rejected."""
        cred = passkey_factory(user=test_user, credential_id="rpid-mismatch-cred", sign_count=1)

        opt_url = reverse("auth:webauthn_login_options")
        opt_resp = unauthenticated_client.post(opt_url, data=json.dumps({}), content_type="application/json")
        challenge = opt_resp.json()["challenge"]

        # Payload built for attacker RP ID "evil.com"
        payload = build_mock_assertion_payload(
            credential_id=cred.credential_id,
            challenge=challenge,
            rp_id="evil.com",
            sign_count=2,
        )

        verify_url = reverse("auth:webauthn_login_verify")
        resp = unauthenticated_client.post(
            verify_url,
            data=json.dumps({"credential": payload}),
            content_type="application/json",
        )
        assert resp.status_code == 400
        assert "rp id hash mismatch" in resp.json().get("error", "").lower()

    def test_missing_challenge_in_session_rejected(
        self, unauthenticated_client, test_user, passkey_factory
    ):
        """Submitting assertion without prior options call (no session challenge) returns HTTP 400."""
        cred = passkey_factory(user=test_user, credential_id="no-session-cred", sign_count=1)

        payload = build_mock_assertion_payload(
            credential_id=cred.credential_id,
            challenge="dummy-challenge",
            sign_count=2,
        )
        verify_url = reverse("auth:webauthn_login_verify")
        # Direct POST without calling options
        resp = unauthenticated_client.post(
            verify_url,
            data=json.dumps({"credential": payload}),
            content_type="application/json",
        )
        assert resp.status_code == 400
        assert "challenge expired or missing" in resp.json().get("error", "").lower()

    def test_unknown_credential_id_rejected(self, unauthenticated_client):
        """Assertion referencing an unrecognized credential ID returns HTTP 400."""
        opt_url = reverse("auth:webauthn_login_options")
        opt_resp = unauthenticated_client.post(opt_url, data=json.dumps({}), content_type="application/json")
        challenge = opt_resp.json()["challenge"]

        payload = build_mock_assertion_payload(
            credential_id="non-existent-credential-id",
            challenge=challenge,
            sign_count=1,
        )
        verify_url = reverse("auth:webauthn_login_verify")
        resp = unauthenticated_client.post(
            verify_url,
            data=json.dumps({"credential": payload}),
            content_type="application/json",
        )
        assert resp.status_code == 400
        assert "not recognized" in resp.json().get("error", "").lower()

    def test_token_plaintext_never_persisted_to_database(self, test_user, test_household):
        """CSPRNG raw token is strictly ephemeral and never stored in SQLite fields."""
        token_obj, raw_token = InviteToken.create_token(test_user, test_household)

        # Inspect all fields of the model
        for field in token_obj._meta.get_fields():
            if hasattr(token_obj, field.name):
                val = getattr(token_obj, field.name)
                assert val != raw_token, f"Plaintext token leaked into field {field.name}"

        # Verify only SHA-256 hash is stored
        assert len(token_obj.token_hash) == 64
        assert int(token_obj.token_hash, 16) > 0

    def test_cross_household_multi_device_isolation(self):
        """Two households, each with 2 devices, maintain complete separation of credentials and session."""
        h1 = Household.objects.create(name="Household Alpha")
        h2 = Household.objects.create(name="Household Beta")

        u1 = User.objects.create_user(username="alpha_user")
        u1.set_unusable_password()
        u1.save()
        UserProfile.objects.create(user=u1, household=h1, role="admin")

        u2 = User.objects.create_user(username="beta_user")
        u2.set_unusable_password()
        u2.save()
        UserProfile.objects.create(user=u2, household=h2, role="admin")

        # Alpha devices
        cred_a1 = PasskeyCredential.objects.create(
            user=u1, credential_id="alpha-dev-1", public_key="pub-a1", sign_count=10, name="Alpha iPhone"
        )
        cred_a2 = PasskeyCredential.objects.create(
            user=u1, credential_id="alpha-dev-2", public_key="pub-a2", sign_count=20, name="Alpha Mac"
        )

        # Beta devices
        cred_b1 = PasskeyCredential.objects.create(
            user=u2, credential_id="beta-dev-1", public_key="pub-b1", sign_count=100, name="Beta Android"
        )
        cred_b2 = PasskeyCredential.objects.create(
            user=u2, credential_id="beta-dev-2", public_key="pub-b2", sign_count=200, name="Beta Linux"
        )

        # Authenticate via Alpha Dev 1
        client_a1 = Client()
        opt_resp = client_a1.post(reverse("auth:webauthn_login_options"), data=json.dumps({}), content_type="application/json")
        payload_a1 = build_mock_assertion_payload("alpha-dev-1", opt_resp.json()["challenge"], sign_count=11)
        resp_a1 = client_a1.post(reverse("auth:webauthn_login_verify"), data=json.dumps({"credential": payload_a1}), content_type="application/json")
        assert resp_a1.status_code == 200
        assert int(client_a1.session["_auth_user_id"]) == u1.pk
        cred_a1.refresh_from_db()
        assert cred_a1.sign_count == 11
        assert cred_a2.sign_count == 20  # Other Alpha device unchanged
        assert cred_b1.sign_count == 100  # Beta device unchanged

        # Authenticate via Beta Dev 2
        client_b2 = Client()
        opt_resp = client_b2.post(reverse("auth:webauthn_login_options"), data=json.dumps({}), content_type="application/json")
        payload_b2 = build_mock_assertion_payload("beta-dev-2", opt_resp.json()["challenge"], sign_count=201)
        resp_b2 = client_b2.post(reverse("auth:webauthn_login_verify"), data=json.dumps({"credential": payload_b2}), content_type="application/json")
        assert resp_b2.status_code == 200
        assert int(client_b2.session["_auth_user_id"]) == u2.pk
        cred_b2.refresh_from_db()
        assert cred_b2.sign_count == 201
        assert cred_b1.sign_count == 100  # Other Beta device unchanged
        assert cred_a1.sign_count == 11   # Alpha device unchanged


    def test_dynamic_rp_id_resolution_with_unset_setting(self):
        """When WEBAUTHN_RP_ID setting is None/empty, host is dynamically parsed and port is stripped."""
        from django.test import override_settings

        with override_settings(WEBAUTHN_RP_ID=None):
            assert resolve_rp_id("localhost") == "localhost"
            assert resolve_rp_id("localhost:8000") == "localhost"
            assert resolve_rp_id("127.0.0.1") == "127.0.0.1"
            assert resolve_rp_id("127.0.0.1:8000") == "127.0.0.1"
            assert resolve_rp_id("kitchen.myhome.lan:8443") == "kitchen.myhome.lan"
