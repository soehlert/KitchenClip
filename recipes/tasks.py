import asyncio
from celery import shared_task
from .services import NotificationService
import logging

logger = logging.getLogger(__name__)

@shared_task
def check_upcoming_meals_task():
    """
    Celery task that runs every 5 minutes to check for upcoming meals
    that need cooking reminders sent.
    """
    logger.info("Running check_upcoming_meals_task")
    
    try:
        # Run the async notification service method
        sent = asyncio.run(NotificationService.check_and_send_upcoming_meals())
        return f"Checked upcoming meals. Sent {sent} notifications."
    except Exception as e:
        logger.error(f"Error in check_upcoming_meals_task: {e}")
        raise
