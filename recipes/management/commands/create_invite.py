"""CLI management command to provision users and authorize devices via single-use magic links."""

import argparse

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from recipes.models import Household, InviteToken, UserProfile


class Command(BaseCommand):
    """Generate a single-use passwordless invitation URL for a new user or additional device."""

    help = "Generate a single-use passwordless invitation URL for a new user or additional device."

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        """Define command arguments."""
        parser.add_argument(
            "--username",
            type=str,
            required=True,
            help="Username of the user to invite or authorize.",
        )
        parser.add_argument(
            "--household",
            type=str,
            required=False,
            default=None,
            help="Household name. Required when creating a new user; optional for existing users.",
        )
        parser.add_argument(
            "--expires-hours",
            type=int,
            required=False,
            default=48,
            help="Token validity duration in hours (default: 48). Must be positive.",
        )
        parser.add_argument(
            "--base-url",
            type=str,
            required=False,
            default="http://localhost:8000",
            help="Base URL for generated invite link (default: http://localhost:8000).",
        )

    def handle(self, *args, **options) -> None:
        """Execute invitation generation command."""
        username = (options.get("username") or "").strip()
        if not username:
            raise CommandError("--username cannot be empty.")

        household_name = (options.get("household") or "").strip() or None
        expires_hours = options.get("expires_hours")
        if expires_hours is None or expires_hours <= 0:
            raise CommandError("--expires-hours must be a positive integer.")

        base_url = (options.get("base_url") or "http://localhost:8000").strip().rstrip("/")
        if not base_url:
            base_url = "http://localhost:8000"

        User = get_user_model()
        user = User.objects.filter(username=username).first()

        # -------------------------------------------------------------------
        # Resolution Case A: User already exists (Multi-Device Addition)
        # -------------------------------------------------------------------
        if user is not None:
            profile = getattr(user, "profile", None)
            if profile is not None:
                existing_household = profile.household
                if household_name is not None and household_name != existing_household.name:
                    raise CommandError(
                        f"User '{username}' already belongs to household '{existing_household.name}'. "
                        "Cannot reassign household via create_invite."
                    )
                household = existing_household
            else:
                if not household_name:
                    raise CommandError(
                        f"User '{username}' exists but has no household profile. "
                        "--household is required to associate this user."
                    )
                with transaction.atomic():
                    household, _ = Household.objects.get_or_create(name=household_name)
                    role = "admin" if not household.members.exists() else "member"
                    profile = UserProfile.objects.create(user=user, household=household, role=role)

        # -------------------------------------------------------------------
        # Resolution Case B: User does not exist (Initial User Provisioning)
        # -------------------------------------------------------------------
        else:
            if not household_name:
                raise CommandError(
                    f"User '{username}' does not exist. --household is required when provisioning a new user."
                )
            with transaction.atomic():
                household, _ = Household.objects.get_or_create(name=household_name)
                role = "admin" if not household.members.exists() else "member"
                user = User(username=username)
                user.set_unusable_password()
                user.save()
                profile = UserProfile.objects.create(user=user, household=household, role=role)

        # -------------------------------------------------------------------
        # Token Generation & Banner Output
        # -------------------------------------------------------------------
        invite, raw_token = InviteToken.create_token(
            user=user,
            household=household,
            expires_hours=expires_hours,
        )
        invite_url = f"{base_url}/auth/invite/{raw_token}/"

        self.stdout.write("=" * 70)
        self.stdout.write(self.style.SUCCESS("KitchenClip Passwordless Invite Generated"))
        self.stdout.write("=" * 70)
        self.stdout.write(f"Username:    {user.username}")
        self.stdout.write(f"Household:   {household.name}")
        self.stdout.write(f"Role:        {profile.role}")
        self.stdout.write(f"Expires:     {invite.expires_at.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        self.stdout.write(f"Invite URL:  {invite_url}")
        self.stdout.write("=" * 70)
        self.stdout.write(f"Single-use enrollment link. Valid for {expires_hours} hours.")
