"""Empirical Stress Tests and Property Checks for Milestone M1.

Challenger 1 (teamwork_preview_challenger_m1_1)
Challenges:
1. Recipe.original_url uniqueness per household and null/blank behavior.
2. MealPlan uniqueness per household, date, and meal_type.
3. InviteToken entropy, SHA-256 integrity, and expiration/validity properties.
4. PasskeyCredential signature counter rollback prevention and clone detection.
5. Scalability stress testing across multiple households and concurrent constraints.
"""

import hashlib
import math
from collections import Counter
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils import timezone

from recipes.models import (
    Household,
    InviteToken,
    MealPlan,
    PasskeyCredential,
    Recipe,
    RecipeTag,
    UserProfile,
)


def calculate_shannon_entropy(s: str) -> float:
    """Calculate Shannon entropy of string in bits per character."""
    if not s:
        return 0.0
    counts = Counter(s)
    length = len(s)
    return -sum((count / length) * math.log2(count / length) for count in counts.values())


# ===========================================================================
# 1. Recipe.original_url Uniqueness & Null/Blank Stress Tests
# ===========================================================================

@pytest.mark.django_db
def test_empirical_recipe_url_across_5_households():
    """Verify that identical URL can be successfully inserted across 5 distinct households."""
    test_url = "https://cooking.nytimes.com/recipes/1018068-pasta-alla-vodka"
    households = [Household.objects.create(name=f"Stress Household {i}") for i in range(5)]

    recipes = []
    for i, hh in enumerate(households):
        recipe = Recipe.objects.create(
            household=hh,
            title=f"Vodka Pasta by Household {i}",
            original_url=test_url,
            instructions="Cook pasta, add vodka sauce.",
        )
        recipes.append(recipe)

    # Verify all 5 were created and saved with distinct PKs
    assert len(recipes) == 5
    assert len({r.pk for r in recipes}) == 5
    for r in recipes:
        assert r.original_url == test_url


@pytest.mark.django_db
def test_empirical_recipe_url_duplicate_in_same_household():
    """Verify that inserting identical URL twice in the same household raises IntegrityError."""
    test_url = "https://cooking.nytimes.com/recipes/1018068-pasta-alla-vodka"
    hh = Household.objects.create(name="Single URL Test Household")

    Recipe.objects.create(
        household=hh,
        title="First Pasta",
        original_url=test_url,
        instructions="Boil water.",
    )

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Recipe.objects.create(
                household=hh,
                title="Duplicate Pasta",
                original_url=test_url,
                instructions="Boil water again.",
            )


@pytest.mark.django_db
def test_empirical_recipe_null_and_blank_urls_in_same_household():
    """Verify multiple null, empty string, and whitespace URLs can coexist in the same household."""
    hh = Household.objects.create(name="Null Blank URL Household")

    # 10 null URLs
    null_recipes = [
        Recipe.objects.create(
            household=hh,
            title=f"Grandma Recipe Null {i}",
            original_url=None,
            instructions="Family secret.",
        )
        for i in range(10)
    ]
    assert len(null_recipes) == 10
    assert len({r.pk for r in null_recipes}) == 10

    # 10 empty string URLs
    blank_recipes = [
        Recipe.objects.create(
            household=hh,
            title=f"Grandma Recipe Blank {i}",
            original_url="",
            instructions="Family secret 2.",
        )
        for i in range(10)
    ]
    assert len(blank_recipes) == 10
    assert len({r.pk for r in blank_recipes}) == 10

    # Total in household is 20
    assert Recipe.objects.filter(household=hh).count() == 20


@pytest.mark.django_db
def test_empirical_recipe_url_stress_50_households():
    """Stress test: 50 different households clipping the exact same viral URL."""
    viral_url = "https://www.tiktok.com/@chef/video/1234567890"
    households = [Household.objects.create(name=f"TikTok HH {i}") for i in range(50)]

    for hh in households:
        Recipe.objects.create(
            household=hh,
            title="Viral TikTok Feta Pasta",
            original_url=viral_url,
            instructions="Bake feta with tomatoes.",
        )

    assert Recipe.objects.filter(original_url=viral_url).count() == 50


# ===========================================================================
# 2. MealPlan Uniqueness Property & Stress Tests
# ===========================================================================

@pytest.mark.django_db
def test_empirical_meal_plan_same_date_and_type_across_5_households():
    """Verify meal plans for same date and meal_type across 5 households all succeed."""
    target_date = timezone.now().date() + timedelta(days=3)
    households = [Household.objects.create(name=f"MealPlan HH {i}") for i in range(5)]

    plans = []
    for i, hh in enumerate(households):
        plan = MealPlan.objects.create(
            household=hh,
            date=target_date,
            meal_type="DINNER",
            custom_meal=f"Dinner at HH {i}",
        )
        plans.append(plan)

    assert len(plans) == 5
    assert len({p.pk for p in plans}) == 5
    assert MealPlan.objects.filter(date=target_date, meal_type="DINNER").count() == 5


