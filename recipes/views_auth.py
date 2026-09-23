"""Views for passwordless invite redemption, WebAuthn passkey registration, and passkey login."""

import json
import logging
import secrets
import time

from django.conf import settings
from django.contrib.auth import login, logout
from django.db import OperationalError, transaction
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from recipes.models import InviteToken, PasskeyCredential
from recipes.webauthn_service import (
    generate_authentication_options,
    generate_registration_options,
    get_expected_origin,
    resolve_rp_id,
    verify_authentication_response,
    verify_registration_response,
)

logger = logging.getLogger(__name__)


@ensure_csrf_cookie
@require_GET
def login_view(request: HttpRequest) -> HttpResponse:
    """Passkey-only login interface. Redirects to / (or safe ?next=) if already authenticated."""
    next_url = request.GET.get("next") or "/"
    if not next_url.startswith("/") or next_url.startswith("//"):
        next_url = "/"
    if request.user.is_authenticated:
        return redirect(next_url)
    return render(request, "auth/login.html", {"next": next_url})


@require_http_methods(["GET", "POST"])
def logout_view(request: HttpRequest) -> HttpResponse:
    """Log out user, flush session, and redirect to /auth/login/."""
    logout(request)
    return redirect("/auth/login/")


@ensure_csrf_cookie
@require_GET
def invite_landing_view(request: HttpRequest, token: str) -> HttpResponse:
    """Idempotent, scanner-safe landing page for single-use invite tokens."""
    token_hash = InviteToken.hash_token(token)
    invite = (
        InviteToken.objects
        .select_related("user", "household", "user__profile")
        .filter(token_hash=token_hash)
        .first()
    )

    if not invite:
        return render(
            request,
            "auth/invite.html",
            {
                "error": "invalid",
                "message": "Invalid or non-existent invite link.",
            },
            status=404,
        )

    if invite.is_used:
        return render(
            request,
            "auth/invite.html",
            {
                "error": "used",
                "message": "This invite link has already been used.",
            },
            status=400,
        )

    if invite.is_expired:
        return render(
            request,
            "auth/invite.html",
            {
                "error": "expired",
                "message": "This invite link has expired. Please request a new invite from your administrator.",
            },
            status=400,
        )

    role = getattr(getattr(invite.user, "profile", None), "role", "member")
    context = {
        "token": token,
        "invite_user": invite.user,
        "household": invite.household,
        "role": role,
        "expires_at": invite.expires_at,
    }
    return render(request, "auth/invite.html", context, status=200)


@require_POST
def invite_redeem_view(request: HttpRequest, token: str) -> HttpResponse:
    """Fallback direct sign-in for browsers/devices without biometric passkey hardware."""
    token_hash = InviteToken.hash_token(token)
    next_url = request.GET.get("next") or "/"
    if not next_url.startswith("/") or next_url.startswith("//"):
        next_url = "/"

    max_retries = 5
    for attempt in range(max_retries):
        try:
            with transaction.atomic():
                invite = (
                    InviteToken.objects
                    .select_for_update()
                    .select_related("user", "household")
                    .filter(token_hash=token_hash)
                    .first()
                )

                if not invite:
                    return render(
                        request,
                        "auth/invite.html",
                        {
                            "error": "invalid",
                            "message": "Invalid or non-existent invite link.",
                        },
                        status=404,
                    )

                if not invite.is_valid:
                    error_code = "used" if invite.is_used else "expired"
                    msg = (
                        "This invite link has already been used."
                        if invite.is_used
                        else "This invite link has expired."
                    )
                    return render(
                        request,
                        "auth/invite.html",
                        {
                            "error": error_code,
                            "message": msg,
                        },
                        status=400,
                    )

                invite.mark_as_used(commit=True)
                login(request, invite.user)
                request.session.set_expiry(31536000)

                logger.info(
                    "Invite token redeemed for user '%s' in household '%s'.",
                    invite.user.username,
                    invite.household.name,
                )
                return redirect(next_url)
        except OperationalError as e:
            if "locked" in str(e).lower() and attempt < max_retries - 1:
                time.sleep(0.02 * (attempt + 1) + (secrets.randbelow(30) / 1000.0))
                continue
            logger.warning("Database locked during invite redeem after %d attempts: %s", attempt + 1, e)
            return render(
                request,
                "auth/invite.html",
                {
                    "error": "busy",
                    "message": "Redemption in progress or database busy, please try again.",
                },
                status=409,
            )


@require_POST
def webauthn_register_options(request: HttpRequest) -> JsonResponse:
    """Issue WebAuthn creation options strictly gated behind valid CLI token."""
    try:
        body = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "Invalid JSON body."}, status=400)

    raw_token = (body.get("token") or "").strip()
    if not raw_token:
        return JsonResponse(
            {"error": "A valid unredeemed invite token is required to register a passkey."},
            status=403,
        )

    token_hash = InviteToken.hash_token(raw_token)
    invite = (
        InviteToken.objects
        .select_related("user", "household")
        .filter(token_hash=token_hash)
        .first()
    )

    if not invite or not invite.is_valid:
        return JsonResponse(
            {"error": "Invite token is invalid, expired, or already used."},
            status=403,
        )

    rp_id = resolve_rp_id(request.get_host())
    rp_name = getattr(settings, "WEBAUTHN_RP_NAME", "KitchenClip")
    options = generate_registration_options(
        user=invite.user,
        token_obj=invite,
        rp_id=rp_id,
        rp_name=rp_name,
        request=request,
    )
    return JsonResponse(options)


