"""recipes/tests/conftest.py - Test fixtures and backward-compatibility harness for KitchenClip multi-tenancy."""

import hashlib
import secrets
import sys
from contextlib import contextmanager
from datetime import timedelta
from unittest.mock import MagicMock

import pytest
from django.contrib.auth import get_user_model
from django.db.models.signals import pre_save
from django.utils import timezone

# ---------------------------------------------------------------------------
# Safeguard: Ensure missing optional dependencies (e.g. python-dotenv) do not
# prevent pytest collection or settings loading.
# ---------------------------------------------------------------------------
if "dotenv" not in sys.modules:
    try:
        import dotenv  # noqa: F401
    except ImportError:
        dummy_dotenv = MagicMock()
        dummy_dotenv.load_dotenv = lambda *args, **kwargs: None
        sys.modules["dotenv"] = dummy_dotenv


# ---------------------------------------------------------------------------
# Global Test Scoping Context
# Holds active test household and user for auto-assignment in un-scoped models.
# ---------------------------------------------------------------------------
class TestHouseholdContext:
    household = None
    user = None
    enabled = True


def get_current_test_household():
    """Retrieve the currently active test household instance, if set."""
    return TestHouseholdContext.household if TestHouseholdContext.enabled else None


def get_current_test_user():
    """Retrieve the currently active test user instance, if set."""
    return TestHouseholdContext.user if TestHouseholdContext.enabled else None


@contextmanager
def no_auto_household():
    """Context manager to temporarily disable auto-assigning default household.
    
    Useful when testing validation or NOT NULL integrity constraint violations.
    """
    prev = TestHouseholdContext.enabled
    TestHouseholdContext.enabled = False
    try:
        yield
    finally:
        TestHouseholdContext.enabled = prev


@pytest.fixture
def disable_auto_household():
    """Pytest fixture to disable auto-assigning default household during a test."""
    prev = TestHouseholdContext.enabled
    TestHouseholdContext.enabled = False
    yield
    TestHouseholdContext.enabled = prev


# ---------------------------------------------------------------------------
# Pre-save Signal Handler for Backward Compatibility
# Automatically assigns household to Recipe and MealPlan if not explicitly set.
# ---------------------------------------------------------------------------
def _auto_assign_test_household(sender, instance, **kwargs):
    """Signal receiver attached to models requiring household foreign key.
    
    If instance.household_id is not already set, assigns active test household.
    Also populates instance._state.fields_cache to prevent any synchronous
    foreign-key database queries in async tests (such as test_services.py).
    """
    if not TestHouseholdContext.enabled or TestHouseholdContext.household is None:
        return

    # Assign household if missing
    if getattr(instance, "household_id", None) is None and hasattr(instance, "household_id"):
        instance.household_id = TestHouseholdContext.household.id
        instance._state.fields_cache["household"] = TestHouseholdContext.household

    # Assign created_by if missing and user is available
    if TestHouseholdContext.user is not None and getattr(instance, "created_by_id", None) is None and hasattr(instance, "created_by_id"):
        instance.created_by_id = TestHouseholdContext.user.id
        instance._state.fields_cache["created_by"] = TestHouseholdContext.user


# Connect signal receivers once at conftest import time
def _register_signals():
    try:
        from recipes.models import MealPlan, Recipe, RecipeTag
        pre_save.connect(_auto_assign_test_household, sender=Recipe, dispatch_uid="test_auto_assign_recipe_household")
        pre_save.connect(_auto_assign_test_household, sender=MealPlan, dispatch_uid="test_auto_assign_mealplan_household")
        pre_save.connect(_auto_assign_test_household, sender=RecipeTag, dispatch_uid="test_auto_assign_recipetag_household")
    except ImportError:
        pass

_register_signals()