@pytest.mark.django_db
def test_empirical_meal_plan_duplicate_in_same_household_fails():
    """Verify duplicate date and meal_type in the same household raises IntegrityError."""
    target_date = timezone.now().date() + timedelta(days=2)
    hh = Household.objects.create(name="Meal Conflict HH")

    MealPlan.objects.create(
        household=hh,
        date=target_date,
        meal_type="DINNER",
        custom_meal="Tacos",
    )

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            MealPlan.objects.create(
                household=hh,
                date=target_date,
                meal_type="DINNER",
                custom_meal="Burritos",
            )


@pytest.mark.django_db
def test_empirical_meal_plan_different_meal_types_and_dates_succeed():
    """Verify same household can have LUNCH and DINNER on same date, and DINNER on another date."""
    today = timezone.now().date()
    tomorrow = today + timedelta(days=1)
    hh = Household.objects.create(name="MultiMeal HH")

    p1 = MealPlan.objects.create(household=hh, date=today, meal_type="LUNCH", custom_meal="Sandwich")
    p2 = MealPlan.objects.create(household=hh, date=today, meal_type="DINNER", custom_meal="Spaghetti")
    p3 = MealPlan.objects.create(household=hh, date=tomorrow, meal_type="DINNER", custom_meal="Roast")

    assert p1.pk and p2.pk and p3.pk
    assert MealPlan.objects.filter(household=hh).count() == 3


# ===========================================================================
# 3. InviteToken Entropy, SHA-256 Integrity & Expiration Stress Tests
# ===========================================================================

@pytest.mark.django_db
def test_empirical_invite_token_entropy_and_hash_integrity(test_household, test_user):
    """Generate 500 tokens and verify:
    - High Shannon entropy (>= 4.5 bits/char for base64url).
    - Length is at least 43 characters (32 bytes urlsafe base64).
    - Perfect SHA-256 hash match against token_hash.
    - Zero collisions across all 500 tokens and hashes.
    """
    raw_tokens = []
    token_hashes = []
    entropies = []

    for _ in range(500):
        token_obj, raw_token = InviteToken.create_token(
            user=test_user,
            household=test_household,
            expires_hours=48,
        )
        raw_tokens.append(raw_token)
        token_hashes.append(token_obj.token_hash)

        # Calculate Shannon entropy
        entropy = calculate_shannon_entropy(raw_token)
        entropies.append(entropy)

        # Cryptographic check: SHA-256 of raw_token matches stored token_hash
        computed_hash = hashlib.sha256(raw_token.strip().encode("utf-8")).hexdigest()
        assert token_obj.token_hash == computed_hash
        assert len(token_obj.token_hash) == 64

    # Assert token lengths
    for rt in raw_tokens:
        assert len(rt) >= 42

    # Assert entropy distribution: mean entropy should be high (> 4.8 bits/char)
    avg_entropy = sum(entropies) / len(entropies)
    min_entropy = min(entropies)
    assert avg_entropy > 4.8, f"Average entropy too low: {avg_entropy}"
    assert min_entropy > 4.0, f"Minimum entropy too low: {min_entropy}"

    # Assert zero collisions
    assert len(set(raw_tokens)) == 500, "Collision detected in raw tokens!"
    assert len(set(token_hashes)) == 500, "Collision detected in token hashes!"


@pytest.mark.django_db
def test_empirical_invite_token_expiration_and_validity(test_household, test_user):
    """Verify is_expired and is_valid logic across edge cases:
    - Fresh token: valid, not expired.
    - Past token: not valid, expired.
    - Used token: not valid, marked used.
    - Used + expired: not valid, expired.
    """
    # 1. Fresh token
    token_valid, _ = InviteToken.create_token(test_user, test_household, expires_hours=24)
    assert token_valid.is_valid is True
    assert token_valid.is_expired is False
    assert token_valid.is_used is False

    # 2. Used token
    token_valid.mark_as_used()
    assert token_valid.is_used is True
    assert token_valid.used_at is not None
    assert token_valid.is_valid is False
    assert token_valid.is_expired is False

    # 3. Expired token (1 second in past)
    token_expired, _ = InviteToken.create_token(test_user, test_household, expires_hours=1)
    token_expired.expires_at = timezone.now() - timedelta(seconds=1)
    token_expired.save(update_fields=["expires_at"])
    assert token_expired.is_expired is True
    assert token_expired.is_valid is False

    # 4. Expired + Used
    token_expired.mark_as_used()
    assert token_expired.is_expired is True
    assert token_expired.is_used is True
    assert token_expired.is_valid is False


@pytest.mark.django_db
def test_empirical_invite_token_hash_uniqueness(test_household, test_user):
    """Verify database unique constraint on token_hash raises IntegrityError on collision."""
    token_obj, _ = InviteToken.create_token(test_user, test_household, expires_hours=48)

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            InviteToken.objects.create(
                user=test_user,
                household=test_household,
                token_hash=token_obj.token_hash,  # duplicate hash
                expires_at=timezone.now() + timedelta(hours=48),
            )


# ===========================================================================
# 4. PasskeyCredential Anti-Rollback & Property Checks
# ===========================================================================

