"""
Migration to add encryption for sensitive PII fields (Day 4)

Strategy:
1. Phase 1 (THIS MIGRATION): Add encrypted field columns alongside existing plaintext
2. Phase 2 (LATER): Data migration - encrypt existing data in background
3. Phase 3 (FUTURE): Remove plaintext columns after all data migrated

This approach ensures:
- ✅ No downtime
- ✅ No data loss
- ✅ Backward compatibility (existing queries still work)
- ✅ Gradual migration (can be done in background job)
- ✅ Easy rollback (keep plaintext fields as fallback)

Fields to Encrypt:
- User.phone_number
- User.email
- Customer.phone (if exists)
- Order.customer_phone
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('urbanfoods', '0073_paymentauditlog'),  # Updated: audit log migration renamed to 0073
    ]

    operations = [
        # ═══════════════════════════════════════════════════════════════
        # USER MODEL: Add phone_number and email encryption
        # ═══════════════════════════════════════════════════════════════
        
        migrations.AddField(
            model_name='user',
            name='phone_number_encrypted',
            field=models.TextField(
                null=True,
                blank=True,
                help_text='🛡️ Encrypted phone number (ENCRYPTED: prefix). Read via get_phone_number() method.'
            ),
        ),
        
        migrations.AddField(
            model_name='user',
            name='email_encrypted',
            field=models.TextField(
                null=True,
                blank=True,
                help_text='🛡️ Encrypted email (ENCRYPTED: prefix). Read via get_email() method.'
            ),
        ),
        
        # ═══════════════════════════════════════════════════════════════
        # ORDER MODEL: Add customer_phone encryption
        # ═══════════════════════════════════════════════════════════════
        
        migrations.AddField(
            model_name='order',
            name='customer_phone_encrypted',
            field=models.TextField(
                null=True,
                blank=True,
                help_text='🛡️ Encrypted customer phone (ENCRYPTED: prefix). Read via get_customer_phone() method.'
            ),
        ),
        
        # ═══════════════════════════════════════════════════════════════
        # PAYMENTATTEMPT MODEL: Add phone_number encryption
        # ═══════════════════════════════════════════════════════════════
        
        migrations.AddField(
            model_name='paymentattempt',
            name='phone_number_encrypted',
            field=models.TextField(
                null=True,
                blank=True,
                help_text='🛡️ Encrypted M-Pesa phone (ENCRYPTED: prefix). Read via get_phone_number() method.'
            ),
        ),
        
        # ═══════════════════════════════════════════════════════════════
        # Add database indexes for encrypted fields
        # ═══════════════════════════════════════════════════════════════
        
        migrations.AddIndex(
            model_name='user',
            index=models.Index(fields=['phone_number_encrypted'], name='user_phone_encrypted_idx'),
        ),
        
        migrations.AddIndex(
            model_name='order',
            index=models.Index(fields=['customer_phone_encrypted'], name='order_phone_encrypted_idx'),
        ),
    ]
