import tempfile
import unittest
from pathlib import Path

from sqlalchemy import select

import analyze_billing
import generate_mock
import persistence


class PersistenceTests(unittest.TestCase):
    def make_session(self):
        tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(tmpdir.name) / "cloudoptix-test.db"
        engine = persistence.make_engine(db_path)
        persistence.create_schema(engine)
        SessionLocal = persistence.session_factory(engine)
        session = SessionLocal()
        self.addCleanup(session.close)
        self.addCleanup(tmpdir.cleanup)
        return session

    def persist(self, session, billing_data):
        analysis = analyze_billing.analyze_billing_data(billing_data)
        return persistence.persist_scan(session, billing_data, analysis)

    def test_persist_mock_scan_writes_snapshot_tables(self):
        session = self.make_session()
        billing_data = generate_mock.generate_billing_data(fleet_size=30, seed=42, autoscale_count=2)

        scan = self.persist(session, billing_data)
        counts = persistence.scan_counts(session, scan.id)

        self.assertEqual(scan.report_id, "BILL-2026-05-MOCK-FLEET-V2")
        self.assertEqual(scan.fleet_size, 32)
        self.assertEqual(counts["instances"], 32)
        self.assertEqual(counts["metrics"], 32)
        self.assertGreater(counts["recommendations"], 0)
        self.assertEqual(counts["recommendations"], counts["action_plans"])
        self.assertEqual(counts["approvals"], 0)

    def test_persist_same_report_id_is_idempotent(self):
        session = self.make_session()
        billing_data = generate_mock.generate_billing_data(fleet_size=20, seed=42, autoscale_count=1)

        first_scan = self.persist(session, billing_data)
        second_scan = self.persist(session, billing_data)
        counts = persistence.scan_counts(session, second_scan.id)
        scan_count = session.scalar(select(persistence.func.count()).select_from(persistence.Scan))

        self.assertEqual(second_scan.report_id, first_scan.report_id)
        self.assertEqual(scan_count, 1)
        self.assertEqual(counts["instances"], 21)
        self.assertEqual(counts["metrics"], 21)

    def test_same_instance_id_can_exist_in_different_scans(self):
        session = self.make_session()
        first = generate_mock.generate_billing_data(fleet_size=3, seed=1, autoscale_count=0)
        second = generate_mock.generate_billing_data(fleet_size=3, seed=2, autoscale_count=0)
        second["report_id"] = "BILL-SECOND-SCAN"

        first_scan = self.persist(session, first)
        second_scan = self.persist(session, second)

        first_instance_count = session.scalar(
            select(persistence.func.count())
            .select_from(persistence.InstanceSnapshot)
            .where(persistence.InstanceSnapshot.scan_id == first_scan.id)
        )
        second_instance_count = session.scalar(
            select(persistence.func.count())
            .select_from(persistence.InstanceSnapshot)
            .where(persistence.InstanceSnapshot.scan_id == second_scan.id)
        )

        self.assertEqual(first_instance_count, 3)
        self.assertEqual(second_instance_count, 3)

    def test_missing_metrics_are_persisted_as_incomplete(self):
        session = self.make_session()
        billing_data = {
            "report_id": "BILL-MISSING-METRICS",
            "resource_type": "AWS EC2",
            "region": "us-east-1",
            "instances": [
                {
                    "instance_id": "i-missing",
                    "instance_type": "t3.xlarge",
                    "monthly_cost": 122.64,
                    "owner": "platform-team",
                    "business_unit": "platform",
                    "service": "api",
                    "environment": "dev",
                    "criticality": "medium",
                    "region": "us-east-1",
                    "pricing_model": "on_demand",
                    "utilization_pattern": "missing_metrics",
                    "metrics_source": "missing",
                    "metrics": {},
                    "protected": True,
                    "do_not_touch_reason": "missing utilization metrics require manual review",
                }
            ],
        }

        scan = self.persist(session, billing_data)
        metric = session.scalar(select(persistence.MetricSnapshot).where(persistence.MetricSnapshot.scan_id == scan.id))
        counts = persistence.scan_counts(session, scan.id)

        self.assertFalse(metric.has_complete_metrics)
        self.assertEqual(metric.metrics_source, "missing")
        self.assertEqual(counts["recommendations"], 0)
        self.assertEqual(scan.missing_metrics_count, 1)

    def test_cost_explorer_scan_does_not_create_automatic_actions(self):
        session = self.make_session()
        billing_data = {
            "report_id": "BILL-COST-EXPLORER",
            "resource_type": "AWS EC2",
            "region": "all",
            "source": {"name": "aws_cost_explorer"},
            "instances": [
                {
                    "instance_id": "i-cost-only",
                    "instance_type": "t3.2xlarge",
                    "monthly_cost": 245.28,
                    "owner": "unknown",
                    "business_unit": "unknown",
                    "service": "unknown",
                    "environment": "unknown",
                    "criticality": "unknown",
                    "region": "all",
                    "pricing_model": "unknown",
                    "utilization_pattern": "missing_metrics",
                    "protected": True,
                    "metrics": {
                        "avg_cpu_utilization": "4%",
                        "peak_cpu_utilization": "15%",
                        "avg_memory_utilization": "10%",
                    },
                }
            ],
        }

        scan = self.persist(session, billing_data)
        counts = persistence.scan_counts(session, scan.id)

        self.assertEqual(scan.source, "aws_cost_explorer")
        self.assertEqual(counts["recommendations"], 0)
        self.assertEqual(counts["action_plans"], 0)


if __name__ == "__main__":
    unittest.main()
