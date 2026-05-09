import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import tool


class ToolPlanningTests(unittest.TestCase):
    def test_get_target_instance_type_downgrades_two_steps(self):
        self.assertEqual(tool.get_target_instance_type("t3.2xlarge"), "t3.large")
        self.assertEqual(tool.get_target_instance_type("t3.xlarge"), "t3.medium")

    def test_get_target_instance_type_rejects_minimum_size(self):
        with self.assertRaises(ValueError):
            tool.get_target_instance_type("t3.micro")

    def test_is_execution_candidate_requires_low_utilization_and_unprotected(self):
        instance = {
            "metrics": {
                "avg_cpu_utilization": "6.0%",
                "peak_cpu_utilization": "20.0%",
                "avg_memory_utilization": "15.0%",
            }
        }

        self.assertTrue(tool.is_execution_candidate(instance))

        protected_instance = {**instance, "protected": True}
        self.assertFalse(tool.is_execution_candidate(protected_instance))

        healthy_instance = {
            "metrics": {
                "avg_cpu_utilization": "35.0%",
                "peak_cpu_utilization": "70.0%",
                "avg_memory_utilization": "50.0%",
            }
        }
        self.assertFalse(tool.is_execution_candidate(healthy_instance))

    def test_build_action_result_generates_multiple_dry_run_plans_and_skips_micro(self):
        billing_data = {
            "instances": [
                {
                    "instance_id": "i-large",
                    "instance_type": "t3.2xlarge",
                    "metrics": {
                        "avg_cpu_utilization": "6.0%",
                        "peak_cpu_utilization": "20.0%",
                        "avg_memory_utilization": "15.0%",
                    },
                },
                {
                    "instance_id": "i-staging",
                    "instance_type": "t3.xlarge",
                    "metrics": {
                        "avg_cpu_utilization": "8.0%",
                        "peak_cpu_utilization": "25.0%",
                        "avg_memory_utilization": "17.0%",
                    },
                },
                {
                    "instance_id": "i-protected",
                    "instance_type": "t3.large",
                    "protected": True,
                    "metrics": {
                        "avg_cpu_utilization": "5.0%",
                        "peak_cpu_utilization": "18.0%",
                        "avg_memory_utilization": "12.0%",
                    },
                },
                {
                    "instance_id": "i-micro",
                    "instance_type": "t3.micro",
                    "metrics": {
                        "avg_cpu_utilization": "4.0%",
                        "peak_cpu_utilization": "12.0%",
                        "avg_memory_utilization": "10.0%",
                    },
                },
            ]
        }

        output = io.StringIO()
        with redirect_stdout(output):
            result = tool.build_action_result(billing_data, execute=False)

        self.assertIn("would downgrade i-large from t3.2xlarge to t3.large", result)
        self.assertIn("would downgrade i-staging from t3.xlarge to t3.medium", result)
        self.assertIn("Skipped: i-micro 无法自动降级", result)
        self.assertNotIn("i-protected", result)
        self.assertEqual(output.getvalue().count("AWS Action Plan"), 2)

    def test_execute_mode_invokes_tool_for_each_candidate(self):
        billing_data = {
            "instances": [
                {
                    "instance_id": "i-one",
                    "instance_type": "t3.large",
                    "metrics": {
                        "avg_cpu_utilization": "5.0%",
                        "peak_cpu_utilization": "20.0%",
                        "avg_memory_utilization": "12.0%",
                    },
                }
            ]
        }

        class FakeDowngradeTool:
            def __init__(self):
                self.calls = []

            def invoke(self, payload):
                self.calls.append(payload)
                return "executed"

        fake_tool = FakeDowngradeTool()
        with patch("tool.execute_aws_downgrade", fake_tool):
            result = tool.build_action_result(billing_data, execute=True)

        self.assertEqual(result, "executed")
        self.assertEqual(fake_tool.calls, [{"instance_id": "i-one", "target_type": "t3.small"}])


if __name__ == "__main__":
    unittest.main()