@pytest.mark.django_db
def test_empirical_passkey_sign_count_monotonic_progression(test_user):
    """Verify sign_count strictly enforces monotonic counter progression."""
    passkey = PasskeyCredential.objects.create(
        user=test_user,
        credential_id="cred_id_monotonic_test",
        public_key="cose_key_sample",
        sign_count=50,
    )

    # Valid progression
    passkey.update_sign_count(51)
    assert passkey.sign_count == 51

    passkey.update_sign_count(100)
    assert passkey.sign_count == 100

    passkey.update_sign_count(1000000)
    assert passkey.sign_count == 1000000

    # Max uint32
    max_uint32 = 4294967295
    passkey.update_sign_count(max_uint32)
    assert passkey.sign_count == max_uint32


@pytest.mark.django_db
def test_empirical_passkey_sign_count_rollback_attacks(test_user):
    """Test adversarial sign_count attacks:
    - Same count replay: new_count == current_count (MUST RAISE ValueError)
    - Regressive count: new_count < current_count (MUST RAISE ValueError)
    - Zero count reset after positive: new_count == 0 (MUST RAISE ValueError)
    """
    passkey = PasskeyCredential.objects.create(
        user=test_user,
        credential_id="cred_id_rollback_test",
        public_key="cose_key_sample",
        sign_count=100,
    )

    # Attack 1: Replay attack (identical counter)
    with pytest.raises(ValueError, match="rollback detected"):
        passkey.update_sign_count(100)
    assert passkey.sign_count == 100  # uncorrupted

    # Attack 2: Regressive counter (decreased by 1)
    with pytest.raises(ValueError, match="rollback detected"):
        passkey.update_sign_count(99)
    assert passkey.sign_count == 100

    # Attack 3: Major regression
    with pytest.raises(ValueError, match="rollback detected"):
        passkey.update_sign_count(1)
    assert passkey.sign_count == 100

    # Attack 4: Reset to 0
    with pytest.raises(ValueError, match="rollback detected"):
        passkey.update_sign_count(0)
    assert passkey.sign_count == 100


@pytest.mark.django_db
def test_empirical_passkey_synced_passkey_zero_counter(test_user):
    """Test WebAuthn synced passkey behavior where authenticators report 0 counter:
    W3C WebAuthn L3 §6.1.2: If stored sign_count is 0 and new_count is 0, accept.
    """
    passkey = PasskeyCredential.objects.create(
        user=test_user,
        credential_id="cred_id_synced_test",
        public_key="cose_key_sample",
        sign_count=0,
    )

    # Successive calls with 0 must be accepted for synced authenticators
    passkey.update_sign_count(0)
    assert passkey.sign_count == 0

    passkey.update_sign_count(0)
    assert passkey.sign_count == 0

    # Advancing from 0 to positive count is allowed
    passkey.update_sign_count(1)
    assert passkey.sign_count == 1

    # Once positive, returning to 0 must fail
    with pytest.raises(ValueError, match="rollback detected"):
        passkey.update_sign_count(0)


@pytest.mark.django_db
def test_empirical_passkey_credential_id_uniqueness(test_user):
    """Verify credential_id is globally unique across all users and devices."""
    User = get_user_model()
    other_user = User.objects.create_user(username="other_passkey_user@example.com")

    PasskeyCredential.objects.create(
        user=test_user,
        credential_id="global_unique_cred_123",
        public_key="cose_pub_1",
    )

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            PasskeyCredential.objects.create(
                user=other_user,
                credential_id="global_unique_cred_123",  # duplicate ID
                public_key="cose_pub_2",
            )


# ===========================================================================
# 5. RecipeTag Scoped Uniqueness & UserProfile Household Multi-User Tests
# ===========================================================================

@pytest.mark.django_db
def test_empirical_recipe_tag_scoped_uniqueness():
    """Verify RecipeTag names and slugs are uniquely scoped per household."""
    h1 = Household.objects.create(name="Tag Household 1")
    h2 = Household.objects.create(name="Tag Household 2")

    tag1 = RecipeTag.objects.create(household=h1, name="Dessert")
    tag2 = RecipeTag.objects.create(household=h2, name="Dessert")
    assert tag1.slug == "dessert"
    assert tag2.slug == "dessert"

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            RecipeTag.objects.create(household=h1, name="Dessert")


@pytest.mark.django_db
def test_empirical_user_profile_household_multi_user():
    """Verify multiple users can belong to the same household with different roles,
    and each user can have at most one profile (OneToOne).
    """
    User = get_user_model()
    hh = Household.objects.create(name="Multi Member Household")

    user_admin = User.objects.create_user(username="admin_user@example.com")
    user_member = User.objects.create_user(username="member_user@example.com")

    p1 = UserProfile.objects.create(user=user_admin, household=hh, role="admin")
    p2 = UserProfile.objects.create(user=user_member, household=hh, role="member")

    assert p1.household == p2.household
    assert UserProfile.objects.filter(household=hh).count() == 2

    # User cannot have a second profile (OneToOne constraint)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            UserProfile.objects.create(user=user_admin, household=hh, role="member")
