"""Milestone M2 Remediation Empirical Stress and Adversarial Verification Suite.

Challenger 2 (teamwork_preview_challenger_m2_r2_2)

Rigorous empirical verification of:
1. Concurrency Stress Testing:
   - Multi-threaded parallel token redemption (`POST /auth/invite/<token>/redeem/`) under SQLite contention.
   - Multi-threaded parallel WebAuthn registration verification (`POST /auth/webauthn/register/verify/`).
   - Cross-endpoint concurrency race (direct redeem vs WebAuthn registration) with synchronized barrier.
   - Zero HTTP 500s (no unhandled SQLite OperationalError), exactly 1 winner, remaining requests get 400/403/409.
   - SQLite retry loop behavior: recovery on transient locks, and graceful HTTP 409 on exhausted retries.
2. Token Hash Binding:
   - Verify HTTP 403 Forbidden when request token hash does not match session['webauthn_reg_token_hash'].
   - Verify token state integrity (neither token marked used, zero credentials created).
   - Session challenge and token hash cleanup upon completion.
3. Validation Ordering:
   - Verify HTTP 403 Forbidden precedes HTTP 400 Bad Request when credentials are empty/missing on invalid tokens.
4. Session Persistence:
   - Verify SESSION_COOKIE_AGE is 31,536,000s and SESSION_EXPIRE_AT_BROWSER_CLOSE is False.
   - Verify session cookie attributes (Max-Age, HttpOnly, SameSite).
   - Verify session survives simulated browser restart across fresh clients.
   - Verify time-travel session validity at 30d, 180d, 360d and expiration at 366d.
"""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from importlib import import_module
from unittest.mock import patch

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import OperationalError
from django.test import Client, TransactionTestCase
from django.utils import timezone

from recipes.models import Household, InviteToken, PasskeyCredential, UserProfile
from recipes.webauthn_service import build_mock_assertion_payload, build_mock_registration_payload

User = get_user_model()
SessionStore = import_module(settings.SESSION_ENGINE).SessionStore


# ==============================================================================
# 1. Concurrency Stress Testing (Multi-Threaded SQLite Contention)
# ==============================================================================

