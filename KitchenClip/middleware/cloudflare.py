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
            remote_ip = request.META.get("REMOTE_ADDR", "")
            trusted_subnets = getattr(settings, "TRUSTED_LOCAL_SUBNETS", [])
            print(f"DEBUG: REMOTE_ADDR={remote_ip}")
            print(f"DEBUG: TRUSTED_LOCAL_SUBNETS={trusted_subnets}")
            print(f"DEBUG: user authenticated={request.user.is_authenticated}")

            on_local_network = any(
                ipaddress.ip_address(remote_ip) in ipaddress.ip_network(subnet, strict=False)
                for subnet in trusted_subnets
            )
            print(f"DEBUG: on_local_network={on_local_network}")

            if on_local_network:
                # Bypass CF auth, treat as admin
                local_admin_email = getattr(settings, "LOCAL_ADMIN_EMAIL", "")
                print(f"DEBUG: LOCAL_ADMIN_EMAIL={local_admin_email}")

                user, created = User.objects.get_or_create(
                    username=local_admin_email,
                    defaults={"email": local_admin_email, "is_active": True},
                )
                print(f"DEBUG: user={user}, created={created}")

                login(
                    request,
                    user,
                    backend="recipes.backends.cloudflare.CloudflareAccessBackend",
                )
                print(f"DEBUG: login called successfully")

            else:
                user = authenticate(request)
                if user:
                    # Log user into session
                    login(request, user)
                else:
                    # No header gets 403
                    return HttpResponseForbidden("No access.")

        role_map = getattr(settings, 'ACCESS_ROLE_MAP', {})
        # read Cf-Access-Authenticated-User-Email header
        email = request.META.get('HTTP_CF_ACCESS_AUTHENTICATED_USER_EMAIL')

        # get the value from the role_map where the email is the key
        role_map = role_map.get(email)
        if role_map == "readonly":
            request.is_readonly = True
        else:
            request.is_readonly = False

        return self.get_response(request)