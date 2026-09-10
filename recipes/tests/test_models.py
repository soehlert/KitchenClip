from datetime import time, timedelta

import pytest
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


@pytest.mark.django_db
def test_recipe_creation():
    recipe = Recipe.objects.create(
        title="Spaghetti Bolognese",
        original_url="http://spaghetti.local",
        prep_time=15,
        cook_time=45
    )
    assert recipe.title == "Spaghetti Bolognese"
    assert recipe.total_time_display == "01:00"

@pytest.mark.django_db
def test_total_time_display_with_explicit_total():
    recipe = Recipe.objects.create(
        title="Quick Snack",
        original_url="http://snack.local",
        total_time=10
    )
    assert recipe.total_time_display == "00:10"

@pytest.mark.django_db
def test_meal_plan_creation():
    recipe = Recipe.objects.create(title="Dinner Roast", original_url="http://roast.local")
    plan = MealPlan.objects.create(
        date=timezone.now().date(),
        meal_type="DINNER",
        recipe=recipe,
        ready_at=time(18, 30)
    )
    assert plan.recipe.title == "Dinner Roast"
    assert plan.notification_sent is False

@pytest.mark.django_db
def test_tag_auto_color():
    tag = RecipeTag.objects.create(name="Vegetarian")
    assert tag.color is not None
    assert tag.color.startswith("#")
    assert tag.slug == "vegetarian"


# ---------------------------------------------------------------------------
# Multi-Household & Auth Model Tests
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_household_and_user_profile(test_household, test_user):
    """Verify Household and UserProfile model behavior and string representation."""
    assert isinstance(test_household, Household)
    assert test_household.name == "Test Primary Household"
    assert str(test_household) == "Test Primary Household"

    profile = test_user.profile
    assert isinstance(profile, UserProfile)
    assert profile.household == test_household
    assert profile.role == "admin"
    assert str(profile) == f"{test_user.username} ({test_household.name})"

    # Update role to member
    profile.role = "member"
    profile.save(update_fields=["role"])
    profile.refresh_from_db()
    assert profile.role == "member"


@pytest.mark.django_db
def test_invite_token_lifecycle(test_household, test_user):
    """Verify InviteToken generation, SHA-256 hashing, expiration, and redemption."""
    token_obj, raw_token = InviteToken.create_token(
        user=test_user,
        household=test_household,
        expires_hours=48,
    )
    assert len(raw_token) >= 40
    assert token_obj.token_hash == InviteToken.hash_token(raw_token)
    assert token_obj.is_valid is True
    assert token_obj.is_expired is False
    assert "active" in str(token_obj)

    # Redemption
    token_obj.mark_as_used()
    assert token_obj.is_used is True
    assert token_obj.used_at is not None
    assert token_obj.is_valid is False
    assert "used" in str(token_obj)

    # Expired token test
    past_token_obj, _ = InviteToken.create_token(
        user=test_user,
        household=test_household,
        expires_hours=1,
    )
    past_token_obj.expires_at = timezone.now() - timedelta(hours=1)
    past_token_obj.save(update_fields=["expires_at"])
    assert past_token_obj.is_expired is True
    assert past_token_obj.is_valid is False
    assert "expired" in str(past_token_obj)


