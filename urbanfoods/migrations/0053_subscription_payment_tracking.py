from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('urbanfoods', '0052_order_email_order_phone_store_email_store_phone'),
    ]

    operations = [
        migrations.AddField(
            model_name='subscriptionpayment',
            name='checkout_request_id',
            field=models.CharField(blank=True, db_index=True, max_length=50, null=True, unique=True),
        ),
        migrations.AddField(
            model_name='subscriptionpayment',
            name='phone_number',
            field=models.CharField(blank=True, max_length=15),
        ),
        migrations.AddField(
            model_name='subscriptionpayment',
            name='plan',
            field=models.CharField(blank=True, choices=[('base', 'Base'), ('pro', 'Pro'), ('custom', 'Custom')], max_length=20, null=True),
        ),
        migrations.AddField(
            model_name='subscriptionpayment',
            name='raw_callback',
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='subscriptionpayment',
            name='result_code',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='subscriptionpayment',
            name='result_desc',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='subscriptionpayment',
            name='transaction_date',
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AlterField(
            model_name='subscriptionpayment',
            name='status',
            field=models.CharField(choices=[('pending', 'Pending'), ('success', 'Success'), ('failed', 'Failed')], default='pending', max_length=20),
        ),
    ]
