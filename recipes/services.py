import logging
import secrets
from datetime import datetime, timedelta

import httpx
from asgiref.sync import sync_to_async
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import MealPlan, Recipe, RecipeIngredient, RecipeTag

logger = logging.getLogger(__name__)


class NotificationService:
    @staticmethod
    async def check_and_send_upcoming_meals():
        """Polls for meals today and sends reminders."""
        now_local = timezone.localtime()
        today = now_local.date()

        @sync_to_async
        def get_pending_meals():
            return list(MealPlan.objects.filter(date=today, notification_sent=False).select_related('recipe'))

        @sync_to_async
        def mark_as_sent(meal):
            meal.notification_sent = True
            meal.save(update_fields=['notification_sent'])

        meal_plans = await get_pending_meals()

        if not meal_plans:
            return 0

        sent_count = 0

        for plan in meal_plans:
            recipe = plan.recipe
            name = recipe.title if recipe else plan.custom_meal

            ready_at = plan.ready_at
            if not ready_at:
                default_time_str = settings.DEFAULT_LUNCH_TIME if plan.meal_type == 'LUNCH' else settings.DEFAULT_DINNER_TIME
                ready_at = datetime.strptime(default_time_str, "%H:%M").time()

            total_time = 0
            if recipe:
                total_time = recipe.total_time or (recipe.prep_time or 0) + (recipe.cook_time or 0)

            ready_at_dt = timezone.make_aware(datetime.combine(today, ready_at))
            start_dt = ready_at_dt - timedelta(minutes=total_time)
            notify_dt = start_dt - timedelta(minutes=30)

            if now_local >= notify_dt:
                message = (
                    f"*{plan.get_meal_type_display()}*: {name}\n"
                    f"• Ready at: {ready_at.strftime('%I:%M %p')}\n"
                    f"• Start cooking at: *{start_dt.strftime('%I:%M %p')}*\n"
                    f"• Time needed: {total_time} min"
                )

                payload = {
                    "title": "KitchenClip Cooking Reminder",
                    "message": message,
                    "level": "info"
                }

                if not getattr(settings, 'ENABLE_COOKING_NOTIFICATIONS', False):
                    logger.info(f"DUMMY MODE (ENABLE_COOKING_NOTIFICATIONS=False): Would have sent reminder for {plan.meal_type} to {settings.BEACON_URL}:\n{message}")
                    await mark_as_sent(plan)
                    sent_count += 1
                else:
                    try:
                        async with httpx.AsyncClient(follow_redirects=True) as client:
                            response = await client.post(settings.BEACON_URL, json=payload, timeout=10.0)
                            response.raise_for_status()
                            await mark_as_sent(plan)
                            sent_count += 1
                            logger.info(f"Sent reminder for {plan.meal_type} on {today}")
                    except Exception as e:
                        logger.error(f"Failed to send reminder for {plan.meal_type}: {e}")

        return sent_count


class RecipeCloningService:
    @classmethod
    @transaction.atomic
    def clone_recipe(
        cls,
        source_recipe: Recipe,
        target_household,
        target_user=None,
        user_notes: str | None = None,
        rating: int | None = None,
        tags: list[str] | None = None,
        is_future: bool = False,
        disambiguate_url: bool = True,
    ) -> Recipe:
        """Deep clone source_recipe into target_household with target_user author and privacy protections."""
        target_url = source_recipe.original_url

        if target_url:
            url_exists = Recipe.objects.filter(household=target_household, original_url=target_url).exists()
            if url_exists:
                if disambiguate_url:
                    suffix = f"#copy-{secrets.token_hex(3)}"
                    if len(source_recipe.original_url) + len(suffix) > 200:
                        base = source_recipe.original_url[: 200 - len(suffix)]
                        target_url = f"{base}{suffix}"
                    else:
                        target_url = f"{source_recipe.original_url}{suffix}"
                else:
                    raise ValueError(f"Recipe with URL '{target_url}' already exists in target household.")

        cloned_recipe = Recipe.objects.create(
            household=target_household,
            created_by=target_user,
            is_shared=False,
            title=source_recipe.title,
            description=source_recipe.description,
            original_url=target_url,
            prep_time=source_recipe.prep_time,
            cook_time=source_recipe.cook_time,
            total_time=source_recipe.total_time,
            servings=source_recipe.servings,
            instructions=source_recipe.instructions,
            image_url=source_recipe.image_url,
            user_notes=user_notes or "",
            rating=rating,
            is_future=is_future,
            is_on_menu=False,
        )

        ingredients_to_create = [
            RecipeIngredient(
                recipe=cloned_recipe,
                ingredient=ri.ingredient,
                raw_text=ri.raw_text,
                quantity=ri.quantity,
                unit=ri.unit,
                preparation=ri.preparation,
                order=ri.order,
            )
            for ri in source_recipe.recipe_ingredients.all().order_by("order")
        ]
        RecipeIngredient.objects.bulk_create(ingredients_to_create)

        target_tags = []
        if tags is not None:
            for tag_name in tags:
                tag_obj = RecipeTag.get_or_create_for_household(
                    household=target_household,
                    name=tag_name,
                )
                if tag_obj:
                    target_tags.append(tag_obj)
        else:
            for tag in source_recipe.tags.all():
                tag_obj = RecipeTag.get_or_create_for_household(
                    household=target_household,
                    name=tag.name,
                    slug=tag.slug,
                    color=tag.color,
                )
                if tag_obj:
                    target_tags.append(tag_obj)

        cloned_recipe.tags.set(target_tags)
        return cloned_recipe


@transaction.atomic
def clone_recipe_to_household(
    source_recipe: Recipe,
    target_household,
    user=None,
    user_notes: str | None = None,
    rating: int | None = None,
    tags: list[str] | None = None,
    is_future: bool = False,
) -> Recipe:
    """Clone a recipe into a target household with privacy protections."""
    return RecipeCloningService.clone_recipe(
        source_recipe=source_recipe,
        target_household=target_household,
        target_user=user,
        user_notes=user_notes,
        rating=rating,
        tags=tags,
        is_future=is_future,
    )
