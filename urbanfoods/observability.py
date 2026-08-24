"""Best-effort payment metrics and redacted operational logging."""

import hashlib
import logging
import os
from django.conf import settings
from django.db import connection
from django.core.cache import cache
from django.utils import timezone

from .models import CallbackInbox, OutboxEvent, PaymentAttempt

logger = logging.getLogger('payment_observability')
METRIC_PREFIX = 'tipsy:payment:metric:'

METRIC_NAMES = (
    'payment_initiation_total',
    'payment_initiation_failure_total',
    'payment_callback_received_total',
    'payment_callback_processing_total',
    'payment_confirmation_total',
    'payment_failure_total',
    'payment_reconciliation_total',
    'payment_unmatched_total',
    'payment_duplicate_event_total',
    'payment_amount_mismatch_total',
    'payment_manual_review_total',
    'payment_provider_queue_deferred_total',
    'payment_provider_circuit_open_total',
)


def increment_metric(name, amount=1):
    if name not in METRIC_NAMES:
        return
    key = f'{METRIC_PREFIX}{name}'
    try:
        if not cache.add(key, 0, timeout=None):
            cache.incr(key, amount)
        elif amount != 1:
            cache.incr(key, amount - 1)
    except Exception:
        # Metrics must never make a payment or callback fail.
        logger.debug('Metric backend unavailable for %s', name, exc_info=True)


def metric_snapshot():
    values = {}
    for name in METRIC_NAMES:
        try:
            values[name] = int(cache.get(f'{METRIC_PREFIX}{name}') or 0)
        except Exception:
            values[name] = None
    return values


def redact_identifier(value, keep=6):
    if not value:
        return None
    value = str(value)
    if len(value) <= keep:
        return hashlib.sha256(value.encode()).hexdigest()[:12]
    return f'...{value[-keep:]}'


def payment_context(attempt):
    target_id = attempt.order_id or attempt.subscription_payment_id or attempt.shiriki_contribution_id
    return {
        'payment_id': str(attempt.public_payment_id),
        'provider': attempt.provider,
        'payment_type': attempt.payment_type,
        'target_id': str(target_id) if target_id else None,
        'checkout_request_id': redact_identifier(attempt.checkout_request_id),
    }


def log_payment_event(event, attempt=None, source=None, **extra):
    payload = {'event': event, 'source': source}
    if attempt is not None:
        payload.update(payment_context(attempt))
    payload.update({key: value for key, value in extra.items() if value is not None})
    logger.info(payload)


def record_payment_transition(attempt, previous_status, source):
    current = attempt.status
    if previous_status == current:
        increment_metric('payment_duplicate_event_total')
        log_payment_event('payment_duplicate_event', attempt, source=source, status=current)
        return
    if current == PaymentAttempt.Status.CONFIRMED:
        increment_metric('payment_confirmation_total')
    elif current == PaymentAttempt.Status.FAILED:
        increment_metric('payment_failure_total')
    elif current == PaymentAttempt.Status.MANUAL_REVIEW:
        increment_metric('payment_manual_review_total')
    log_payment_event('payment_status_transition', attempt, source=source,
                      previous_status=previous_status, status=current)


def database_snapshot():
    now = timezone.now()
    pending = PaymentAttempt.objects.filter(status__in=[
        PaymentAttempt.Status.INITIATING, PaymentAttempt.Status.PENDING,
    ])
    oldest = pending.order_by('created_at').values_list('created_at', flat=True).first()
    pending_age = int((now - oldest).total_seconds()) if oldest else 0
    completed = list(PaymentAttempt.objects.filter(
        status=PaymentAttempt.Status.CONFIRMED,
        confirmed_at__isnull=False,
    ).order_by('-confirmed_at').values_list('created_at', 'confirmed_at')[:1000])
    latencies = sorted(max(0, int((confirmed - created).total_seconds())) for created, confirmed in completed)
    latency = {
        'sample_count': len(latencies),
        'average_seconds': round(sum(latencies) / len(latencies), 2) if latencies else 0,
        'p95_seconds': latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))] if latencies else 0,
    }
    return {
        'pending_payment_count': pending.count(),
        'pending_payment_age_seconds': pending_age,
        'callback_inbox_backlog': CallbackInbox.objects.filter(
            status__in=[CallbackInbox.Status.RECEIVED, CallbackInbox.Status.PROCESSING, CallbackInbox.Status.RETRY]
        ).count(),
        'callback_unmatched_count': CallbackInbox.objects.filter(status=CallbackInbox.Status.UNMATCHED).count(),
        'callback_manual_review_count': CallbackInbox.objects.filter(status=CallbackInbox.Status.MANUAL_REVIEW).count(),
        'outbox_backlog': OutboxEvent.objects.filter(
            status__in=[OutboxEvent.Status.PENDING, OutboxEvent.Status.PROCESSING, OutboxEvent.Status.RETRY]
        ).count(),
        'outbox_dead_count': OutboxEvent.objects.filter(status=OutboxEvent.Status.DEAD).count(),
        'payment_confirmation_latency': latency,
        'provider_initiation_queue_depth': PaymentAttempt.objects.filter(
            status__in=[PaymentAttempt.Status.PENDING, PaymentAttempt.Status.INITIATING],
            checkout_request_id__isnull=True,
        ).count(),
    }


def infrastructure_snapshot():
    """Return safe capacity facts for the restricted operations endpoint."""
    database = {'vendor': connection.vendor, 'active_connections': None, 'max_connections': None}
    if connection.vendor == 'postgresql':
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()")
                database['active_connections'] = cursor.fetchone()[0]
                cursor.execute('SHOW max_connections')
                database['max_connections'] = int(cursor.fetchone()[0])
        except Exception:
            logger.debug('Could not read PostgreSQL connection capacity', exc_info=True)
    return {
        'database': database,
        'connection_max_age_seconds': getattr(settings, 'DB_CONN_MAX_AGE', None),
        'configured_db_pool_size': os.environ.get('DB_POOL_SIZE'),
        'celery_worker_concurrency': getattr(settings, 'CELERY_WORKER_CONCURRENCY', None),
        'celery_worker_max_tasks_per_child': getattr(settings, 'CELERY_WORKER_MAX_TASKS_PER_CHILD', None),
        'celery_prefetch_multiplier': getattr(settings, 'CELERY_WORKER_PREFETCH_MULTIPLIER', None),
        'redis_configured': bool(os.environ.get('REDIS_URL')),
        'payment_queues': ['payment_initiation', 'payment_reconciliation', 'payment_notifications'],
    }
