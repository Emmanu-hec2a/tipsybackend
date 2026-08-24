"""
Django management command to migrate M-Pesa credentials to AWS Secrets Manager.

Usage:
    python manage.py migrate_credentials_to_secrets_manager
    python manage.py migrate_credentials_to_secrets_manager --dry-run
    python manage.py migrate_credentials_to_secrets_manager --store-id 123
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from urbanfoods.models import Store
from urbanfoods.secrets_manager import SecretsManager
from urbanfoods.mpesa_utils import decrypt_value
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Migrate M-Pesa credentials from database encryption to AWS Secrets Manager'

    def add_arguments(self, parser):
        parser.add_argument(
            '--store-id',
            type=int,
            help='Migrate credentials for a specific store ID'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be migrated without actually migrating'
        )
        parser.add_argument(
            '--enable-rotation',
            action='store_true',
            help='Enable automatic credential rotation after migration'
        )

    @transaction.atomic
    def handle(self, *args, **options):
        """Execute the migration."""
        self.stdout.write(self.style.SUCCESS('Starting credential migration to AWS Secrets Manager'))
        
        store_id = options.get('store_id')
        dry_run = options.get('dry_run', False)
        enable_rotation = options.get('enable_rotation', False)
        
        # Get stores to migrate
        if store_id:
            try:
                stores = [Store.objects.get(id=store_id)]
                self.stdout.write(f"Migrating store {store_id}")
            except Store.DoesNotExist:
                self.stdout.write(self.style.ERROR(f"Store {store_id} not found"))
                return
        else:
            # Migrate all stores with M-Pesa credentials
            stores = Store.objects.filter(
                mpesa_consumer_key__isnull=False
            ).exclude(
                mpesa_consumer_key__exact=''
            )
            self.stdout.write(f"Found {stores.count()} stores to migrate")
        
        sm = SecretsManager()
        successful = 0
        failed = 0
        
        for store in stores:
            try:
                # Decrypt credentials from database
                credentials = {
                    'consumer_key': decrypt_value(store.mpesa_consumer_key),
                    'consumer_secret': decrypt_value(store.mpesa_consumer_secret),
                    'passkey': decrypt_value(store.mpesa_passkey),
                    'shortcode': store.mpesa_shortcode,
                }
                
                if not credentials['consumer_key'] or not credentials['consumer_secret']:
                    self.stdout.write(
                        self.style.WARNING(f"Store {store.id} ({store.name}): Incomplete credentials, skipping")
                    )
                    failed += 1
                    continue
                
                if dry_run:
                    self.stdout.write(
                        f"[DRY RUN] Would migrate credentials for store {store.id} ({store.name})"
                    )
                else:
                    # Store to Secrets Manager
                    success = sm.store_credentials(store.id, credentials)
                    
                    if success:
                        self.stdout.write(
                            self.style.SUCCESS(f"✓ Store {store.id} ({store.name}): Migrated successfully")
                        )
                        
                        # Enable rotation if requested
                        if enable_rotation:
                            sm.rotate_credentials(store.id)
                            self.stdout.write(f"  ✓ Enabled automatic rotation")
                        
                        successful += 1
                    else:
                        self.stdout.write(
                            self.style.ERROR(f"✗ Store {store.id} ({store.name}): Migration failed")
                        )
                        failed += 1
                
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f"✗ Store {store.id}: Error - {str(e)}")
                )
                failed += 1
        
        # Summary
        self.stdout.write("\n" + "="*60)
        if dry_run:
            self.stdout.write(self.style.SUCCESS(f"DRY RUN: Would migrate {successful + failed} stores"))
        else:
            self.stdout.write(
                self.style.SUCCESS(f"Migration complete: {successful} successful, {failed} failed")
            )
        
        if failed > 0:
            self.stdout.write(
                self.style.WARNING(f"Check logs for details on {failed} failed migrations")
            )
