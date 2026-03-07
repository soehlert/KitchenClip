"""Read CF header, return user + role"""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import BaseBackend

User = get_user_model()

class CloudflareAccessBackend(BaseBackend):
    """Authentication backend for Cloudflare"""

    def authenticate(self, request, **kwargs):
        """Authenticate a Cloudflare user based on email provided via CF header"""
        if request is None:
            return None

        email = request.META.get('HTTP_CF_ACCESS_AUTHENTICATED_USER_EMAIL')

        # If there's no email that means it didn't come via CF
        if not email:
            return None

        # Dict in .env of emails allowed and their role (admin or readonly)
        role_map = getattr(settings, 'ACCESS_ROLE_MAP', {})

        # Email not in our allowed list, deny
        if email not in role_map:
            return None

        # Get or create a Django user record for this email
        user, _ = User.objects.get_or_create(
            username=email,
            defaults={'email': email, 'is_active': True}
        )

        return user

    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None
