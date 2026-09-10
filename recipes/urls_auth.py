"""Dedicated URLconf for passwordless authentication."""

from django.urls import path

from recipes import views_auth

app_name = "auth"

urlpatterns = [
    path("login/", views_auth.login_view, name="login"),
    path("logout/", views_auth.logout_view, name="logout"),
    path("invite/<str:token>/", views_auth.invite_landing_view, name="invite_landing"),
    path("invite/<str:token>/redeem/", views_auth.invite_redeem_view, name="invite_redeem"),
    path("webauthn/register/options/", views_auth.webauthn_register_options, name="webauthn_register_options"),
    path("webauthn/register/verify/", views_auth.webauthn_register_verify, name="webauthn_register_verify"),
    path("webauthn/login/options/", views_auth.webauthn_login_options, name="webauthn_login_options"),
    path("webauthn/login/verify/", views_auth.webauthn_login_verify, name="webauthn_login_verify"),
]
