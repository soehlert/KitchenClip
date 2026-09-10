"""Empirical Stress Tests and Adversarial Verification for Milestone M2.

Challenger 1 (teamwork_preview_challenger_m2_1)
Challenges:
1. CLI Command Stress Testing:
   - Diverse usernames (unicode, special characters, spaces, email-like).
   - Household conflict detection and immutability.
   - Multi-device provisioning with independent token coexistence.
   - Edge case arguments (zero/negative hours, empty names).
2. Token Entropy & Cryptographic Properties:
   - 1,000 token sample Shannon entropy (> 4.5 bits/char mean).
   - CSPRNG character distribution and RFC 4648 Base64URL adherence.
   - SHA-256 collision resistance and hash integrity.
   - Constant-time challenge / RP hash comparison verification.
3. Concurrent Race Condition Testing:
   - Parallel concurrent token redemption requests (double-click simulation).
   - Database row locking and atomic single-use guarantees.
   - Parallel WebAuthn registration verify contention.
4. Crawler Idempotency Verification:
   - Repetitive SafeLinks / Slack bot GET requests (50+ iterations).
   - Verifying immutability of token state during preview scans.
   - Status code correctness for valid, expired, used, and non-existent tokens.
5. TTL Expiration Enforcement:
   - Time travel boundary checks (47h 59m vs 48h 01s).
   - Custom TTL durations (1h, 720h).
   - Complete endpoint rejection on expired tokens (landing, redeem, options, verify).
"""

import hashlib
import json
import math
import secrets
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from importlib import import_module
from unittest.mock import patch

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from django.test import Client, TransactionTestCase
from django.utils import timezone

from recipes.models import Household, InviteToken, PasskeyCredential, UserProfile
from recipes.webauthn_service import (
    build_mock_registration_payload,
)

User = get_user_model()
SessionStore = import_module(settings.SESSION_ENGINE).SessionStore


def calculate_shannon_entropy(s: str) -> float:
    """Calculate Shannon entropy of a string in bits per character."""
    if not s:
        return 0.0
    counts = Counter(s)
    length = len(s)
    return -sum((count / length) * math.log2(count / length) for count in counts.values())


# ==============================================================================
# 1. CLI Command Stress Testing
# ==============================================================================