class TestConcurrencyStressHarness(TransactionTestCase):
    """Empirical multi-threaded concurrency stress testing against SQLite row/table locking."""

    def test_high_concurrency_invite_redeem_10_threads(self):
        """10 parallel threads racing to redeem the same single-use token simultaneously."""
        hh = Household.objects.create(name="Concurrency HH 1")
        user = User.objects.create_user(username="stress_redeem_user")
        UserProfile.objects.create(user=user, household=hh)

        invite, raw_token = InviteToken.create_token(user=user, household=hh, expires_hours=48)
        redeem_url = f"/auth/invite/{raw_token}/redeem/"

        num_threads = 10
        barrier = threading.Barrier(num_threads)
        results = []

        def worker(thread_idx):
            client = Client(raise_request_exception=False)
            barrier.wait(timeout=5.0)
            response = client.post(redeem_url)
            return response.status_code

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(worker, i) for i in range(num_threads)]
            for f in futures:
                results.append(f.result())

        # Zero unhandled server errors (no HTTP 500)
        server_errors = [c for c in results if c == 500]
        assert len(server_errors) == 0, f"Found HTTP 500 errors under concurrency: {results}"

        # Exactly 1 thread must succeed (HTTP 302 redirect)
        winners = [c for c in results if c == 302]
        assert len(winners) == 1, f"Expected exactly 1 winner (302), got results: {results}"

        # All losing threads must receive graceful HTTP 400 (used) or HTTP 409 (busy)
        losers = [c for c in results if c != 302]
        assert len(losers) == num_threads - 1
        for code in losers:
            assert code in (400, 409), f"Unexpected status code for loser: {code}"

        # Verify DB state
        invite.refresh_from_db()
        assert invite.is_used is True
        assert invite.used_at is not None
        assert invite.is_valid is False

    def test_high_concurrency_webauthn_register_verify_10_threads(self):
        """10 parallel threads racing to complete WebAuthn register verify for the same token."""
        hh = Household.objects.create(name="Concurrency HH 2")
        user = User.objects.create_user(username="stress_webauthn_user")
        UserProfile.objects.create(user=user, household=hh)

        invite, raw_token = InviteToken.create_token(user=user, household=hh, expires_hours=48)

        # Generate registration options to obtain a valid challenge
        setup_client = Client()
        opt_resp = setup_client.post(
            "/auth/webauthn/register/options/",
            data=json.dumps({"token": raw_token}),
            content_type="application/json",
        )
        assert opt_resp.status_code == 200
        challenge = opt_resp.json()["challenge"]
        token_hash = InviteToken.hash_token(raw_token)

        # Pre-seed 10 independent session stores with matching challenge and token hash
        num_threads = 10
        session_keys = []
        for _ in range(num_threads):
            s = SessionStore()
            s["webauthn_reg_challenge"] = challenge
            s["webauthn_reg_token_hash"] = token_hash
            s.save()
            session_keys.append(s.session_key)

        barrier = threading.Barrier(num_threads)
        results = []

        def worker(idx):
            client = Client(raise_request_exception=False)
            client.cookies[settings.SESSION_COOKIE_NAME] = session_keys[idx]
            cred_payload = build_mock_registration_payload(
                user=user,
                challenge=challenge,
                credential_id=f"concurrent-cred-{idx}",
            )
            data = {
                "token": raw_token,
                "credential": cred_payload,
                "name": f"Device {idx}",
            }
            barrier.wait(timeout=5.0)
            response = client.post(
                "/auth/webauthn/register/verify/",
                data=json.dumps(data),
                content_type="application/json",
            )
            return response.status_code

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(worker, i) for i in range(num_threads)]
            for f in futures:
                results.append(f.result())

        # Zero HTTP 500s
        server_errors = [c for c in results if c == 500]
        assert len(server_errors) == 0, f"Found HTTP 500 errors in webauthn verify: {results}"

        # Exactly 1 winner (HTTP 200)
        winners = [c for c in results if c == 200]
        assert len(winners) == 1, f"Expected exactly 1 registration winner (200), got: {results}"

        # Losing threads must receive HTTP 403 (token used/invalid) or HTTP 409 (busy)
        losers = [c for c in results if c != 200]
        assert len(losers) == num_threads - 1
        for code in losers:
            assert code in (403, 409), f"Unexpected status code for losing registration: {code}"

        # Exactly 1 PasskeyCredential was registered in DB
        assert PasskeyCredential.objects.filter(user=user).count() == 1

        # Token is marked as used
        invite.refresh_from_db()
        assert invite.is_used is True
        assert invite.is_valid is False

    def test_mixed_concurrency_redeem_vs_webauthn_verify_20_threads(self):
        """20 parallel threads: 10 direct redeem vs 10 WebAuthn verify racing for the same token."""
        hh = Household.objects.create(name="Concurrency HH 3")
        user = User.objects.create_user(username="stress_mixed_user")
        UserProfile.objects.create(user=user, household=hh)

        invite, raw_token = InviteToken.create_token(user=user, household=hh, expires_hours=48)
        token_hash = InviteToken.hash_token(raw_token)

        setup_client = Client()
        opt_resp = setup_client.post(
            "/auth/webauthn/register/options/",
            data=json.dumps({"token": raw_token}),
            content_type="application/json",
        )
        assert opt_resp.status_code == 200
        challenge = opt_resp.json()["challenge"]

        # Pre-seed 10 sessions for WebAuthn workers
        session_keys = []
        for _ in range(10):
            s = SessionStore()
            s["webauthn_reg_challenge"] = challenge
            s["webauthn_reg_token_hash"] = token_hash
            s.save()
            session_keys.append(s.session_key)

        total_threads = 20
        barrier = threading.Barrier(total_threads)
        results = []

        def worker_redeem(idx):
            client = Client(raise_request_exception=False)
            barrier.wait(timeout=5.0)
            r = client.post(f"/auth/invite/{raw_token}/redeem/")
            return ("redeem", r.status_code)

        def worker_webauthn(idx):
            client = Client(raise_request_exception=False)
            client.cookies[settings.SESSION_COOKIE_NAME] = session_keys[idx]
            cred_payload = build_mock_registration_payload(
                user=user,
                challenge=challenge,
                credential_id=f"mixed-cred-{idx}",
            )
            barrier.wait(timeout=5.0)
            r = client.post(
                "/auth/webauthn/register/verify/",
                data=json.dumps({
                    "token": raw_token,
                    "credential": cred_payload,
                    "name": f"Mixed Device {idx}",
                }),
                content_type="application/json",
            )
            return ("webauthn", r.status_code)

        with ThreadPoolExecutor(max_workers=total_threads) as executor:
            futures = []
            for i in range(10):
                futures.append(executor.submit(worker_redeem, i))
                futures.append(executor.submit(worker_webauthn, i))
            for f in futures:
                results.append(f.result())

        # Zero 500 errors across all 20 threads
        server_errors = [res for res in results if res[1] == 500]
        assert len(server_errors) == 0, f"Found HTTP 500 errors in mixed concurrency: {results}"

        # Total successful redemptions across both channels must be EXACTLY 1
        redeem_winners = [res for res in results if res[0] == "redeem" and res[1] == 302]
        webauthn_winners = [res for res in results if res[0] == "webauthn" and res[1] == 200]
        total_winners = len(redeem_winners) + len(webauthn_winners)
        assert total_winners == 1, (
            f"Expected exactly 1 total winner, got {len(redeem_winners)} redeem winners and "
            f"{len(webauthn_winners)} webauthn winners. All results: {results}"
        )

        # Database state consistency
        invite.refresh_from_db()
        assert invite.is_used is True
        assert invite.is_valid is False

        cred_count = PasskeyCredential.objects.filter(user=user).count()
        if len(webauthn_winners) == 1:
            assert cred_count == 1
        else:
            assert cred_count == 0

    def test_sqlite_retry_loop_recovers_from_transient_lock(self):
        """Simulate transient SQLite locks where attempts 1 and 2 fail, and attempt 3 succeeds."""
        from django.db.models.query import QuerySet

        hh = Household.objects.create(name="Transient Lock HH")
        user = User.objects.create_user(username="transient_user")
        UserProfile.objects.create(user=user, household=hh)

        invite, raw_token = InviteToken.create_token(user=user, household=hh, expires_hours=48)
        client = Client()

        attempt_count = 0
        orig_first = QuerySet.first

        def flaky_first_call(queryset_self, *args, **kwargs):
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count <= 2:
                raise OperationalError("database table is locked: recipes_invitetoken")
            return orig_first(queryset_self, *args, **kwargs)

        with patch.object(QuerySet, "first", flaky_first_call):
            response = client.post(f"/auth/invite/{raw_token}/redeem/")

        assert response.status_code == 302
        assert attempt_count >= 3
        invite.refresh_from_db()
        assert invite.is_used is True

    def test_sqlite_retry_exhaustion_returns_409_not_500(self):
        """When SQLite lock persists across all 5 retries, views return HTTP 409 Conflict, never 500."""
        from django.db.models.query import QuerySet

        hh = Household.objects.create(name="Exhausted Lock HH")
        user = User.objects.create_user(username="exhausted_user")
        UserProfile.objects.create(user=user, household=hh)

        invite, raw_token = InviteToken.create_token(user=user, household=hh, expires_hours=48)
        client = Client()

        with patch.object(QuerySet, "first", side_effect=OperationalError("database is locked")):
            # 1. Direct redeem returns 409
            redeem_resp = client.post(f"/auth/invite/{raw_token}/redeem/")
            assert redeem_resp.status_code == 409
            assert "database busy" in redeem_resp.content.decode("utf-8").lower()

            # 2. WebAuthn register verify returns 409
            s = client.session
            s["webauthn_reg_challenge"] = "dummy_chal"
            s["webauthn_reg_token_hash"] = invite.token_hash
            s.save()

            verify_resp = client.post(
                "/auth/webauthn/register/verify/",
                data=json.dumps({"token": raw_token, "credential": {"id": "x"}}),
                content_type="application/json",
            )
            assert verify_resp.status_code == 409
            assert "database busy" in verify_resp.json().get("error", "").lower()