@require_POST
def webauthn_register_verify(request: HttpRequest) -> JsonResponse:
    """Verify attestation, persist PasskeyCredential, consume token, and establish session."""
    try:
        body = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "Invalid JSON body."}, status=400)

    raw_token = (body.get("token") or "").strip()
    if not raw_token:
        return JsonResponse(
            {"error": "A valid unredeemed invite token is required to register a passkey."},
            status=403,
        )

    credential_data = body.get("credential")
    device_name = (body.get("name") or "").strip()
    next_url = request.GET.get("next") or body.get("next") or "/"
    if not next_url.startswith("/") or next_url.startswith("//"):
        next_url = "/"

    token_hash = InviteToken.hash_token(raw_token)

    max_retries = 5
    for attempt in range(max_retries):
        try:
            with transaction.atomic():
                invite = (
                    InviteToken.objects
                    .select_for_update()
                    .select_related("user", "household")
                    .filter(token_hash=token_hash)
                    .first()
                )

                if not invite or not invite.is_valid:
                    return JsonResponse(
                        {"error": "Invite token is invalid, expired, or already used."},
                        status=403,
                    )

                expected_token_hash = request.session.get("webauthn_reg_token_hash")
                if expected_token_hash and not secrets.compare_digest(invite.token_hash, expected_token_hash):
                    return JsonResponse(
                        {"error": "Invite token does not match registration session."},
                        status=403,
                    )

                expected_challenge = request.session.get("webauthn_reg_challenge")
                if not expected_challenge:
                    return JsonResponse(
                        {"error": "Registration challenge expired or missing session."},
                        status=400,
                    )

                if not credential_data:
                    return JsonResponse({"error": "Missing credential payload."}, status=400)

                rp_id = resolve_rp_id(request.get_host())
                expected_origin = get_expected_origin(request)

                try:
                    verification = verify_registration_response(
                        credential_data=credential_data,
                        expected_challenge=expected_challenge,
                        expected_rp_id=rp_id,
                        user=invite.user,
                        expected_origin=expected_origin,
                    )
                except ValueError as e:
                    return JsonResponse({"error": str(e)}, status=400)

                PasskeyCredential.objects.create(
                    user=invite.user,
                    credential_id=verification["credential_id"],
                    public_key=verification["public_key"],
                    sign_count=verification.get("sign_count", 0),
                    name=device_name,
                    aaguid=verification.get("aaguid", ""),
                )

                invite.mark_as_used(commit=True)

                request.session.pop("webauthn_reg_challenge", None)
                request.session.pop("webauthn_reg_token_hash", None)

                login(request, invite.user)
                request.session.set_expiry(31536000)

                return JsonResponse({"success": True, "redirect_url": next_url})
        except OperationalError as e:
            if "locked" in str(e).lower() and attempt < max_retries - 1:
                time.sleep(0.02 * (attempt + 1) + (secrets.randbelow(30) / 1000.0))
                continue
            logger.warning("Database locked during webauthn register verify after %d attempts: %s", attempt + 1, e)
            return JsonResponse(
                {"error": "Redemption in progress or database busy, please try again."},
                status=409,
            )


@require_POST
def webauthn_login_options(request: HttpRequest) -> JsonResponse:
    """Issue WebAuthn request options for existing device passkey sign-in."""
    rp_id = resolve_rp_id(request.get_host())
    options = generate_authentication_options(rp_id=rp_id, request=request)
    return JsonResponse(options)


@require_POST
def webauthn_login_verify(request: HttpRequest) -> JsonResponse:
    """Verify assertion signature, enforce monotonic counter, and log in."""
    try:
        body = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "Invalid JSON body."}, status=400)

    credential_data = body.get("credential")
    if not credential_data:
        return JsonResponse({"error": "Missing credential payload."}, status=400)

    expected_challenge = request.session.get("webauthn_auth_challenge")
    if not expected_challenge:
        return JsonResponse(
            {"error": "Authentication challenge expired or missing session."},
            status=400,
        )

    rp_id = resolve_rp_id(request.get_host())
    expected_origin = get_expected_origin(request)

    try:
        verification = verify_authentication_response(
            credential_data=credential_data,
            expected_challenge=expected_challenge,
            expected_rp_id=rp_id,
            expected_origin=expected_origin,
        )
    except ValueError as e:
        err_msg = str(e)
        if "rollback detected" in err_msg.lower():
            return JsonResponse({"error": err_msg}, status=403)
        return JsonResponse({"error": err_msg}, status=400)

    request.session.pop("webauthn_auth_challenge", None)

    login(request, verification["user"])
    request.session.set_expiry(31536000)

    next_url = request.GET.get("next") or body.get("next") or "/"
    if not next_url.startswith("/") or next_url.startswith("//"):
        next_url = "/"

    return JsonResponse({"success": True, "redirect_url": next_url})
