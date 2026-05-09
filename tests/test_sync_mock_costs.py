import tempfile
import unittest
from pathlib import Path

import sync_mock_costs


class SyncMockCostsTests(unittest.TestCase):
    def test_sync_full_month_instance_costs(self):
        billing_data = {
            "instances": [
                {"instance_id": "i-one", "instance_type": "t3.large", "monthly_cost": 61.32}
            ]
        }
        pricing_data = {
            "metadata": {"name": "pricing", "region": "us-east-1"},
            "instance_types": {"t3.large": {"monthly_estimate": 60.74}},
        }

        synced, summary = sync_mock_costs.sync_billing_costs(billing_data, pricing_data)

        self.assertEqual(synced["instances"][0]["monthly_cost"], 60.74)
        self.assertEqual(summary["updated_instance_count"], 1)
        self.assertEqual(synced["cost_sync"]["pricing_region"], "us-east-1")

    def test_sync_temporary_instance_preserves_partial_month_ratio(self):
        billing_data = {
            "instances": [
                {"instance_id": "i-full", "instance_type": "t3.xlarge", "monthly_cost": 122.64},
                {"instance_id": "i-temp", "instance_type": "t3.xlarge", "monthly_cost": 30.66, "temporary": True},
            ]
        }
        pricing_data = {"instance_types": {"t3.xlarge": {"monthly_estimate": 121.47}}}

        synced, _ = sync_mock_costs.sync_billing_costs(billing_data, pricing_data)

        self.assertEqual(synced["instances"][0]["monthly_cost"], 121.47)
        self.assertEqual(synced["instances"][1]["monthly_cost"], 30.37)

    def test_unknown_instance_type_is_unchanged_and_reported(self):
        billing_data = {
            "instances": [
                {"instance_id": "i-unknown", "instance_type": "m7g.large", "monthly_cost": 70.0}
            ]
        }
        pricing_data = {"instance_types": {"t3.large": {"monthly_estimate": 60.74}}}

        synced, summary = sync_mock_costs.sync_billing_costs(billing_data, pricing_data)

        self.assertEqual(synced["instances"][0]["monthly_cost"], 70.0)
        self.assertEqual(summary["unchanged_instance_types"], ["m7g.large"])

    def test_write_json_creates_output_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "billing.json"
            sync_mock_costs.write_json({"instances": []}, output_path)

            self.assertTrue(output_path.exists())
            self.assertIn('"instances"', output_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
