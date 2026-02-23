import logging
import httpx
from django.conf import settings
from django.utils import timezone
from .models import MealPlan
from asgiref.sync import sync_to_async
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class NotificationService:
    @staticmethod
    async def check_and_send_upcoming_meals():
        """
        Polls for meals today that:
        1. Have not had their notification sent yet.
        2. Are within (total_time + 30) minutes of their ready_at time.
        Sends an individual notification for each and marks it as sent.
        """

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
            
            # Use provided ready_at or default
            ready_at = plan.ready_at
            if not ready_at:
                default_time_str = settings.DEFAULT_LUNCH_TIME if plan.meal_type == 'LUNCH' else settings.DEFAULT_DINNER_TIME
                ready_at = datetime.strptime(default_time_str, "%H:%M").time()
            
            # Calculate total cooking time
            total_time = 0
            if recipe:
                total_time = recipe.total_time or (recipe.prep_time or 0) + (recipe.cook_time or 0)
            
            # Notification threshold: ready_at minus (total_time + 30 minutes buffer)
            ready_at_dt = timezone.make_aware(datetime.combine(today, ready_at))
            start_dt = ready_at_dt - timedelta(minutes=total_time)
            notify_dt = start_dt - timedelta(minutes=30)
            
            # If current local time has passed the notification threshold, send it
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
