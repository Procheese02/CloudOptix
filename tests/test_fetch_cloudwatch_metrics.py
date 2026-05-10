import unittest
from datetime import UTC, datetime

import fetch_cloudwatch_metrics


class FetchCloudWatchMetricsTests(unittest.TestCase):
    def test_enrich_instance_adds_tags_and_cloudwatch_metrics(self):
        instance = {
            "instance_id": "i-one",
            "instance_type": "unknown",
            "monthly_cost": 42.0,
            "metrics": {"avg_memory_utilization": "100.00%"},
            "protected": True,
        }
        metadata = {
            "i-one": {
                "instance_type": "t3.large",
                "environment": "production",
                "owner": "platform-team",
                "workload": "api",
                "tags": {"Environment": "production", "Owner": "platform-team"},
            }
        }
        metrics = {
            "avg_cpu_utilization": "8.50%",
            "peak_cpu_utilization": "25.00%",
            "avg_network_in_bytes": 1024.0,
        }

        enriched = fetch_cloudwatch_metrics.enrich_instance(instance, metadata, metrics)

        self.assertEqual(enriched["instance_type"], "t3.large")
        self.assertEqual(enriched["owner"], "platform-team")
        self.assertEqual(enriched["metrics"]["avg_cpu_utilization"], "8.50%")
        self.assertTrue(enriched["protected"])
        self.assertIn("CloudWatch default EC2 metrics", enriched["do_not_touch_reason"])

    def test_enrich_instance_protects_when_cloudwatch_has_no_cpu_data(self):
        enriched = fetch_cloudwatch_metrics.enrich_instance(
            {"instance_id": "i-missing", "metrics": {}},
            {},
            {},
        )

        self.assertTrue(enriched["protected"])
        self.assertEqual(enriched["metrics"]["avg_memory_utilization"], "100.00%")
        self.assertIn("no CPU utilization", enriched["do_not_touch_reason"])

    def test_enrich_billing_data_records_source_metadata(self):
        billing_data = {
            "source": {"name": "aws_cost_explorer"},
            "instances": [{"instance_id": "i-one", "metrics": {}}],
        }
        start = datetime(2026, 5, 1, tzinfo=UTC)
        end = datetime(2026, 5, 10, tzinfo=UTC)

        enriched = fetch_cloudwatch_metrics.enrich_billing_data(
            billing_data,
            {},
            {"i-one": {"avg_cpu_utilization": "20.00%"}},
            "us-east-1",
            start,
            end,
        )

        self.assertEqual(enriched["source"]["name"], "aws_cost_explorer_cloudwatch_enriched")
        self.assertEqual(enriched["source"]["base_source"], "aws_cost_explorer")
        self.assertEqual(enriched["source"]["time_period"], {"start": "2026-05-01", "end": "2026-05-10"})

    def test_result_values_extracts_metric_values_by_id(self):
        values = fetch_cloudwatch_metrics.result_values([
            {"Id": "cpu_avg", "Values": [1, 2.5]},
            {"Id": "network_in", "Values": []},
        ])

        self.assertEqual(values["cpu_avg"], [1.0, 2.5])
        self.assertEqual(values["network_in"], [])


if __name__ == "__main__":
    unittest.main()
