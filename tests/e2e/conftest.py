"""tests/e2e/conftest.py - E2E test fixtures, session injection, and backward compatibility."""

import os
from importlib import import_module
import pytest

os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
from django.conf import settings
from django.contrib.auth import BACKEND_SESSION_KEY, HASH_SESSION_KEY, SESSION_KEY, get_user_model
from django.core.management import call_command
from django.db.models.signals import pre_save
from playwright.sync_api import Page

from recipes.models import Household, MealPlan, Recipe, RecipeTag, UserProfile

User = get_user_model()


class E2EContext:
    household = None
    user = None
    enabled = True


def _auto_assign_e2e(sender, instance, **kwargs):
    if not E2EContext.enabled or E2EContext.household is None:
        return
    if getattr(instance, "household_id", None) is None and hasattr(instance, "household_id"):
        instance.household_id = E2EContext.household.id
        instance._state.fields_cache["household"] = E2EContext.household
    if (
        E2EContext.user is not None
        and getattr(instance, "created_by_id", None) is None
        and hasattr(instance, "created_by_id")
    ):
        instance.created_by_id = E2EContext.user.id
        instance._state.fields_cache["created_by"] = E2EContext.user


pre_save.connect(_auto_assign_e2e, sender=Recipe, dispatch_uid="e2e_auto_recipe")
pre_save.connect(_auto_assign_e2e, sender=MealPlan, dispatch_uid="e2e_auto_mealplan")
pre_save.connect(_auto_assign_e2e, sender=RecipeTag, dispatch_uid="e2e_auto_recipetag")


@pytest.fixture
def e2e_household(db):
    household, _ = Household.objects.get_or_create(name="E2E Primary Household")
    return household


@pytest.fixture
def e2e_user(db, e2e_household):
    user, _ = User.objects.get_or_create(
        username="e2e_primary@example.com",
        defaults={"email": "e2e_primary@example.com"},
    )
    profile, _ = UserProfile.objects.get_or_create(
        user=user,
        defaults={"household": e2e_household, "role": "admin"},
    )
    if profile.household_id != e2e_household.id:
        profile.household = e2e_household
        profile.save(update_fields=["household"])
    return user


@pytest.fixture
def e2e_secondary_household(db):
    household, _ = Household.objects.get_or_create(name="E2E Secondary Household")
    return household


@pytest.fixture
def e2e_secondary_user(db, e2e_secondary_household):
    user, _ = User.objects.get_or_create(
        username="e2e_secondary@example.com",
        defaults={"email": "e2e_secondary@example.com"},
    )
    profile, _ = UserProfile.objects.get_or_create(
        user=user,
        defaults={"household": e2e_secondary_household, "role": "admin"},
    )
    if profile.household_id != e2e_secondary_household.id:
        profile.household = e2e_secondary_household
        profile.save(update_fields=["household"])
    return user


@pytest.fixture
def e2e_household_spouse(db, e2e_household):
    user, _ = User.objects.get_or_create(
        username="e2e_spouse@example.com",
        defaults={"email": "e2e_spouse@example.com"},
    )
    profile, _ = UserProfile.objects.get_or_create(
        user=user,
        defaults={"household": e2e_household, "role": "member"},
    )
    if profile.household_id != e2e_household.id:
        profile.household = e2e_household
        profile.save(update_fields=["household"])
    return user


def inject_session_cookie(context, live_server_url: str, user):
    """Programmatically generate a Django session and inject sessionid cookie into browser context."""
    SessionStore = import_module(settings.SESSION_ENGINE).SessionStore
    session = SessionStore()
    session[SESSION_KEY] = str(user.pk)
    session[BACKEND_SESSION_KEY] = settings.AUTHENTICATION_BACKENDS[0]
    session[HASH_SESSION_KEY] = user.get_session_auth_hash()
    session.save()

    context.add_cookies([
        {
            "name": settings.SESSION_COOKIE_NAME,
            "value": session.session_key,
            "url": live_server_url,
        }
    ])
    return session


@pytest.fixture
def session_injector():
    """Fixture exposing the inject_session_cookie function."""
    return inject_session_cookie


@pytest.fixture
def create_cli_invite():
    """Helper to invoke create_invite CLI command and extract raw token."""
    def _create(username, household_name=None, expires_hours=48):
        from io import StringIO
        out = StringIO()
        kwargs = {"username": username, "expires_hours": expires_hours, "stdout": out}
        if household_name:
            kwargs["household"] = household_name
        call_command("create_invite", **kwargs)
        output = out.getvalue()
        token = output.split("/auth/invite/")[1].split("/")[0].strip()
        return token
    return _create


@pytest.fixture(autouse=True)
def e2e_autologin(request, e2e_household, e2e_user):
    """Automatically authenticate Playwright page unless marked with unauthenticated."""
    E2EContext.household = e2e_household
    E2EContext.user = e2e_user

    if "unauthenticated" not in request.keywords and "page" in request.fixturenames:
        page: Page = request.getfixturevalue("page")
        live_server = request.getfixturevalue("live_server")
        inject_session_cookie(page.context, live_server.url, e2e_user)

    yield

    E2EContext.household = None
    E2EContext.user = None


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args):
    """Provide safe flags for headless chromium execution."""
    import sys
    args = [
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-dev-shm-usage",
    ]
    if sys.platform.startswith("linux"):
        args.append("--single-process")
    return {
        **browser_type_launch_args,
        "args": [
            *args,
            *(browser_type_launch_args.get("args") or []),
        ],
    }


@pytest.fixture(scope="session")
def browser(launch_browser):
    """Safely launch browser or skip if environment prevents browser launch/network."""
    try:
        browser_inst = launch_browser()
        test_context = browser_inst.new_context()
        test_page = test_context.new_page()
        try:
            test_page.goto("http://127.0.0.1:59999", timeout=1500)
        except Exception as probe_err:
            probe_msg = str(probe_err)
            if "ERR_ACCESS_DENIED" in probe_msg:
                try:
                    test_context.close()
                    browser_inst.close()
                except Exception:
                    pass
                pytest.skip(
                    "Playwright browser network restricted by macOS sandbox. "
                    "Run E2E in Docker: docker compose -f docker-compose.test.yml run --rm test"
                )
        try:
            test_context.close()
        except Exception:
            pass
    except Exception as exc:
        pytest.skip(f"Playwright browser could not be launched in this environment: {exc}")
    yield browser_inst
    try:
        browser_inst.close()
    except Exception:
        pass


@pytest.fixture
def e2e_client(client, e2e_user):
    """Authenticated client for the primary household admin user."""
    client.force_login(e2e_user)
    return client


@pytest.fixture
def e2e_spouse_client(e2e_household_spouse):
    """Authenticated client for the primary household spouse member."""
    from django.test import Client

    c = Client()
    c.force_login(e2e_household_spouse)
    return c


@pytest.fixture
def e2e_secondary_client(e2e_secondary_user):
    """Authenticated client for the secondary household admin user."""
    from django.test import Client

    c = Client()
    c.force_login(e2e_secondary_user)
    return c



