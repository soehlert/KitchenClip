"""Concurrency and SQLite contention test suite for KitchenClip authentication.

Tests multi-threaded race conditions against single-use token redemption, WebAuthn
registration verification, and SQLite lock retry recovery.
"""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import OperationalError
from django.db.models.query import QuerySet
from django.test import Client, TransactionTestCase

from recipes.models import Household, InviteToken, PasskeyCredential, UserProfile
from recipes.webauthn_service import build_mock_registration_payload

User = get_user_model()
SessionStore = import_module(settings.SESSION_ENGINE).SessionStore


class TestConcurrencyStressHarness(TransactionTestCase):
    """Multi-threaded concurrency stress testing against SQLite row/table locking."""

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