# ---------------------------------------------------------------------------
# Pytest Autouse Fixture: Lifecycle Context Management
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def auto_test_household_context(request):
    """Autouse fixture that manages the active household context per test.
    
    Only initializes database records for tests requesting db access (marked with
    django_db or requesting db/client fixtures), ensuring pure unit tests
    (like test_ingredient_processor.py) remain fast and isolated.
    """
    is_db_test = (
        "django_db" in request.keywords
        or "db" in request.fixturenames
        or "client" in request.fixturenames
        or "transactional_db" in request.fixturenames
    )
    if not is_db_test:
        yield
        return

    # Ensure database access is active for this test
    request.getfixturevalue("db")

    from recipes.models import Household, UserProfile
    User = get_user_model()

    if "asyncio" in request.keywords:
        # Avoid thread 1 DB query in async tests to prevent SQLite multi-thread locking
        prev_h = TestHouseholdContext.household
        prev_u = TestHouseholdContext.user
        TestHouseholdContext.household = Household(id=1, name="Test Primary Household")
        TestHouseholdContext.user = User(id=1, username="admin")
        yield TestHouseholdContext.household
        TestHouseholdContext.household = prev_h
        TestHouseholdContext.user = prev_u
        return

    household, _ = Household.objects.get_or_create(name="Test Primary Household")
    user, _ = User.objects.get_or_create(
        username="test_primary_user@example.com",
        defaults={"email": "test_primary_user@example.com", "first_name": "Test", "last_name": "User"}
    )
    profile, _ = UserProfile.objects.get_or_create(
        user=user,
        defaults={"household": household, "role": "admin"}
    )
    # Ensure profile household is linked correctly
    if profile.household_id != household.id:
        profile.household = household
        profile.save(update_fields=["household"])

    prev_household = TestHouseholdContext.household
    prev_user = TestHouseholdContext.user
    TestHouseholdContext.household = household
    TestHouseholdContext.user = user

    from django.db import connection
    connection.close()

    yield household

    TestHouseholdContext.household = prev_household
    TestHouseholdContext.user = prev_user


# ---------------------------------------------------------------------------
# Core Domain Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def test_household(db):
    """Fixture returning the primary test household."""
    from recipes.models import Household
    household, _ = Household.objects.get_or_create(name="Test Primary Household")
    return household


@pytest.fixture
def test_user(db, test_household):
    """Fixture returning primary test user linked to test_household."""
    from recipes.models import UserProfile
    User = get_user_model()
    user, _ = User.objects.get_or_create(
        username="test_primary_user@example.com",
        defaults={"email": "test_primary_user@example.com"}
    )
    profile, _ = UserProfile.objects.get_or_create(
        user=user,
        defaults={"household": test_household, "role": "admin"}
    )
    if profile.household_id != test_household.id:
        profile.household = test_household
        profile.save(update_fields=["household"])
    return user


@pytest.fixture
def secondary_household(db):
    """Fixture providing a distinct second household for multi-tenancy isolation tests."""
    from recipes.models import Household
    household, _ = Household.objects.get_or_create(name="Test Secondary Household")
    return household


@pytest.fixture
def secondary_user(db, secondary_household):
    """Fixture providing an admin user belonging to secondary_household."""
    from recipes.models import UserProfile
    User = get_user_model()
    user, _ = User.objects.get_or_create(
        username="test_secondary_user@example.com",
        defaults={"email": "test_secondary_user@example.com"}
    )
    profile, _ = UserProfile.objects.get_or_create(
        user=user,
        defaults={"household": secondary_household, "role": "admin"}
    )
    if profile.household_id != secondary_household.id:
        profile.household = secondary_household
        profile.save(update_fields=["household"])
    return user


@pytest.fixture
def household_member_user(db, test_household):
    """Fixture providing a non-admin member in the same primary household (e.g. spouse)."""
    from recipes.models import UserProfile
    User = get_user_model()
    user, _ = User.objects.get_or_create(
        username="test_spouse_user@example.com",
        defaults={"email": "test_spouse_user@example.com"}
    )
    profile, _ = UserProfile.objects.get_or_create(
        user=user,
        defaults={"household": test_household, "role": "member"}
    )
    if profile.household_id != test_household.id:
        profile.household = test_household
        profile.save(update_fields=["household"])
    return user


