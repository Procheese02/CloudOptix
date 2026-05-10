import unittest
from datetime import UTC, datetime

import fetch_cloudwatch_metrics
import fetch_cost_explorer


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

        enriched = fetch_cloudwatch_metrics.enrich_instance(instance, metadata, metrics, 30.0)

        self.assertEqual(enriched["instance_type"], "t3.large")
        self.assertEqual(enriched["owner"], "platform-team")
        self.assertEqual(enriched["monthly_cost"], 30.0)
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

    def test_enrich_billing_data_expands_cost_groups_to_ec2_instances(self):
        billing_data = {
            "source": {"name": "aws_cost_explorer"},
            "instances": [
                {
                    "instance_id": "cost-group-us-east-1-t3.large",
                    "instance_type": "t3.large",
                    "monthly_cost": 60.0,
                    "cost_group": {"instance_type": "t3.large", "region": "us-east-1"},
                    "metrics": {},
                }
            ],
        }
        metadata = {
            "i-one": {"instance_type": "t3.large", "owner": "platform-team"},
            "i-two": {"instance_type": "t3.large", "owner": "api-team"},
        }
        start = datetime(2026, 5, 1, tzinfo=UTC)
        end = datetime(2026, 5, 10, tzinfo=UTC)

        enriched = fetch_cloudwatch_metrics.enrich_billing_data(
            billing_data,
            metadata,
            {"i-one": {"avg_cpu_utilization": "20.00%"}, "i-two": {"avg_cpu_utilization": "30.00%"}},
            "us-east-1",
            start,
            end,
        )

        self.assertEqual([instance["instance_id"] for instance in enriched["instances"]], ["i-one", "i-two"])
        self.assertEqual([instance["monthly_cost"] for instance in enriched["instances"]], [30.0, 30.0])
        self.assertEqual(enriched["source"]["name"], "aws_cost_explorer_cloudwatch_enriched")
        self.assertEqual(enriched["source"]["base_source"], "aws_cost_explorer")
        self.assertEqual(enriched["source"]["time_period"], {"start": "2026-05-01", "end": "2026-05-10"})

    def test_enrich_billing_data_expands_empty_cost_explorer_to_ec2_instances(self):
        billing_data = {
            "source": {"name": "aws_cost_explorer"},
            "instances": [],
        }
        metadata = {
            "i-new": {"instance_type": "t3.micro", "owner": "platform-team"},
        }
        start = datetime(2026, 5, 1, tzinfo=UTC)
        end = datetime(2026, 5, 10, tzinfo=UTC)

        enriched = fetch_cloudwatch_metrics.enrich_billing_data(
            billing_data,
            metadata,
            {"i-new": {"avg_cpu_utilization": "5.00%"}},
            "us-east-1",
            start,
            end,
        )

        self.assertEqual([instance["instance_id"] for instance in enriched["instances"]], ["i-new"])
        self.assertEqual(enriched["instances"][0]["monthly_cost"], 0.0)
        self.assertEqual(enriched["instances"][0]["cost_allocation"], "missing_cost_explorer_data")
        self.assertIn("returned no EC2 cost records", enriched["source"]["cost_allocation_note"])

    def test_result_values_extracts_metric_values_by_id(self):
        values = fetch_cloudwatch_metrics.result_values([
            {"Id": "cpu_avg", "Values": [1, 2.5]},
            {"Id": "network_in", "Values": []},
        ])

        self.assertEqual(values["cpu_avg"], [1.0, 2.5])
        self.assertEqual(values["network_in"], [])

    def test_cost_explorer_builds_supported_instance_type_region_group(self):
        group = {
            "Keys": ["t3.large", "US East (N. Virginia)"],
            "Metrics": {"UnblendedCost": {"Amount": "61.25"}},
        }

        instance = fetch_cost_explorer.build_instance(group)

        self.assertEqual(instance["instance_id"], "cost-group-US East (N. Virginia)-t3.large")
        self.assertEqual(instance["cost_group"], {
            "group_by": ["INSTANCE_TYPE", "REGION"],
            "instance_type": "t3.large",
            "region": "US East (N. Virginia)",
        })


if __name__ == "__main__":
    unittest.main()
