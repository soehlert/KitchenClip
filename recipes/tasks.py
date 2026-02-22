import asyncio
from celery import shared_task
from django.utils import timezone
from .services import NotificationService
import logging

logger = logging.getLogger(__name__)

@shared_task
def send_cooking_summary_task():
    """
    Celery task to send the daily cooking summary notification.
    """
    today = timezone.now().date()
    logger.info(f"Running send_cooking_summary_task for {today}")
    
    try:
        # Run the async notification service method
        success = asyncio.run(NotificationService.send_daily_summary(today))
        if success:
            return f"Successfully sent cooking summary for {today}"
        else:
            return f"No summary sent for {today} (possibly no meals planned or Beacon unreachable)"
    except Exception as e:
        logger.error(f"Error in send_cooking_summary_task: {e}")
        raise
