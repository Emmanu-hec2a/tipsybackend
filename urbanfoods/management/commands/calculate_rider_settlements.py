from django.core.management.base import BaseCommand
from urbanfoods.tasks import calculate_rider_weekly_stats
from django.utils import timezone

class Command(BaseCommand):
    help = 'Manually triggers the weekly rider settlement calculation (normally runs Sundays 23:59)'

    def add_arguments(self, parser):
        parser.add_argument('--date', type=str, help='Force calculation for a specific date (YYYY-MM-DD)')

    def handle(self, *args, **options):
        force_date_str = options.get('date')
        force_date = None
        if force_date_str:
            from datetime import datetime
            force_date = datetime.strptime(force_date_str, '%Y-%m-%d').date()

        self.stdout.write(self.style.SUCCESS(f'Starting rider settlement calculation for {force_date or "today"}...'))
        result = calculate_rider_weekly_stats(force_date=force_date)
        self.stdout.write(self.style.SUCCESS(f'Successfully finished: {result}'))
