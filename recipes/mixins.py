from functools import wraps

from django.core.exceptions import PermissionDenied


class AdminRequiredMixin:
    """Verify that the current user is an admin (not read-only)."""
    
    def dispatch(self, request, *args, **kwargs):
        if getattr(request, 'is_readonly', False):
            raise PermissionDenied("You do not have permission to perform this action.")
        return super().dispatch(request, *args, **kwargs)

def require_admin(view_func):
    """Decorator for views that checks that the user is an admin."""
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if getattr(request, 'is_readonly', False):
            raise PermissionDenied("You do not have permission to perform this action.")
        return view_func(request, *args, **kwargs)
    return _wrapped_view