# ==============================================================================
# 2. Token Hash Binding Tests
# ==============================================================================

@pytest.mark.django_db
class TestTokenHashBinding:
    """Challenge token binding between registration options initiation and verification."""

    def test_token_hash_mismatch_returns_strict_403_and_preserves_tokens(self, client):
        """Using Token B to verify an options session initiated with Token A yields HTTP 403."""
        hh = Household.objects.create(name="Hash Binding HH")
        user = User.objects.create_user(username="binding_user")
        UserProfile.objects.create(user=user, household=hh)

        invite_a, token_a = InviteToken.create_token(user=user, household=hh)
        invite_b, token_b = InviteToken.create_token(user=user, household=hh)

        # Initiate registration with Token A
        opt_resp = client.post(
            "/auth/webauthn/register/options/",
            data=json.dumps({"token": token_a}),
            content_type="application/json",
        )
        assert opt_resp.status_code == 200
        challenge = opt_resp.json()["challenge"]

        # Verify session was populated with Token A's hash
        assert client.session["webauthn_reg_token_hash"] == invite_a.token_hash

        # Attempt to verify with Token B
        payload = build_mock_registration_payload(user=user, challenge=challenge)
        verify_resp = client.post(
            "/auth/webauthn/register/verify/",
            data=json.dumps({"token": token_b, "credential": payload, "name": "Mismatched Device"}),
            content_type="application/json",
        )
        assert verify_resp.status_code == 403
        data = verify_resp.json()
        assert "Invite token does not match registration session." in data["error"]

        # Assert neither token was consumed
        invite_a.refresh_from_db()
        invite_b.refresh_from_db()
        assert invite_a.is_used is False
        assert invite_b.is_used is False
        assert PasskeyCredential.objects.filter(name="Mismatched Device").count() == 0

    def test_tampered_session_token_hash_rejected_403(self, client):
        """Direct tampering with the session's token hash causes verification to fail with HTTP 403."""
        hh = Household.objects.create(name="Tamper HH")
        user = User.objects.create_user(username="tamper_user")
        UserProfile.objects.create(user=user, household=hh)

        invite, raw_token = InviteToken.create_token(user=user, household=hh)

        opt_resp = client.post(
            "/auth/webauthn/register/options/",
            data=json.dumps({"token": raw_token}),
            content_type="application/json",
        )
        challenge = opt_resp.json()["challenge"]

        # Tamper with session token hash
        session = client.session
        session["webauthn_reg_token_hash"] = "0" * 64
        session.save()

        payload = build_mock_registration_payload(user=user, challenge=challenge)
        verify_resp = client.post(
            "/auth/webauthn/register/verify/",
            data=json.dumps({"token": raw_token, "credential": payload}),
            content_type="application/json",
        )
        assert verify_resp.status_code == 403
        assert "does not match registration session" in verify_resp.json()["error"]

    def test_session_tokens_and_challenges_cleared_after_successful_verification(self, client):
        """Successful verification purges webauthn_reg_token_hash and webauthn_reg_challenge from session."""
        hh = Household.objects.create(name="Cleanup HH")
        user = User.objects.create_user(username="cleanup_user")
        UserProfile.objects.create(user=user, household=hh)

        invite, raw_token = InviteToken.create_token(user=user, household=hh)

        opt_resp = client.post(
            "/auth/webauthn/register/options/",
            data=json.dumps({"token": raw_token}),
            content_type="application/json",
        )
        challenge = opt_resp.json()["challenge"]

        payload = build_mock_registration_payload(user=user, challenge=challenge)
        verify_resp = client.post(
            "/auth/webauthn/register/verify/",
            data=json.dumps({"token": raw_token, "credential": payload}),
            content_type="application/json",
        )
        assert verify_resp.status_code == 200

        # Session keys must be wiped to prevent replay
        assert "webauthn_reg_challenge" not in client.session
        assert "webauthn_reg_token_hash" not in client.session