# ---------------------------------------------------------------------------
# Test Client Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def client(db, test_user, test_household):
    """Override pytest-django client to be authenticated as primary household user.
    
    Guarantees 100% backward compatibility for existing view tests.
    """
    from django.test.client import Client
    c = Client()
    c.force_login(test_user)
    c.user = test_user
    c.household = test_household
    return c


@pytest.fixture
def unauthenticated_client():
    """Unauthenticated client for testing login redirects and auth gates."""
    from django.test.client import Client
    return Client()


@pytest.fixture
def secondary_client(db, secondary_user, secondary_household):
    """Authenticated client for a user belonging to secondary_household."""
    from django.test.client import Client
    c = Client()
    c.force_login(secondary_user)
    c.user = secondary_user
    c.household = secondary_household
    return c


@pytest.fixture
def auth_client_factory(db):
    """Factory fixture generating authenticated clients for arbitrary users/households."""
    def _make_client(user=None, household=None, role="admin"):
        from django.test.client import Client
        from recipes.models import Household, UserProfile
        User = get_user_model()

        if household is None:
            household = Household.objects.create(name=f"Household_{secrets.token_hex(4)}")
        if user is None:
            user = User.objects.create_user(
                username=f"user_{secrets.token_hex(4)}@example.com",
                email=f"user_{secrets.token_hex(4)}@example.com"
            )
        profile, _ = UserProfile.objects.get_or_create(
            user=user,
            defaults={"household": household, "role": role}
        )
        if profile.household_id != household.id:
            profile.household = household
            profile.save(update_fields=["household"])

        c = Client()
        c.force_login(user)
        c.user = user
        c.household = household
        return c
    return _make_client


# ---------------------------------------------------------------------------
# Domain Factories for Tests
# ---------------------------------------------------------------------------
@pytest.fixture
def recipe_factory(db, test_household, test_user):
    """Factory creating Recipe instances with sensible defaults and household scoping."""
    def _create_recipe(household=None, created_by=None, **kwargs):
        from recipes.models import Recipe
        defaults = {
            "title": f"Test Recipe {secrets.token_hex(3)}",
            "instructions": "1. Prep ingredients.\n2. Cook and enjoy.",
            "household": household or test_household,
            "created_by": created_by or test_user,
        }
        defaults.update(kwargs)
        return Recipe.objects.create(**defaults)
    return _create_recipe


@pytest.fixture
def meal_plan_factory(db, test_household, test_user):
    """Factory creating MealPlan instances."""
    def _create_plan(household=None, created_by=None, **kwargs):
        from recipes.models import MealPlan
        defaults = {
            "date": timezone.now().date(),
            "meal_type": "DINNER",
            "household": household or test_household,
            "created_by": created_by or test_user,
        }
        defaults.update(kwargs)
        return MealPlan.objects.create(**defaults)
    return _create_plan


@pytest.fixture
def invite_token_factory(db, test_household, test_user):
    """Factory creating InviteToken instances with attached raw_token attribute."""
    def _create_token(user=None, household=None, **kwargs):
        from recipes.models import InviteToken
        raw_token = kwargs.pop("raw_token", secrets.token_urlsafe(32))
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        defaults = {
            "user": user or test_user,
            "household": household or test_household,
            "token_hash": token_hash,
            "expires_at": timezone.now() + timedelta(hours=48),
            "is_used": False,
        }
        defaults.update(kwargs)
        token_obj = InviteToken.objects.create(**defaults)
        token_obj.raw_token = raw_token
        return token_obj
    return _create_token


@pytest.fixture
def passkey_factory(db, test_user):
    """Factory creating PasskeyCredential instances."""
    def _create_passkey(user=None, **kwargs):
        from recipes.models import PasskeyCredential
        defaults = {
            "user": user or test_user,
            "credential_id": secrets.token_urlsafe(32),
            "public_key": "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA0TestKey",
            "sign_count": 0,
            "name": "Test Platform Authenticator",
        }
        defaults.update(kwargs)
        return PasskeyCredential.objects.create(**defaults)
    return _create_passkey
