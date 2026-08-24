from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import OutboxEvent


def create_outbox_event(event_type, aggregate_type, aggregate_id, payload, payment_attempt=None):
    event, created = OutboxEvent.objects.get_or_create(
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=str(aggregate_id),
        defaults={
            'payment_attempt': payment_attempt,
            'payload': payload,
            'idempotency_key': f'{event_type}:{aggregate_type}:{aggregate_id}',
            'next_attempt_at': timezone.now(),
        },
    )
    if created:
        transaction.on_commit(_wake_outbox_dispatcher)
    return event


def _wake_outbox_dispatcher():
    # Django's test runner has no broker; production uses this fast wake-up
    # plus the periodic beat schedule as a recovery path.
    import sys
    if any(arg == 'test' or arg.startswith('test:') for arg in sys.argv):
        return
    from .tasks import dispatch_outbox_events
    dispatch_outbox_events.delay()


def claim_outbox_event(event_id):
    with transaction.atomic():
        event = OutboxEvent.objects.select_for_update().get(pk=event_id)
        if event.status == OutboxEvent.Status.PROCESSED:
            return None
        event.status = OutboxEvent.Status.PROCESSING
        event.attempts += 1
        event.save(update_fields=['status', 'attempts', 'updated_at'])
        return event


def mark_outbox_processed(event_id):
    OutboxEvent.objects.filter(pk=event_id).update(
        status=OutboxEvent.Status.PROCESSED,
        processed_at=timezone.now(),
        last_error='',
    )
    try:
        from .observability import log_payment_event
        event = OutboxEvent.objects.select_related('payment_attempt').get(pk=event_id)
        log_payment_event('outbox_processed', event.payment_attempt, source='outbox', event_type=event.event_type)
    except Exception:
        pass


def mark_outbox_retry(event_id, error, max_attempts=8):
    event = OutboxEvent.objects.get(pk=event_id)
    delay = min(3600, 2 ** min(event.attempts, 10))
    status = OutboxEvent.Status.DEAD if event.attempts >= max_attempts else OutboxEvent.Status.RETRY
    OutboxEvent.objects.filter(pk=event_id).update(
        status=status,
        next_attempt_at=timezone.now() + timedelta(seconds=delay),
        last_error=str(error)[:4000],
    )
    try:
        from .observability import log_payment_event
        event = OutboxEvent.objects.select_related('payment_attempt').get(pk=event_id)
        log_payment_event('outbox_retry', event.payment_attempt, source='outbox', event_type=event.event_type)
    except Exception:
        pass