# ==============================================================================
# 3. Validation Ordering Tests (403 Forbidden before 400 Bad Request)
# ==============================================================================

@pytest.mark.django_db
class TestValidationOrdering:
    """Verify that token authorization (HTTP 403) strictly precedes payload format checks (HTTP 400)."""

    def test_empty_credential_missing_token_returns_403(self, client):
        """Missing token returns 403 even with completely empty payload."""
        resp = client.post(
            "/auth/webauthn/register/verify/",
            data=json.dumps({"credential": {}}),
            content_type="application/json",
        )
        assert resp.status_code == 403
        assert "token is required" in resp.json()["error"].lower()

    def test_empty_credential_whitespace_token_returns_403(self, client):
        """Whitespace-only token returns 403 even with empty credential dictionary."""
        resp = client.post(
            "/auth/webauthn/register/verify/",
            data=json.dumps({"token": "   ", "credential": {}}),
            content_type="application/json",
        )
        assert resp.status_code == 403
        assert "token is required" in resp.json()["error"].lower()

    def test_empty_credential_invalid_token_returns_403(self, client):
        """Non-existent token returns 403 even with empty credential dictionary."""
        resp = client.post(
            "/auth/webauthn/register/verify/",
            data=json.dumps({"token": "completely_bogus_token", "credential": {}}),
            content_type="application/json",
        )
        assert resp.status_code == 403
        assert "invalid, expired, or already used" in resp.json()["error"].lower()

    def test_empty_credential_expired_token_returns_403(self, client):
        """Expired token returns 403 even with empty credential dictionary."""
        hh = Household.objects.create(name="Expired Order HH")
        user = User.objects.create_user(username="exp_order_user")
        UserProfile.objects.create(user=user, household=hh)

        invite, raw_token = InviteToken.create_token(user=user, household=hh, expires_hours=48)
        invite.expires_at = timezone.now() - timedelta(hours=1)
        invite.save()

        resp = client.post(
            "/auth/webauthn/register/verify/",
            data=json.dumps({"token": raw_token, "credential": {}}),
            content_type="application/json",
        )
        assert resp.status_code == 403
        assert "invalid, expired, or already used" in resp.json()["error"].lower()

    def test_empty_credential_used_token_returns_403(self, client):
        """Already-used token returns 403 even with empty credential dictionary."""
        hh = Household.objects.create(name="Used Order HH")
        user = User.objects.create_user(username="used_order_user")
        UserProfile.objects.create(user=user, household=hh)

        invite, raw_token = InviteToken.create_token(user=user, household=hh, expires_hours=48)
        invite.mark_as_used(commit=True)

        resp = client.post(
            "/auth/webauthn/register/verify/",
            data=json.dumps({"token": raw_token, "credential": {}}),
            content_type="application/json",
        )
        assert resp.status_code == 403
        assert "invalid, expired, or already used" in resp.json()["error"].lower()

    def test_empty_credential_with_valid_token_and_session_returns_400(self, client):
        """Only when token is valid and session matches does an empty credential return 400 Bad Request."""
        hh = Household.objects.create(name="Valid Token Order HH")
        user = User.objects.create_user(username="valid_order_user")
        UserProfile.objects.create(user=user, household=hh)

        invite, raw_token = InviteToken.create_token(user=user, household=hh, expires_hours=48)

        # Step 1: options sets session
        opt_resp = client.post(
            "/auth/webauthn/register/options/",
            data=json.dumps({"token": raw_token}),
            content_type="application/json",
        )
        assert opt_resp.status_code == 200

        # Step 2: verify with valid token but empty/missing credential
        resp = client.post(
            "/auth/webauthn/register/verify/",
            data=json.dumps({"token": raw_token, "credential": {}}),
            content_type="application/json",
        )
        assert resp.status_code == 400
        assert "Missing credential payload." in resp.json()["error"]


