from functools import wraps

from django.conf import settings
from django.contrib.auth import get_user_model, login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect

from recipes.models import Household, UserProfile


def _auto_login_dev_user(request) -> None:
    """Automatically authenticate a default household user in local DEBUG mode."""
    if request.user.is_authenticated:
        return
    if not getattr(settings, "DEBUG", False) or not getattr(settings, "DEV_AUTO_LOGIN", True):
        return

    preferred_username = getattr(settings, "DEV_AUTO_LOGIN_USER", "sam")
    profile = (
        UserProfile.objects.select_related("user", "household")
        .filter(user__username=preferred_username, household__isnull=False)
        .first()
    )
    if not profile:
        profile = (
            UserProfile.objects.select_related("user", "household")
            .filter(household__isnull=False)
            .first()
        )
    if not profile:
        user_model = get_user_model()
        household, _ = Household.objects.get_or_create(name="Local Dev")
        user, _ = user_model.objects.get_or_create(username=preferred_username)
        profile, _ = UserProfile.objects.get_or_create(user=user, defaults={"household": household})

    login(request, profile.user, backend="django.contrib.auth.backends.ModelBackend")


class HouseholdLoginRequiredMixin(LoginRequiredMixin):
    """Enforce user authentication and resolve active household."""

    login_url = settings.LOGIN_URL

    @property
    def household(self):
        """Convenience property to access current user's household."""
        profile = getattr(self.request.user, "profile", None)
        if profile and profile.household:
            return profile.household
        raise PermissionDenied("User is not associated with an active household.")

    def dispatch(self, request, *args, **kwargs):
        _auto_login_dev_user(request)
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not hasattr(request.user, "profile") or request.user.profile.household is None:
            raise PermissionDenied("User is not associated with an active household.")
        return super().dispatch(request, *args, **kwargs)


class AdminRequiredMixin(HouseholdLoginRequiredMixin):
    """Verify that current user is authenticated and not flagged as read-only."""

    def dispatch(self, request, *args, **kwargs):
        _auto_login_dev_user(request)
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if getattr(request, "is_readonly", False):
            raise PermissionDenied("You do not have permission to perform this action.")
        return super().dispatch(request, *args, **kwargs)


def household_required(view_func):
    """Decorator ensuring authentication, active household, and attaching request.household."""

    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        _auto_login_dev_user(request)
        if not request.user.is_authenticated:
            return redirect(f"{settings.LOGIN_URL}?next={request.path}")
        profile = getattr(request.user, "profile", None)
        if profile and profile.household:
            request.household = profile.household
        else:
            raise PermissionDenied("User is not associated with an active household.")
        return view_func(request, *args, **kwargs)

    return _wrapped_view


def require_admin(view_func):
    """Decorator ensuring user is authenticated, has household, and is not read-only."""

    @wraps(view_func)
    @household_required
    def _wrapped_view(request, *args, **kwargs):
        if getattr(request, "is_readonly", False):
            raise PermissionDenied("You do not have permission to perform this action.")
        return view_func(request, *args, **kwargs)

    return _wrapped_view
