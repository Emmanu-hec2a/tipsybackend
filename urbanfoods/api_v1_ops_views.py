from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from .observability import database_snapshot, infrastructure_snapshot, metric_snapshot
from .permissions import IsSuperAdmin


class PaymentMetricsView(APIView):
    """Restricted operational snapshot for Railway dashboards and operators."""

    permission_classes = [permissions.IsAuthenticated, IsSuperAdmin]

    def get(self, request):
        return Response({
            'metrics': metric_snapshot(),
            'database': database_snapshot(),
            'infrastructure': infrastructure_snapshot(),
        })
