import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import generate_mock
import tool


class GenerateMockTests(unittest.TestCase):
    def test_generate_billing_data_has_expected_schema_and_fleet_size(self):
        data = generate_mock.generate_billing_data(fleet_size=60, seed=42, autoscale_count=4)

        self.assertEqual(data["resource_type"], "AWS EC2")
        self.assertEqual(data["region"], "us-east-1")
        self.assertEqual(len(data["instances"]), 64)
        self.assertEqual(data["simulation"]["base_fleet_size"], 60)

        first_instance = data["instances"][0]
        self.assertIn("instance_id", first_instance)
        self.assertIn("instance_type", first_instance)
        self.assertIn("monthly_cost", first_instance)
        self.assertIn("environment", first_instance)
        self.assertIn("owner", first_instance)
        self.assertIn("metrics", first_instance)
        self.assertIn("avg_cpu_utilization", first_instance["metrics"])
        self.assertIn("peak_cpu_utilization", first_instance["metrics"])
        self.assertIn("avg_memory_utilization", first_instance["metrics"])

    def test_same_seed_generates_identical_data(self):
        first = generate_mock.generate_billing_data(fleet_size=60, seed=99, autoscale_count=4)
        second = generate_mock.generate_billing_data(fleet_size=60, seed=99, autoscale_count=4)

        self.assertEqual(first, second)

    def test_autoscaling_instances_can_be_forced(self):
        data = generate_mock.generate_billing_data(fleet_size=50, seed=42, autoscale_count=6)
        temporary_instances = [instance for instance in data["instances"] if instance.get("temporary")]

        self.assertEqual(len(temporary_instances), 6)
        self.assertTrue(all("autoscaling_group" in instance for instance in temporary_instances))

    def test_generated_data_is_compatible_with_tool_planning(self):
        data = generate_mock.generate_billing_data(fleet_size=60, seed=42, autoscale_count=4)
        instances = tool.get_instances(data)
        candidates = [instance for instance in instances if tool.is_execution_candidate(instance)]

        self.assertGreaterEqual(len(instances), 50)
        self.assertGreater(len(candidates), 0)

        output = io.StringIO()
        with redirect_stdout(output):
            result = tool.build_action_result(data, execute=False)

        self.assertIn("Dry run: would downgrade", result)
        self.assertIn("AWS Action Plan", output.getvalue())

    def test_write_billing_data_creates_json_file(self):
        data = generate_mock.generate_billing_data(fleet_size=3, seed=7, autoscale_count=1)

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "mock_billing.json"
            generate_mock.write_billing_data(data, output_path)

            self.assertTrue(output_path.exists())
            self.assertIn('"instances"', output_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