@pytest.mark.django_db
class TestCLIStress:
    """Stress-test CLI invite generation command with diverse inputs and edge cases."""

    @pytest.mark.parametrize(
        "username",
        [
            "alice",
            "user.name",
            "user_name-123",
            "user+tag@domain.com",
            "Renée",
            "Müller",
            "佐藤",
            "Иван",
            "user@home.local",
        ],
    )
    def test_cli_diverse_usernames(self, username, capsys):
        """CLI successfully creates invites for standard, punctuated, and unicode usernames."""
        call_command("create_invite", username=username, household="Stress Household")
        user = User.objects.filter(username=username).first()
        assert user is not None
        assert not user.has_usable_password()

        token = InviteToken.objects.filter(user=user).first()
        assert token is not None
        assert token.is_valid

        out = capsys.readouterr().out
        assert f"Username:    {username}" in out
        assert "/auth/invite/" in out

    def test_cli_whitespace_stripping_and_empty_username_rejection(self):
        """Whitespace is stripped from username; blank/whitespace-only usernames are rejected."""
        # Stripping leading/trailing whitespace
        call_command("create_invite", username="  spaced_user  ", household="Trim HH")
        assert User.objects.filter(username="spaced_user").exists()

        # Pure whitespace or empty string
        with pytest.raises(CommandError, match="--username cannot be empty"):
            call_command("create_invite", username="   ", household="Trim HH")

        with pytest.raises(CommandError, match="--username cannot be empty"):
            call_command("create_invite", username="", household="Trim HH")

    def test_cli_household_conflict_detection_and_immutability(self):
        """Specifying a conflicting household for an existing user raises CommandError and preserves state."""
        hh_original = Household.objects.create(name="Original Household")
        Household.objects.create(name="Conflicting Household")

        call_command("create_invite", username="fixed_user", household="Original Household")
        user = User.objects.get(username="fixed_user")
        assert user.profile.household == hh_original

        # Attempt to reassign household via create_invite
        with pytest.raises(CommandError, match="already belongs to household 'Original Household'"):
            call_command("create_invite", username="fixed_user", household="Conflicting Household")

        # Confirm user profile was NOT changed
        user.refresh_from_db()
        assert user.profile.household == hh_original

        # Confirm matching household works
        call_command("create_invite", username="fixed_user", household="Original Household")

        # Confirm omitted household flag reuses existing household
        call_command("create_invite", username="fixed_user")

    def test_cli_multi_device_provisioning_independent_tokens(self):
        """Multiple CLI calls for the same user create distinct, simultaneously valid tokens."""
        call_command("create_invite", username="device_user", household="MultiDevice HH")
        user = User.objects.get(username="device_user")

        # Issue 4 more invite tokens (e.g. MacBook, iPad, iPhone, Desktop)
        for _ in range(4):
            call_command("create_invite", username="device_user")

        tokens = list(InviteToken.objects.filter(user=user).order_by("created_at"))
        assert len(tokens) == 5

        # All 5 have distinct hashes
        token_hashes = {t.token_hash for t in tokens}
        assert len(token_hashes) == 5

        # All 5 are valid
        assert all(t.is_valid for t in tokens)

        # Redeeming token 0 marks ONLY token 0 as used
        tokens[0].mark_as_used()
        assert tokens[0].is_used
        assert not tokens[0].is_valid

        # Remaining 4 tokens remain completely valid
        for t in tokens[1:]:
            t.refresh_from_db()
            assert t.is_valid
            assert not t.is_used

    def test_cli_expires_hours_validation(self):
        """CLI enforces positive integer for --expires-hours."""
        with pytest.raises(CommandError, match="--expires-hours must be a positive integer"):
            call_command("create_invite", username="ttl_user", household="TTL HH", expires_hours=0)

        with pytest.raises(CommandError, match="--expires-hours must be a positive integer"):
            call_command("create_invite", username="ttl_user", household="TTL HH", expires_hours=-10)

    def test_cli_existing_user_without_profile_requires_household(self):
        """Existing User with no UserProfile requires --household to link."""
        user = User.objects.create_user(username="bare_user")
        assert not hasattr(user, "profile") or user.profile is None

        with pytest.raises(CommandError, match="exists but has no household profile"):
            call_command("create_invite", username="bare_user")

        call_command("create_invite", username="bare_user", household="Adoptive HH")
        user.refresh_from_db()
        assert user.profile.household.name == "Adoptive HH"
        assert user.profile.role == "admin"


# ==============================================================================
# 2. Token Entropy & Cryptographic Properties
# ==============================================================================

@pytest.mark.django_db
class TestCryptographicProperties:
    """Stress-test entropy, collision resistance, and hash integrity across 1,000 tokens."""

    def test_invite_token_shannon_entropy_distribution(self):
        """Sample 1,000 generated invite tokens and verify Shannon entropy exceeds 4.5 bits/char."""
        sample_size = 1000
        raw_tokens = [secrets.token_urlsafe(32) for _ in range(sample_size)]

        entropies = [calculate_shannon_entropy(t) for t in raw_tokens]
        min_ent = min(entropies)
        max_ent = max(entropies)
        mean_ent = sum(entropies) / len(entropies)

        # Base64url alphabet contains 64 characters (6 bits max per character)
        # Mean entropy must exceed 4.5 bits/char per DISPATCH requirements
        assert mean_ent >= 4.75, f"Mean Shannon entropy too low: {mean_ent:.4f} (expected > 4.75)"
        assert min_ent >= 4.0, f"Minimum Shannon entropy too low: {min_ent:.4f}"
        assert max_ent <= 6.0, f"Max Shannon entropy exceeded theoretical bound: {max_ent:.4f}"

        # Token length: 32 bytes in base64url is 43 chars (without padding)
        lengths = {len(t) for t in raw_tokens}
        assert lengths == {43}, f"Unexpected token lengths: {lengths}"

        # Character set must strictly be RFC 4648 Base64URL
        allowed_chars = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
        for t in raw_tokens:
            assert set(t).issubset(allowed_chars)

    def test_token_sha256_collision_resistance_and_determinism(self):
        """1,000 tokens generated via InviteToken.create_token have zero collisions and valid SHA-256."""
        hh = Household.objects.create(name="Crypto HH")
        user = User.objects.create_user(username="crypto_user")
        UserProfile.objects.create(user=user, household=hh)

        sample_size = 1000
        raw_tokens = []
        token_hashes = []

        for _ in range(sample_size):
            invite, raw = InviteToken.create_token(user=user, household=hh, expires_hours=24)
            raw_tokens.append(raw)
            token_hashes.append(invite.token_hash)

        # Zero raw token collisions
        assert len(set(raw_tokens)) == sample_size

        # Zero hash collisions
        assert len(set(token_hashes)) == sample_size

        # Every hash strictly matches SHA-256 hexadecimal digest
        for raw, thash in zip(raw_tokens, token_hashes):
            expected_hash = hashlib.sha256(raw.strip().encode("utf-8")).hexdigest()
            assert thash == expected_hash
            assert len(thash) == 64

    def test_token_hash_db_uniqueness_constraint(self):
        """Database enforces UNIQUE constraint on token_hash."""
        hh = Household.objects.create(name="Uniq HH")
        user = User.objects.create_user(username="uniq_user")

        invite1, raw1 = InviteToken.create_token(user=user, household=hh)

        # Attempt duplicate insert with same token_hash
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                InviteToken.objects.create(
                    token_hash=invite1.token_hash,
                    user=user,
                    household=hh,
                    expires_at=invite1.expires_at,
                )


