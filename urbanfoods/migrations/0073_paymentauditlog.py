"""
Django migration to create PaymentAuditLog table

This migration creates the audit logging infrastructure for payment operations.
It's designed to be non-breaking and can be applied to existing databases.
"""

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('urbanfoods', '0072_callbackinbox_callback_status_next_idx_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='PaymentAuditLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('timestamp', models.DateTimeField(auto_now_add=True, db_index=True, help_text='When the action occurred (UTC)')),
                ('content_type', models.CharField(db_index=True, help_text="Model name (e.g., 'PaymentAttempt')", max_length=100)),
                ('object_id', models.CharField(db_index=True, help_text='ID of the object being modified', max_length=100)),
                ('action', models.CharField(choices=[('create', 'Created'), ('update', 'Updated'), ('delete', 'Deleted'), ('manual_review', 'Marked for Manual Review'), ('approve', 'Approved'), ('reject', 'Rejected'), ('refund', 'Initiated Refund'), ('dispute', 'Marked as Disputed')], db_index=True, help_text='Type of action performed', max_length=20)),
                ('reason', models.TextField(blank=True, help_text="Reason/comment for the action (admin's explanation)", null=True)),
                ('changes', models.JSONField(default=dict, help_text="Dictionary of changed fields: {'field': {'old': value, 'new': value}}")),
                ('ip_address', models.GenericIPAddressField(blank=True, db_index=True, help_text='IP address of the admin', null=True)),
                ('user_agent', models.TextField(blank=True, help_text='Browser user agent string', null=True)),
                ('admin_user', models.ForeignKey(help_text='Admin user who performed the action', on_delete=django.db.models.deletion.PROTECT, related_name='payment_audit_logs', to='urbanfoods.user')),
            ],
            options={
                'verbose_name': 'Payment Audit Log',
                'verbose_name_plural': 'Payment Audit Logs',
                'db_table': 'payment_audit_log',
                'ordering': ['-timestamp'],
            },
        ),
        migrations.AddIndex(
            model_name='paymentauditlog',
            index=models.Index(fields=['admin_user', 'timestamp'], name='payment_audi_admin_u_012345_idx'),
        ),
        migrations.AddIndex(
            model_name='paymentauditlog',
            index=models.Index(fields=['object_id', 'content_type'], name='payment_audi_object__012345_idx'),
        ),
        migrations.AddIndex(
            model_name='paymentauditlog',
            index=models.Index(fields=['action', 'timestamp'], name='payment_audi_action__012345_idx'),
        ),
    ]
