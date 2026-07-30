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
}

@app.task(bind=True)
def debug_task(self):
    logger.debug(f'Request: {self.request!r}')