@pytest.mark.django_db
def test_passkey_credential_model(test_user):
    """Verify PasskeyCredential creation, W3C WebAuthn Level 3 anti-rollback, and synced passkey support."""
    passkey = PasskeyCredential.objects.create(
        user=test_user,
        credential_id="test_credential_id_base64url_12345",
        public_key="test_cose_public_key_bytes",
        name="MacBook Pro TouchID",
        sign_count=10,
        aaguid="00000000-0000-0000-0000-000000000000",
    )
    assert passkey.user == test_user
    assert passkey.display_name == "MacBook Pro TouchID"
    assert "MacBook Pro TouchID" in str(passkey)
    assert len(passkey.credential_id_preview) <= 20

    # Valid counter increment
    passkey.update_sign_count(11)
    assert passkey.sign_count == 11
    assert passkey.last_used_at is not None

    # Rollback detection must raise ValueError per W3C WebAuthn L3 §6.1.2
    with pytest.raises(ValueError, match="rollback detected"):
        passkey.update_sign_count(11)

    with pytest.raises(ValueError, match="rollback detected"):
        passkey.update_sign_count(5)

    # Synced passkey with sign_count=0 remains 0 without error
    synced_passkey = PasskeyCredential.objects.create(
        user=test_user,
        credential_id="synced_credential_id_456",
        public_key="cose_key",
        sign_count=0,
    )
    synced_passkey.update_sign_count(0)
    assert synced_passkey.sign_count == 0


@pytest.mark.django_db
def test_scoped_recipe_url_uniqueness(test_household, secondary_household):
    """Verify Recipe.original_url uniqueness is scoped to Household."""
    shared_url = "https://example.com/unique-pasta"

    # Household 1 can create recipe with URL
    r1 = Recipe.objects.create(
        household=test_household,
        title="Household 1 Pasta",
        original_url=shared_url,
    )
    assert r1.pk is not None

    # Household 2 can independently save the EXACT same URL
    r2 = Recipe.objects.create(
        household=secondary_household,
        title="Household 2 Pasta",
        original_url=shared_url,
    )
    assert r2.pk is not None

    # Household 1 cannot create a duplicate with the same URL
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Recipe.objects.create(
                household=test_household,
                title="Household 1 Duplicate Pasta",
                original_url=shared_url,
            )

    # Multiple manual recipes with empty or null URL in the same household are permitted
    m1 = Recipe.objects.create(household=test_household, title="Manual 1", original_url="")
    m2 = Recipe.objects.create(household=test_household, title="Manual 2", original_url="")
    m3 = Recipe.objects.create(household=test_household, title="Manual 3", original_url=None)
    assert m1.pk and m2.pk and m3.pk


@pytest.mark.django_db
def test_scoped_meal_plan_uniqueness(test_household, secondary_household):
    """Verify MealPlan (date, meal_type) uniqueness is scoped to Household."""
    today = timezone.now().date()

    # Household 1 meal plan
    p1 = MealPlan.objects.create(
        household=test_household,
        date=today,
        meal_type="DINNER",
        custom_meal="Tacos",
    )
    assert p1.pk is not None

    # Household 2 can plan dinner on the same day
    p2 = MealPlan.objects.create(
        household=secondary_household,
        date=today,
        meal_type="DINNER",
        custom_meal="Burgers",
    )
    assert p2.pk is not None

    # Household 1 cannot have a duplicate dinner on the same day
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            MealPlan.objects.create(
                household=test_household,
                date=today,
                meal_type="DINNER",
                custom_meal="Steak",
            )


@pytest.mark.django_db
def test_scoped_recipe_tag_uniqueness(test_household, secondary_household):
    """Verify RecipeTag (household, name) and (household, slug) uniqueness."""
    t1 = RecipeTag.objects.create(
        household=test_household,
        name="Quick",
    )
    assert t1.slug == "quick"

    # Secondary household can have a tag with the same name and slug
    t2 = RecipeTag.objects.create(
        household=secondary_household,
        name="Quick",
    )
    assert t2.slug == "quick"

    # Same household cannot have duplicate tag name
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            RecipeTag.objects.create(
                household=test_household,
                name="Quick",
            )


@pytest.mark.django_db
def test_models_require_household_constraint(disable_auto_household):
    """Verify NOT NULL constraint on Recipe and MealPlan when auto-assignment is disabled."""
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Recipe.objects.create(title="Orphan Recipe")

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            MealPlan.objects.create(
                date=timezone.now().date(),
                meal_type="LUNCH",
                custom_meal="Orphan Meal",
            )
