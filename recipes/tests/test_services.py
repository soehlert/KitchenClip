import pytest
from datetime import timedelta
from unittest.mock import patch, AsyncMock
from django.utils import timezone
from recipes.models import Recipe, MealPlan
from recipes.services import NotificationService

@pytest.mark.django_db
@pytest.mark.asyncio
@patch('recipes.services.timezone.localtime')
@patch('recipes.services.httpx.AsyncClient.post')
async def test_check_and_send_upcoming_meals_dummy_mode(mock_post, mock_localtime, settings):
    # Setup dummy mode
    settings.ENABLE_COOKING_NOTIFICATIONS = False
    
    # Fix time to noon to prevent midnight wraparound flakes in CI
    fixed_now = timezone.now().astimezone(timezone.get_current_timezone()).replace(hour=12, minute=0, second=0, microsecond=0)
    mock_localtime.return_value = fixed_now
    today = fixed_now.date()
    
    # Create a meal plan exactly at the notification threshold
    # Total time 0 means we notify exactly 30 minutes before ready_at
    ready_time = (fixed_now + timedelta(minutes=30)).time()
    
    recipe = await Recipe.objects.acreate(title="Dummy Recipe", original_url="http://dummy.local")
    plan = await MealPlan.objects.acreate(
        date=today,
        meal_type="LUNCH",
        recipe=recipe,
        ready_at=ready_time,
        notification_sent=False
    )
    
    # Run the service
    sent_count = await NotificationService.check_and_send_upcoming_meals()
    
    # Should flag 1 meal as sent, but NOT fire httpx
    assert sent_count == 1
    mock_post.assert_not_called()
    
    # Verify the database updated the boolean flag
    await plan.arefresh_from_db()
    assert plan.notification_sent is True

@pytest.mark.django_db
@pytest.mark.asyncio
@patch('recipes.services.timezone.localtime')
@patch('recipes.services.httpx.AsyncClient')
async def test_check_and_send_upcoming_meals_live_mode(mock_client_class, mock_localtime, settings):
    # Setup live mode and mock the context manager httpx post response
    settings.ENABLE_COOKING_NOTIFICATIONS = True
    settings.BEACON_URL = "http://testserver.local"
    
    mock_client = AsyncMock()
    mock_post = AsyncMock()
    mock_post.raise_for_status = lambda: None
    mock_client.post.return_value = mock_post
    mock_client_class.return_value.__aenter__.return_value = mock_client
    
    # Fix time to noon to prevent midnight wraparound flakes in CI
    fixed_now = timezone.now().astimezone(timezone.get_current_timezone()).replace(hour=12, minute=0, second=0, microsecond=0)
    mock_localtime.return_value = fixed_now
    today = fixed_now.date()
    
    # 45 min prep + 15 min cook = 60 min total
    # If ready_at is 2 hours from now, threshold is ready_at - 60m - 30m = 1.5 hours before ready_at.
    # Therefore, 2 hours > 1.5 hours => notify_dt hasn't arrived yet.
    future_ready_time = (fixed_now + timedelta(hours=2)).time()
    
    recipe = await Recipe.objects.acreate(title="Future Recipe", prep_time=45, cook_time=15, original_url="http://live.local")
    plan = await MealPlan.objects.acreate(
        date=today,
        meal_type="DINNER",
        recipe=recipe,
        ready_at=future_ready_time,
        notification_sent=False
    )
    
    sent_count = await NotificationService.check_and_send_upcoming_meals()
    
    # Because time hasn't passed the threshold, it sends 0
    assert sent_count == 0
    mock_client.post.assert_not_called()
    
    # Fast forward time to force the threshold
    future_time = fixed_now + timedelta(hours=1)
    mock_localtime.return_value = future_time
    
    sent_count = await NotificationService.check_and_send_upcoming_meals()
    
    # Now it should be sent
    assert sent_count == 1
    mock_client.post.assert_called_once()
    
    # Ensure db was updated
    await plan.arefresh_from_db()
    assert plan.notification_sent is True
