import os
import random
import time

from django.core.cache import cache


class PaymentBackpressure:
    """Redis-backed admission and circuit-breaker controls for provider calls."""

    RATE_WINDOW_SECONDS = 60
    FAILURE_WINDOW_SECONDS = 60

    @classmethod
    def _int_env(cls, name, default):
        try:
            return max(1, int(os.environ.get(name, default)))
        except (TypeError, ValueError):
            return default

    @classmethod
    def provider_rate_limit(cls):
        return cls._int_env('MPESA_INITIATION_RATE_PER_MINUTE', 300)

    @classmethod
    def queue_limit(cls):
        return cls._int_env('PAYMENT_INITIATION_QUEUE_LIMIT', 1000)

    @classmethod
    def failure_threshold(cls):
        return cls._int_env('MPESA_CIRCUIT_FAILURE_THRESHOLD', 5)

    @classmethod
    def circuit_timeout(cls):
        return cls._int_env('MPESA_CIRCUIT_OPEN_SECONDS', 60)

    @classmethod
    def _cache_incr(cls, key, timeout):
        try:
            if cache.add(key, 0, timeout=timeout):
                return 0
            return cache.incr(key)
        except Exception:
            # Payment admission must fail open if Redis is unavailable; the
            # database and provider attempt lock remain the safety boundary.
            return 0

    @classmethod
    def circuit_open(cls):
        try:
            return bool(cache.get('tipsy:mpesa:circuit:open'))
        except Exception:
            return False

    @classmethod
    def admit_provider_call(cls, attempt_id):
        if cls.circuit_open():
            return False, 'provider_circuit_open'

        from .models import PaymentAttempt
        queued = PaymentAttempt.objects.filter(
            status__in=[PaymentAttempt.Status.PENDING, PaymentAttempt.Status.INITIATING],
            checkout_request_id__isnull=True,
        ).count()
        if queued > cls.queue_limit():
            return False, 'provider_queue_full'

        window = int(time.time()) // cls.RATE_WINDOW_SECONDS
        count = cls._cache_incr(f'tipsy:mpesa:rate:{window}', timeout=120) + 1
        if count > cls.provider_rate_limit():
            return False, 'provider_rate_limited'
        return True, None

    @classmethod
    def record_provider_result(cls, result):
        if result and result.get('success'):
            try:
                cache.delete('tipsy:mpesa:circuit:failures')
            except Exception:
                pass
            return
        message = str((result or {}).get('message', '')).lower()
        if not any(token in message for token in ('unavailable', 'timeout', 'timed out', 'provider')):
            return
        failures = cls._cache_incr(
            'tipsy:mpesa:circuit:failures', cls.FAILURE_WINDOW_SECONDS
        ) + 1
        if failures >= cls.failure_threshold():
            try:
                cache.set('tipsy:mpesa:circuit:open', True, timeout=cls.circuit_timeout())
            except Exception:
                pass

    @staticmethod
    def retry_delay(retries, base=5, maximum=120):
        exponential = min(maximum, base * (2 ** min(retries, 5)))
        return exponential + random.uniform(0, max(1, exponential * 0.25))
