from functools import wraps

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect


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
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not hasattr(request.user, "profile") or request.user.profile.household is None:
            raise PermissionDenied("User is not associated with an active household.")
        return super().dispatch(request, *args, **kwargs)


class AdminRequiredMixin(HouseholdLoginRequiredMixin):
    """Verify that current user is authenticated and not flagged as read-only."""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if getattr(request, "is_readonly", False):
            raise PermissionDenied("You do not have permission to perform this action.")
        return super().dispatch(request, *args, **kwargs)


def household_required(view_func):
    """Decorator ensuring authentication, active household, and attaching request.household."""

    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
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
