import os
import logging
from celery import Celery
from celery.schedules import crontab

logger = logging.getLogger(__name__)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

app = Celery('tipsytheoryy')

app.config_from_object('django.conf:settings', namespace='CELERY')

app.autodiscover_tasks()

app.conf.beat_schedule = {
    'reconcile-pending-mpesa-payments': {
        'task': 'urbanfoods.tasks.reconcile_pending_mpesa_payments',
        'schedule': 120.0,  # every 2 minutes
    },
    'dispatch-payment-outbox': {
        'task': 'urbanfoods.tasks.dispatch_outbox_events',
        'schedule': 10.0,
    },
    'requeue-deferred-payment-attempts': {
        'task': 'urbanfoods.tasks.requeue_deferred_payment_attempts',
        'schedule': 30.0,
    },
    'review-stale-payment-initiations': {
        'task': 'urbanfoods.tasks.review_stale_initiating_payment_attempts',
        'schedule': 60.0,
    },
    'daily-deals-digest': {
        'task': 'urbanfoods.tasks.send_daily_deals_digest',
        'schedule': crontab(hour=17, minute=0),  # Daily at 5:00 PM EAT
    },
}

@app.task(bind=True)
def debug_task(self):
    logger.debug(f'Request: {self.request!r}')
