"""
Management command to encrypt existing plaintext data in database.

Usage:
    python manage.py encrypt_existing_pii --model User --batch-size 1000 --dry-run
    python manage.py encrypt_existing_pii --model Order --batch-size 1000
    python manage.py encrypt_existing_pii --all  # Encrypt all models

Purpose:
- Gradually migrate existing unencrypted data to encrypted format
- Can be run as background job without downtime
- Includes dry-run mode for verification
- Batch processing to avoid memory overload
- Supports all PII models

Strategy:
1. Read plaintext value from old field
2. Encrypt using encryption_utils
3. Write encrypted value to new _encrypted field
4. Keep plaintext field for fallback/compatibility
5. Once all data migrated, plaintext field can be dropped (future migration)
"""

import logging
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from urbanfoods.models import User, Order, PaymentAttempt
from urbanfoods.encryption_utils import EncryptedFieldManager

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Encrypt existing plaintext PII data for PCI DSS compliance (Day 4)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--model',
            type=str,
            choices=['User', 'Order', 'PaymentAttempt'],
            help='Encrypt specific model'
        )
        parser.add_argument(
            '--all',
            action='store_true',
            help='Encrypt all models'
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=1000,
            help='Number of records per batch (default: 1000)'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Simulate encryption without saving'
        )

    def handle(self, *args, **options):
        model_name = options.get('model')
        encrypt_all = options.get('all')
        batch_size = options.get('batch_size')
        dry_run = options.get('dry_run')

        if dry_run:
            self.stdout.write(self.style.WARNING('🔄 DRY RUN MODE - No changes will be saved'))

        if encrypt_all:
            self.encrypt_user_data(batch_size, dry_run)
            self.encrypt_order_data(batch_size, dry_run)
            self.encrypt_payment_attempt_data(batch_size, dry_run)
        elif model_name == 'User':
            self.encrypt_user_data(batch_size, dry_run)
        elif model_name == 'Order':
            self.encrypt_order_data(batch_size, dry_run)
        elif model_name == 'PaymentAttempt':
            self.encrypt_payment_attempt_data(batch_size, dry_run)
        else:
            raise CommandError('Specify --model or --all')

        self.stdout.write(self.style.SUCCESS('✅ Encryption complete!'))

    def encrypt_user_data(self, batch_size, dry_run):
        """Encrypt User.phone_number and User.email"""
        self.stdout.write('\n📋 Encrypting User data...')

        # Get users with unencrypted phone (doesn't have ENCRYPTED: prefix)
        unencrypted_users = User.objects.exclude(
            phone_number__startswith='ENCRYPTED:'
        ).exclude(
            phone_number__isnull=True
        ).exclude(
            phone_number=''
        )

        total = unencrypted_users.count()
        if total == 0:
            self.stdout.write('  ℹ️  No unencrypted phone numbers found')
        else:
            self.stdout.write(f'  Found {total} users with unencrypted phone numbers')

            processed = 0
            for batch_start in range(0, total, batch_size):
                batch = unencrypted_users[batch_start:batch_start + batch_size]
                
                for user in batch:
                    try:
                        # Encrypt phone_number
                        if user.phone_number:
                            encrypted_phone = EncryptedFieldManager.encrypt_value(
                                user.phone_number,
                                'phone_number'
                            )
                            user.phone_number_encrypted = encrypted_phone
                        
                        # Encrypt email
                        if user.email:
                            encrypted_email = EncryptedFieldManager.encrypt_value(
                                user.email,
                                'email'
                            )
                            user.email_encrypted = encrypted_email
                        
                        if not dry_run:
                            user.save(update_fields=['phone_number_encrypted', 'email_encrypted'])
                        
                        processed += 1
                        
                        if processed % 100 == 0:
                            self.stdout.write(f'  ✓ Encrypted {processed}/{total}')
                    
                    except Exception as e:
                        logger.error(f'Error encrypting user {user.id}: {e}')
                        self.stdout.write(self.style.ERROR(f'  ✗ Error encrypting user {user.id}: {e}'))

        # Email encryption
        unencrypted_emails = User.objects.exclude(
            email__startswith='ENCRYPTED:'
        ).exclude(
            email__isnull=True
        ).exclude(
            email=''
        )

        email_total = unencrypted_emails.count()
        if email_total > 0:
            self.stdout.write(f'  Found {email_total} users with unencrypted emails')

    def encrypt_order_data(self, batch_size, dry_run):
        """Encrypt Order.customer_phone"""
        self.stdout.write('\n📋 Encrypting Order data...')

        unencrypted_orders = Order.objects.exclude(
            customer_phone__startswith='ENCRYPTED:'
        ).exclude(
            customer_phone__isnull=True
        ).exclude(
            customer_phone=''
        )

        total = unencrypted_orders.count()
        if total == 0:
            self.stdout.write('  ℹ️  No unencrypted customer phones found')
        else:
            self.stdout.write(f'  Found {total} orders with unencrypted customer phones')

            processed = 0
            for batch_start in range(0, total, batch_size):
                batch = unencrypted_orders[batch_start:batch_start + batch_size]
                
                for order in batch:
                    try:
                        if order.customer_phone:
                            encrypted_phone = EncryptedFieldManager.encrypt_value(
                                order.customer_phone,
                                'customer_phone'
                            )
                            order.customer_phone_encrypted = encrypted_phone
                        
                        if not dry_run:
                            order.save(update_fields=['customer_phone_encrypted'])
                        
                        processed += 1
                        
                        if processed % 100 == 0:
                            self.stdout.write(f'  ✓ Encrypted {processed}/{total}')
                    
                    except Exception as e:
                        logger.error(f'Error encrypting order {order.id}: {e}')
                        self.stdout.write(self.style.ERROR(f'  ✗ Error encrypting order {order.id}: {e}'))

    def encrypt_payment_attempt_data(self, batch_size, dry_run):
        """Encrypt PaymentAttempt.phone_number"""
        self.stdout.write('\n📋 Encrypting PaymentAttempt data...')

        unencrypted_attempts = PaymentAttempt.objects.exclude(
            phone_number__startswith='ENCRYPTED:'
        ).exclude(
            phone_number__isnull=True
        ).exclude(
            phone_number=''
        )

        total = unencrypted_attempts.count()
        if total == 0:
            self.stdout.write('  ℹ️  No unencrypted M-Pesa phones found')
        else:
            self.stdout.write(f'  Found {total} payment attempts with unencrypted phones')

            processed = 0
            for batch_start in range(0, total, batch_size):
                batch = unencrypted_attempts[batch_start:batch_start + batch_size]
                
                for attempt in batch:
                    try:
                        if attempt.phone_number:
                            encrypted_phone = EncryptedFieldManager.encrypt_value(
                                attempt.phone_number,
                                'phone_number'
                            )
                            attempt.phone_number_encrypted = encrypted_phone
                        
                        if not dry_run:
                            attempt.save(update_fields=['phone_number_encrypted'])
                        
                        processed += 1
                        
                        if processed % 100 == 0:
                            self.stdout.write(f'  ✓ Encrypted {processed}/{total}')
                    
                    except Exception as e:
                        logger.error(f'Error encrypting payment attempt {attempt.id}: {e}')
                        self.stdout.write(self.style.ERROR(f'  ✗ Error encrypting attempt {attempt.id}: {e}'))
