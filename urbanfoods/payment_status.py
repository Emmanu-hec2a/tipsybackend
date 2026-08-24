from django.core.cache import cache
from django.utils import timezone


TERMINAL_PAYMENT_STATUSES = frozenset({
    'confirmed', 'failed', 'expired', 'manual_review', 'overpaid', 'refund_required',
})


def status_cache_key(user_id, payment_id):
    return f'tipsy:payment-status:{user_id}:{payment_id}'


def get_cached_status(user_id, payment_id):
    try:
        return cache.get(status_cache_key(user_id, payment_id))
    except Exception:
        return None


def cache_status(user_id, payment_id, payload, status):
    # Terminal responses may be reused longer; pending responses are short-lived
    # so a callback becomes visible quickly without hammering PostgreSQL.
    timeout = 30 if status in TERMINAL_PAYMENT_STATUSES else 2
    try:
        cache.set(status_cache_key(user_id, payment_id), payload, timeout=timeout)
    except Exception:
        pass


def next_poll_after(attempt):
    if attempt.status not in ('initiating', 'pending'):
        return None
    age = max(0, int((timezone.now() - attempt.created_at).total_seconds()))
    if age < 30:
        return 5
    if age < 120:
        return 10
    if age < 300:
        return 20
    return 30


def retry_after(attempt):
    if attempt.status == 'manual_review':
        return 60
    return None
