from rest_framework.throttling import SimpleRateThrottle


class PaymentAttemptThrottle(SimpleRateThrottle):
    scope = 'payment_status_per_payment'

    def get_cache_key(self, request, view):
        payment_id = view.kwargs.get('payment_id') or view.kwargs.get('pk')
        if not payment_id or not request.user.is_authenticated:
            return None
        return self.cache_format % {
            'scope': self.scope,
            'ident': f'{request.user.pk}:{payment_id}',
        }
