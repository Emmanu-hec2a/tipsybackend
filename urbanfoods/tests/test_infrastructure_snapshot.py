from django.test import TestCase

from urbanfoods.observability import infrastructure_snapshot


class InfrastructureSnapshotTest(TestCase):
    def test_snapshot_is_safe_and_reports_capacity_configuration(self):
        snapshot = infrastructure_snapshot()
        self.assertIn(snapshot['database']['vendor'], ('sqlite', 'postgresql'))
        self.assertEqual(snapshot['payment_queues'], [
            'payment_initiation', 'payment_reconciliation', 'payment_notifications'
        ])
        self.assertIn('celery_worker_concurrency', snapshot)
        self.assertNotIn('DATABASE_URL', str(snapshot))