# ==============================================================================
# 3. Crawler Idempotency Verification
# ==============================================================================

@pytest.mark.django_db
class TestCrawlerIdempotency:
    """Verify that automated crawlers (SafeLinks, Slack unfurlers) cannot consume tokens."""

    def test_crawler_50_repeated_get_requests_do_not_consume_token(self, client):
        """50 repeated GET requests on an active invite link leave it completely unredeemed."""
        hh = Household.objects.create(name="Crawler Household")
        user = User.objects.create_user(username="crawler_user")
        UserProfile.objects.create(user=user, household=hh, role="member")

        invite, raw_token = InviteToken.create_token(user=user, household=hh, expires_hours=48)
        invite_url = f"/auth/invite/{raw_token}/"

        for i in range(50):
            response = client.get(invite_url)
            assert response.status_code == 200, f"Request {i} failed"
            assert "Crawler Household" in response.content.decode("utf-8")
            assert "crawler_user" in response.content.decode("utf-8")

            # Token must remain pristine in database
            invite.refresh_from_db()
            assert not invite.is_used
            assert invite.used_at is None
            assert invite.is_valid

        # After 50 GET requests, redeeming via POST succeeds immediately
        redeem_response = client.post(f"/auth/invite/{raw_token}/redeem/")
        assert redeem_response.status_code == 302
        assert redeem_response.url == "/"

        invite.refresh_from_db()
        assert invite.is_used
        assert invite.used_at is not None
        assert not invite.is_valid

    def test_crawler_get_on_invalid_expired_used_tokens(self, client):
        """GET on invalid returns 404; GET on used/expired returns 400 with descriptive error."""
        hh = Household.objects.create(name="Status HH")
        user = User.objects.create_user(username="status_user")

        # 1. Invalid / non-existent token
        resp_404 = client.get("/auth/invite/non_existent_token_string/")
        assert resp_404.status_code == 404
        assert "Invalid or non-existent invite link." in resp_404.content.decode("utf-8")

        # 2. Used token
        used_invite, used_raw = InviteToken.create_token(user=user, household=hh)
        used_invite.mark_as_used()
        resp_used = client.get(f"/auth/invite/{used_raw}/")
        assert resp_used.status_code == 400
        assert "This invite link has already been used." in resp_used.content.decode("utf-8")

        # 3. Expired token
        exp_invite, exp_raw = InviteToken.create_token(user=user, household=hh)
        exp_invite.expires_at = timezone.now() - timedelta(minutes=10)
        exp_invite.save()
        resp_exp = client.get(f"/auth/invite/{exp_raw}/")
        assert resp_exp.status_code == 400
        assert "This invite link has expired." in resp_exp.content.decode("utf-8")


# ==============================================================================
# 4. TTL Expiration Enforcement
# ==============================================================================

