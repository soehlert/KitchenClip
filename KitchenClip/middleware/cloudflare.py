"""Auto-login from header, set is_readonly on request"""

import ipaddress

from django.contrib.auth import authenticate, login, get_user_model
from django.http import HttpResponseForbidden
from django.conf import settings

User = get_user_model()

class CloudflareLoginMiddleware:

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.user.is_authenticated:
            x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
            if x_forwarded_for:
                remote_ip = x_forwarded_for.split(',')[0].strip()
            else:
                remote_ip = request.META.get("REMOTE_ADDR", "")
            
            trusted_subnets = getattr(settings, "TRUSTED_LOCAL_SUBNETS", [])

            on_local_network = any(
                ipaddress.ip_address(remote_ip) in ipaddress.ip_network(subnet, strict=False)
                for subnet in trusted_subnets
            )
            if on_local_network:
                # Bypass CF auth, treat as admin
                local_admin_email = getattr(settings, "LOCAL_ADMIN_EMAIL", "")

                user, created = User.objects.get_or_create(
                    username=local_admin_email,
                    defaults={"email": local_admin_email, "is_active": True},
                )

                login(
                    request,
                    user,
                    backend="recipes.backends.cloudflare.CloudflareAccessBackend",
                )
                request.user = user

            else:
                user = authenticate(request)
                if user:
                    # Log user into session
                    login(request, user)
                    request.user = user
                else:
                    # No header gets 403
                    return HttpResponseForbidden("No access.")

        role_map = getattr(settings, 'ACCESS_ROLE_MAP', {})
        # read Cf-Access-Authenticated-User-Email header
        email = request.META.get('HTTP_CF_ACCESS_AUTHENTICATED_USER_EMAIL')
        
        # Fallback to the logged in user's email for local testing
        if not email and request.user.is_authenticated:
            email = getattr(request.user, "email", "") or getattr(request.user, "username", "")
            
        # get the value from the role_map where the email is the key
        role_value = role_map.get(email)
        
        if role_value == "readonly":
            request.is_readonly = True
        else:
            request.is_readonly = False

        return self.get_response(request)