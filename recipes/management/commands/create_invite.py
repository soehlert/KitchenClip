"""CLI management command to provision users and authorize devices via single-use magic links."""

import argparse

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q

from recipes.models import (
    Household,
    InviteToken,
    MealPlan,
    Recipe,
    RecipeTag,
    UserProfile,
)


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
        parser.add_argument(
            "--claim-legacy-data",
            action="store_true",
            default=False,
            help="Transfer unassigned or 'Primary Household' recipes, meal plans, and tags to this household.",
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

        base_url = (
            (options.get("base_url") or "http://localhost:8000").strip().rstrip("/")
        )
        if not base_url:
            base_url = "http://localhost:8000"

        User = get_user_model()
        user = User.objects.filter(username=username).first()

        claim_legacy = options.get("claim_legacy_data", False)

        # -------------------------------------------------------------------
        # Resolution Case A: User already exists (Multi-Device Addition)
        # -------------------------------------------------------------------
        if user is not None:
            profile = getattr(user, "profile", None)
            if profile is not None:
                existing_household = profile.household
                if (
                    household_name is not None
                    and household_name != existing_household.name
                ):
                    if claim_legacy and existing_household.name == "Primary Household":
                        existing_household.name = household_name
                        existing_household.save(update_fields=["name"])
                        household = existing_household
                    else:
                        raise CommandError(
                            f"User '{username}' already belongs to household '{existing_household.name}'. "
                            "Cannot reassign household via create_invite."
                        )
                else:
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
                    profile = UserProfile.objects.create(
                        user=user, household=household, role=role
                    )

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
                profile = UserProfile.objects.create(
                    user=user, household=household, role=role
                )

        # -------------------------------------------------------------------
        # Legacy Data Claiming (Optional --claim-legacy-data flag)
        # -------------------------------------------------------------------
        if claim_legacy:
            with transaction.atomic():
                transferred_recipes = 0
                transferred_plans = 0
                legacy_household = Household.objects.filter(
                    name="Primary Household"
                ).first()

                if legacy_household is not None and legacy_household.pk != household.pk:
                    # 1. Re-scope / merge RecipeTags from legacy household
                    for tag in RecipeTag.objects.filter(household=legacy_household):
                        existing_tag = (
                            RecipeTag.objects.filter(
                                household=household, name__iexact=tag.name
                            ).first()
                            or RecipeTag.objects.filter(
                                household=household, slug=tag.slug
                            ).first()
                        )
                        if existing_tag:
                            for recipe in tag.recipes.all():
                                recipe.tags.remove(tag)
                                recipe.tags.add(existing_tag)
                            tag.delete()
                        else:
                            tag.household = household
                            tag.save(update_fields=["household"])

                    # 2. Re-scope Recipes
                    transferred_recipes += Recipe.objects.filter(
                        household=legacy_household
                    ).update(
                        household=household,
                        created_by=user,
                    )

                    # 3. Re-scope MealPlans
                    transferred_plans += MealPlan.objects.filter(
                        household=legacy_household
                    ).update(
                        household=household,
                        created_by=user,
                    )

                    # 4. Remove empty legacy household
                    legacy_household.delete()

                else:
                    admin_user = User.objects.filter(
                        username="admin", email="admin@example.com"
                    ).first()
                    transferred_recipes += (
                        Recipe.objects.filter(household=household)
                        .filter(
                            Q(created_by__isnull=True)
                            | (Q(created_by=admin_user) if admin_user else Q())
                            | ~Q(created_by=user)
                        )
                        .update(created_by=user)
                    )
                    transferred_plans += (
                        MealPlan.objects.filter(household=household)
                        .filter(
                            Q(created_by__isnull=True)
                            | (Q(created_by=admin_user) if admin_user else Q())
                            | ~Q(created_by=user)
                        )
                        .update(created_by=user)
                    )

                # Capture any unassigned records if present
                transferred_recipes += Recipe.objects.filter(
                    household__isnull=True
                ).update(
                    household=household,
                    created_by=user,
                )
                transferred_plans += MealPlan.objects.filter(
                    household__isnull=True
                ).update(
                    household=household,
                    created_by=user,
                )
                for tag in RecipeTag.objects.filter(household__isnull=True):
                    existing_tag = (
                        RecipeTag.objects.filter(
                            household=household, name__iexact=tag.name
                        ).first()
                        or RecipeTag.objects.filter(
                            household=household, slug=tag.slug
                        ).first()
                    )
                    if existing_tag:
                        for recipe in tag.recipes.all():
                            recipe.tags.remove(tag)
                            recipe.tags.add(existing_tag)
                        tag.delete()
                    else:
                        tag.household = household
                        tag.save(update_fields=["household"])

                # 5. Clean up placeholder admin user if unused
                admin_user = User.objects.filter(
                    username="admin", email="admin@example.com"
                ).first()
                if (
                    admin_user is not None
                    and admin_user.pk != user.pk
                    and not admin_user.passkeys.exists()
                    and not admin_user.invite_tokens.filter(is_used=True).exists()
                ):
                    admin_user.delete()

                self.stdout.write(
                    self.style.SUCCESS(
                        f"Claimed legacy data: {transferred_recipes} recipes, {transferred_plans} meal plans transferred to '{household.name}'."
                    )
                )

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
        self.stdout.write(
            self.style.SUCCESS("KitchenClip Passwordless Invite Generated")
        )
        self.stdout.write("=" * 70)
        self.stdout.write(f"Username:    {user.username}")
        self.stdout.write(f"Household:   {household.name}")
        self.stdout.write(f"Role:        {profile.role}")
        self.stdout.write(
            f"Expires:     {invite.expires_at.strftime('%Y-%m-%d %H:%M:%S UTC')}"
        )
        self.stdout.write(f"Invite URL:  {invite_url}")
        self.stdout.write("=" * 70)
        self.stdout.write(
            f"Single-use enrollment link. Valid for {expires_hours} hours."
        )