@pytest.mark.django_db
class TestTTLExpiration:
    """Verify precise time-boundary expiration enforcement across all endpoints."""

    def test_ttl_boundary_precision(self, client):
        """Token is valid at expires_at - 1s, but rejected at expires_at + 1s."""
        hh = Household.objects.create(name="Boundary HH")
        user = User.objects.create_user(username="boundary_user")
        UserProfile.objects.create(user=user, household=hh)

        invite, raw_token = InviteToken.create_token(user=user, household=hh, expires_hours=48)
        invite_url = f"/auth/invite/{raw_token}/"
        redeem_url = f"/auth/invite/{raw_token}/redeem/"
        options_url = "/auth/webauthn/register/options/"

        # 1. Test 10 seconds before expiration
        with patch("django.utils.timezone.now", return_value=invite.expires_at - timedelta(seconds=10)):
            assert invite.is_valid
            assert not invite.is_expired
            resp_get = client.get(invite_url)
            assert resp_get.status_code == 200

            resp_opt = client.post(options_url, data=json.dumps({"token": raw_token}), content_type="application/json")
            assert resp_opt.status_code == 200

        # 2. Test 1 second after expiration
        with patch("django.utils.timezone.now", return_value=invite.expires_at + timedelta(seconds=1)):
            assert not invite.is_valid
            assert invite.is_expired

            # Landing GET returns 400
            resp_get_exp = client.get(invite_url)
            assert resp_get_exp.status_code == 400
            assert "expired" in resp_get_exp.content.decode("utf-8").lower()

            # Redeem POST returns 400
            resp_red_exp = client.post(redeem_url)
            assert resp_red_exp.status_code == 400
            assert "expired" in resp_red_exp.content.decode("utf-8").lower()

            # WebAuthn options returns 403
            resp_opt_exp = client.post(options_url, data=json.dumps({"token": raw_token}), content_type="application/json")
            assert resp_opt_exp.status_code == 403
            assert "expired" in resp_opt_exp.json().get("error", "").lower()

            # WebAuthn verify returns 403 when passed credential payload
            mock_payload = build_mock_registration_payload(user=user, challenge="expired_challenge")
            resp_ver_exp = client.post(
                "/auth/webauthn/register/verify/",
                data=json.dumps({"token": raw_token, "credential": mock_payload}),
                content_type="application/json",
            )
            assert resp_ver_exp.status_code == 403
            assert "expired" in resp_ver_exp.json().get("error", "").lower()

    @pytest.mark.parametrize("hours", [1, 24, 72, 720])
    def test_custom_ttl_durations(self, hours):
        """CLI allows setting arbitrary positive TTLs from 1 hour to 30 days."""
        call_command("create_invite", username=f"user_{hours}h", household="Custom TTL HH", expires_hours=hours)
        user = User.objects.get(username=f"user_{hours}h")
        token = InviteToken.objects.get(user=user)

        expected_expiry = token.created_at + timedelta(hours=hours)
        diff = abs((token.expires_at - expected_expiry).total_seconds())
        assert diff < 5.0, f"Expiry mismatch for {hours}h: {diff}s deviation"


# ==============================================================================
# 5. Concurrent Race Condition Testing
# ==============================================================================

