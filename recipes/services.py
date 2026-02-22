import logging
import httpx
from django.conf import settings
from django.utils import timezone
from .models import MealPlan

logger = logging.getLogger(__name__)

class NotificationService:
    @staticmethod
    async def send_daily_summary(date):
        """
        Aggregate all MealPlan items for the day, calculate start times,
        and send a formatted message to Beacon.
        """
        from asgiref.sync import sync_to_async

        # Fetch meal plans with recipe details in a sync context
        @sync_to_async
        def get_meal_plans():
            return list(MealPlan.objects.filter(date=date).select_related('recipe'))

        meal_plans = await get_meal_plans()
        
        if not meal_plans:
            logger.info(f"No meal plans found for {date}")
            return False

        message_lines = [f"*Cooking Schedule for {date}:*\n"]
        
        for plan in meal_plans:
            recipe = plan.recipe
            name = recipe.title if recipe else plan.custom_meal
            
            # Use provided ready_at or default
            ready_at = plan.ready_at
            if not ready_at:
                from datetime import datetime
                default_time_str = settings.DEFAULT_LUNCH_TIME if plan.meal_type == 'LUNCH' else settings.DEFAULT_DINNER_TIME
                ready_at = datetime.strptime(default_time_str, "%H:%M").time()
            
            # Calculate start time
            total_time = 0
            if recipe:
                total_time = recipe.total_time or (recipe.prep_time or 0) + (recipe.cook_time or 0)
            
            from datetime import datetime, date as dt_date, timedelta
            dummy_dt = datetime.combine(dt_date.today(), ready_at)
            start_dt = dummy_dt - timedelta(minutes=total_time)
            start_time = start_dt.time()

            message_lines.append(
                f"• *{plan.get_meal_type_display()}*: {name}\n"
                f"  - Ready at: {ready_at.strftime('%H:%M')}\n"
                f"  - Start cooking at: *{start_time.strftime('%H:%M')}* ({total_time} min total)\n"
            )

        full_message = "\n".join(message_lines)
        
        payload = {
            "title": "KitchenClip Daily Schedule",
            "message": full_message,
            "level": "info"
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(settings.BEACON_URL, json=payload, timeout=10.0)
                response.raise_for_status()
                logger.info(f"Notification sent to Beacon for {date}")
                return True
        except Exception as e:
            logger.error(f"Failed to send notification to Beacon: {e}")
            logger.info(f"Notification message that failed: {full_message}")
            return False