# ==============================================================================
# 4. Session Persistence Tests (1-Year Duration & Browser Restart)
# ==============================================================================

@pytest.mark.django_db
class TestSessionPersistence:
    """Verify 1-year (31,536,000s) persistent session configuration and survival across browser restarts."""

    def test_session_settings_mandates(self):
        """Settings explicitly mandate 31,536,000s cookie age and persistent sessions."""
        assert settings.SESSION_COOKIE_AGE == 31536000
        assert settings.SESSION_EXPIRE_AT_BROWSER_CLOSE is False
        assert settings.SESSION_COOKIE_HTTPONLY is True
        assert settings.SESSION_COOKIE_SAMESITE == "Lax"

    def test_direct_redeem_establishes_1_year_cookie_and_expiry(self, client):
        """Direct token redemption returns session cookie configured for 1 year."""
        hh = Household.objects.create(name="Session HH 1")
        user = User.objects.create_user(username="session_redeem_user")
        UserProfile.objects.create(user=user, household=hh)

        invite, raw_token = InviteToken.create_token(user=user, household=hh)
        response = client.post(f"/auth/invite/{raw_token}/redeem/")
        assert response.status_code == 302

        # Verify session expiry age on server session
        assert client.session.get_expiry_age() == 31536000
        assert client.session.get_expire_at_browser_close() is False

        # Verify response Set-Cookie header contains Max-Age
        session_cookie = response.cookies.get(settings.SESSION_COOKIE_NAME)
        assert session_cookie is not None
        assert session_cookie["max-age"] == 31536000
        assert session_cookie["httponly"] is True
        assert session_cookie["samesite"] == "Lax"

    def test_webauthn_register_establishes_1_year_session(self, client):
        """Passkey registration sets 1-year session expiry."""
        hh = Household.objects.create(name="Session HH 2")
        user = User.objects.create_user(username="session_reg_user")
        UserProfile.objects.create(user=user, household=hh)

        invite, raw_token = InviteToken.create_token(user=user, household=hh)
        opt_resp = client.post(
            "/auth/webauthn/register/options/",
            data=json.dumps({"token": raw_token}),
            content_type="application/json",
        )
        challenge = opt_resp.json()["challenge"]

        payload = build_mock_registration_payload(user=user, challenge=challenge)
        verify_resp = client.post(
            "/auth/webauthn/register/verify/",
            data=json.dumps({"token": raw_token, "credential": payload}),
            content_type="application/json",
        )
        assert verify_resp.status_code == 200
        assert client.session.get_expiry_age() == 31536000
        assert client.session.get_expire_at_browser_close() is False

    def test_webauthn_login_establishes_1_year_session(self, client):
        """Passkey login sets 1-year session expiry."""
        hh = Household.objects.create(name="Session HH 3")
        user = User.objects.create_user(username="session_login_user")
        UserProfile.objects.create(user=user, household=hh)

        # Register a passkey credential
        invite, raw_token = InviteToken.create_token(user=user, household=hh)
        opt_resp = client.post(
            "/auth/webauthn/register/options/",
            data=json.dumps({"token": raw_token}),
            content_type="application/json",
        )
        chal = opt_resp.json()["challenge"]
        payload = build_mock_registration_payload(user=user, challenge=chal, credential_id="login-test-cred")
        client.post(
            "/auth/webauthn/register/verify/",
            data=json.dumps({"token": raw_token, "credential": payload}),
            content_type="application/json",
        )

        # Log out
        client.post("/auth/logout/")

        # Login with passkey
        login_opt = client.post("/auth/webauthn/login/options/", data=json.dumps({}), content_type="application/json")
        login_chal = login_opt.json()["challenge"]

        assertion = build_mock_assertion_payload(
            credential_id="login-test-cred",
            challenge=login_chal,
            sign_count=1,
        )
        login_resp = client.post(
            "/auth/webauthn/login/verify/",
            data=json.dumps({"credential": assertion}),
            content_type="application/json",
        )
        assert login_resp.status_code == 200
        assert client.session.get_expiry_age() == 31536000
        assert client.session.get_expire_at_browser_close() is False

    def test_session_persists_across_simulated_browser_restart(self):
        """Simulate closing browser process and opening new browser with persisted cookie."""
        hh = Household.objects.create(name="Restart HH")
        user = User.objects.create_user(username="restart_user")
        UserProfile.objects.create(user=user, household=hh)

        # Browser 1: User redeems invite link
        browser1 = Client()
        invite, raw_token = InviteToken.create_token(user=user, household=hh)
        resp1 = browser1.post(f"/auth/invite/{raw_token}/redeem/")
        assert resp1.status_code == 302

        # Extract persisted session cookie from Browser 1
        session_cookie = browser1.cookies[settings.SESSION_COOKIE_NAME]
        session_key = session_cookie.value

        # Browser 1 process terminates (deleted from memory)
        del browser1

        # Browser 2: New browser instance opens, reads persisted cookie from disk
        browser2 = Client()
        browser2.cookies[settings.SESSION_COOKIE_NAME] = session_key

        # Browser 2 navigates to login page — should redirect to / because already authenticated!
        login_resp = browser2.get("/auth/login/")
        assert login_resp.status_code == 302
        assert login_resp.url == "/"

        # Browser 2 navigates to home page
        home_resp = browser2.get("/")
        assert home_resp.status_code == 200
        assert home_resp.wsgi_request.user.is_authenticated
        assert home_resp.wsgi_request.user.username == "restart_user"

    def test_session_time_travel_survival_and_expiration_boundary(self, client):
        """Session remains valid after 30d, 180d, 360d, and expires after 365d + 1h."""
        hh = Household.objects.create(name="Time Travel HH")
        user = User.objects.create_user(username="time_travel_user")
        UserProfile.objects.create(user=user, household=hh)

        invite, raw_token = InviteToken.create_token(user=user, household=hh)
        client.post(f"/auth/invite/{raw_token}/redeem/")
        session_key = client.cookies[settings.SESSION_COOKIE_NAME].value

        session_store = SessionStore(session_key=session_key)
        expiry_date = session_store.get_expiry_date()
        now = timezone.now()

        # Expected expiry date is roughly 365 days in the future
        diff = expiry_date - now
        assert abs(diff.total_seconds() - 31536000) < 5.0

        # Advance 30 days
        with patch("django.utils.timezone.now", return_value=now + timedelta(days=30)):
            s30 = SessionStore(session_key=session_key)
            assert not s30.is_empty()
            assert s30.get_expiry_date() > now + timedelta(days=30)

        # Advance 180 days (half year)
        with patch("django.utils.timezone.now", return_value=now + timedelta(days=180)):
            s180 = SessionStore(session_key=session_key)
            assert not s180.is_empty()
            assert s180.get_expiry_date() > now + timedelta(days=180)

        # Advance 360 days
        with patch("django.utils.timezone.now", return_value=now + timedelta(days=360)):
            s360 = SessionStore(session_key=session_key)
            assert not s360.is_empty()
            assert s360.get_expiry_date() > now + timedelta(days=360)

        # Advance 366 days (exceeded 1 year)
        with patch("django.utils.timezone.now", return_value=now + timedelta(days=366)):
            s366 = SessionStore(session_key=session_key)
            # In Django SessionStore, an expired session is cleared/empty
            loaded = s366.load()
            assert loaded == {}, f"Expected empty session after 366 days, got: {loaded}"
