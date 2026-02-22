import asyncio
from django.core.management.base import BaseCommand
from django.utils import timezone
from recipes.services import NotificationService

class Command(BaseCommand):
    help = 'Send a daily cooking summary to Beacon'

    def handle(self, *args, **options):
        today = timezone.now().date()
        self.stdout.write(f"Preparing cooking summary for {today}...")
        
        try:
            success = asyncio.run(NotificationService.send_daily_summary(today))
            if success:
                self.stdout.write(self.style.SUCCESS(f"Successfully sent cooking summary for {today}"))
            else:
                self.stdout.write(self.style.WARNING(f"No summary sent for {today} (possibly no meals planned)"))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Error sending cooking summary: {e}"))