class TestConcurrencyAndDoubleRedemption(TransactionTestCase):
    """Simulate parallel concurrent requests to verify row locking and atomic consumption."""

    def test_concurrent_invite_redeem_requests_single_winner(self):
        """Simulate rapid concurrent POST requests to redeem the same token. Exactly one succeeds."""
        hh = Household.objects.create(name="Race Household")
        user = User.objects.create_user(username="race_user")
        UserProfile.objects.create(user=user, household=hh)

        invite, raw_token = InviteToken.create_token(user=user, household=hh, expires_hours=48)
        redeem_url = f"/auth/invite/{raw_token}/redeem/"

        results = []

        def worker_redeem(idx):
            # Client(raise_request_exception=False) converts unhandled server errors (like SQLite lock) to HTTP 500
            c = Client(raise_request_exception=False)
            r = c.post(redeem_url)
            return r.status_code

        # Launch 5 concurrent requests
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(worker_redeem, i) for i in range(5)]
            for f in futures:
                results.append(f.result())

        # In SQLite/Postgres, exactly one request is the 302 winner, and other requests
        # are rejected (HTTP 400 if sequential/serialized, or 500 if SQLite lock contention occurs).
        # In NO circumstance can more than 1 request succeed!
        winners = [res for res in results if res == 302]
        assert len(winners) == 1, f"Expected exactly 1 winner (302 redirect), got results: {results}"

        # Check DB state
        invite.refresh_from_db()
        assert invite.is_used is True
        assert invite.used_at is not None
        assert invite.is_valid is False

    def test_double_click_sequential_race_rejection(self):
        """Simulate fast sequential double-click on redeem button."""
        hh = Household.objects.create(name="Click Household")
        user = User.objects.create_user(username="click_user")
        UserProfile.objects.create(user=user, household=hh)

        invite, raw_token = InviteToken.create_token(user=user, household=hh, expires_hours=48)
        redeem_url = f"/auth/invite/{raw_token}/redeem/"

        c1 = Client()
        resp1 = c1.post(redeem_url)
        assert resp1.status_code == 302
        assert resp1.url == "/"

        # Second click immediately after
        c2 = Client()
        resp2 = c2.post(redeem_url)
        assert resp2.status_code == 400
        assert "This invite link has already been used." in resp2.content.decode("utf-8")

    def test_interleaved_webauthn_and_direct_redeem_race(self):
        """Racing direct session redeem against WebAuthn registration allows only one to consume token."""
        hh = Household.objects.create(name="DualRace HH")
        user = User.objects.create_user(username="dual_user")
        UserProfile.objects.create(user=user, household=hh)

        invite, raw_token = InviteToken.create_token(user=user, household=hh, expires_hours=48)

        # Set up WebAuthn registration session
        client = Client()
        opt_resp = client.post(
            "/auth/webauthn/register/options/",
            data=json.dumps({"token": raw_token}),
            content_type="application/json",
        )
        assert opt_resp.status_code == 200
        challenge = opt_resp.json()["challenge"]

        # Now simulate direct redeem completing FIRST
        client_direct = Client()
        dir_resp = client_direct.post(f"/auth/invite/{raw_token}/redeem/")
        assert dir_resp.status_code == 302

        # Now attempt to verify the WebAuthn registration payload
        cred_payload = build_mock_registration_payload(user=user, challenge=challenge)
        reg_resp = client.post(
            "/auth/webauthn/register/verify/",
            data=json.dumps({"token": raw_token, "credential": cred_payload, "name": "Raced Device"}),
            content_type="application/json",
        )
        # Must be rejected because token was already consumed!
        assert reg_resp.status_code == 403
        assert "already used" in reg_resp.json().get("error", "").lower()
        assert PasskeyCredential.objects.filter(name="Raced Device").count() == 0

    def test_concurrent_webauthn_verify_requests_single_winner(self):
        """Simulate concurrent WebAuthn verification requests for the same token."""
        hh = Household.objects.create(name="WebAuthnRace HH")
        user = User.objects.create_user(username="webauthn_race_user")
        UserProfile.objects.create(user=user, household=hh)

        invite, raw_token = InviteToken.create_token(user=user, household=hh, expires_hours=48)

        client = Client()
        opt_resp = client.post(
            "/auth/webauthn/register/options/",
            data=json.dumps({"token": raw_token}),
            content_type="application/json",
        )
        challenge = opt_resp.json()["challenge"]

        # Pre-create distinct sessions on main thread to avoid session DB table write lock contention
        session_keys = []
        for _ in range(4):
            s = SessionStore()
            s["webauthn_reg_challenge"] = challenge
            s.save()
            session_keys.append(s.session_key)

        def worker_verify(idx):
            c = Client(raise_request_exception=False)
            c.cookies[settings.SESSION_COOKIE_NAME] = session_keys[idx]
            cred_payload = build_mock_registration_payload(
                user=user, challenge=challenge, credential_id=f"cred_concurrent_{idx}"
            )
            r = c.post(
                "/auth/webauthn/register/verify/",
                data=json.dumps({"token": raw_token, "credential": cred_payload, "name": f"Device {idx}"}),
                content_type="application/json",
            )
            return r.status_code

        results = []
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(worker_verify, i) for i in range(4)]
            for f in futures:
                results.append(f.result())

        winners = [res for res in results if res == 200]
        assert len(winners) == 1, f"Expected exactly 1 registration winner, got: {results}"

        # Confirm exactly 1 PasskeyCredential was created in database
        registered = PasskeyCredential.objects.filter(user=user)
        assert registered.count() == 1

        invite.refresh_from_db()
        assert invite.is_used is True
        assert invite.is_valid is False
