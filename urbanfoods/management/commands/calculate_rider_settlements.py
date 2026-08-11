from django.core.management.base import BaseCommand
from urbanfoods.tasks import calculate_rider_weekly_stats
from django.utils import timezone

class Command(BaseCommand):
    help = 'Manually triggers the weekly rider settlement calculation (normally runs Sundays 23:59)'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Starting rider settlement calculation...'))
        result = calculate_rider_weekly_stats()
        self.stdout.write(self.style.SUCCESS(f'Successfully finished: {result}'))
