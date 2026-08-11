"""
Management command to clear M-Pesa credentials from database.
Used when credentials cannot be decrypted due to encryption key mismatch.
Run: python manage.py clear_mpesa_credentials
"""
from django.core.management.base import BaseCommand
from django.core.cache import cache
from urbanfoods.models import Store
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Clear M-Pesa credentials from database and Redis cache. Used when starting fresh due to encryption key mismatch.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--store-id',
            type=int,
            help='Clear credentials for specific store ID only (by default, clears all stores)',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Skip confirmation prompt',
        )

    def handle(self, *args, **options):
        store_id = options.get('store_id')
        force = options.get('force', False)

        # Determine which stores to clear
        if store_id:
            stores = Store.objects.filter(id=store_id)
            if not stores.exists():
                self.stdout.write(self.style.ERROR(f'Store with ID {store_id} not found.'))
                return
        else:
            stores = Store.objects.filter(
                mpesa_consumer_key__isnull=False
            ).exclude(mpesa_consumer_key='')

        if not stores.exists():
            self.stdout.write(self.style.WARNING('No stores with M-Pesa credentials found.'))
            return

        self.stdout.write(self.style.WARNING(f'\n⚠️  This will clear M-Pesa credentials for {stores.count()} store(s):'))
        for store in stores:
            self.stdout.write(f'  • {store.name} (ID: {store.id})')

        if not force:
            confirm = input('\n⚠️  Continue? This action cannot be undone. Type "yes" to confirm: ')
            if confirm.lower() != 'yes':
                self.stdout.write(self.style.ERROR('Cancelled.'))
                return

        # Clear M-Pesa credentials from database
        cleared_count = 0
        for store in stores:
            self.stdout.write(f'Clearing credentials for {store.name}...')
            store.mpesa_consumer_key = None
            store.mpesa_consumer_secret = None
            store.mpesa_passkey = None
            store.save(update_fields=['mpesa_consumer_key', 'mpesa_consumer_secret', 'mpesa_passkey'])
            cleared_count += 1
            logger.info(f'Cleared M-Pesa credentials for store: {store.name}')

        # Clear Redis cache for M-Pesa tokens
        try:
            # Clear all M-Pesa token cache keys
            cache_keys = [f'mpesa_token_{store.mpesa_shortcode}' for store in stores if store.mpesa_shortcode]
            cache_keys.append('mpesa_access_token')  # Legacy cache key
            
            for key in cache_keys:
                cache.delete(key)
                self.stdout.write(f'Cleared cache key: {key}')
            
            logger.info(f'Cleared {len(cache_keys)} M-Pesa cache keys from Redis')
        except Exception as e:
            self.stdout.write(self.style.WARNING(f'Warning: Could not clear cache: {e}'))
            logger.warning(f'Could not clear M-Pesa cache: {e}')

        self.stdout.write(self.style.SUCCESS(
            f'\n✅ Cleared M-Pesa credentials for {cleared_count} store(s) and Redis cache.\n'
            f'Next steps:\n'
            f'  1. Go to Django admin → Stores\n'
            f'  2. Select each store and re-enter M-Pesa credentials\n'
            f'  3. Credentials will be encrypted with your current ENCRYPTION_KEY\n'
            f'  4. Restart your application if needed\n'
        ))

