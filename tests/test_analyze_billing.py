import unittest

import analyze_billing
import generate_mock


class AnalyzeBillingTests(unittest.TestCase):
    def test_histogram_and_instance_type_aggregation(self):
        data = generate_mock.generate_billing_data(fleet_size=60, seed=42, autoscale_count=4)
        analysis = analyze_billing.analyze_billing_data(data)
        complete_metric_count = sum(
            1 for instance in data["instances"] if analyze_billing.has_complete_metrics(instance)
        )

        self.assertEqual(analysis["fleet_size"], 64)
        self.assertEqual(sum(bucket["count"] for bucket in analysis["cpu_distribution"]), complete_metric_count)
        self.assertTrue(any(row["instance_type"] == "t3.2xlarge" for row in analysis["instance_type_aggregation"]))

    def test_cost_share_sums_to_one(self):
        data = generate_mock.generate_billing_data(fleet_size=12, seed=11, autoscale_count=2)
        shares = analyze_billing.cost_share_by_instance(data["instances"])

        self.assertAlmostEqual(sum(item["cost_share"] for item in shares), 1.0, places=5)
        self.assertGreaterEqual(shares[0]["cost_share"], shares[-1]["cost_share"])

    def test_detects_high_cost_low_utilization_anomaly(self):
        instances = [
            {
                "instance_id": "i-small",
                "instance_type": "t3.small",
                "monthly_cost": 15.0,
                "metrics": {
                    "avg_cpu_utilization": "35%",
                    "peak_cpu_utilization": "65%",
                    "avg_memory_utilization": "50%",
                },
            },
            {
                "instance_id": "i-medium",
                "instance_type": "t3.medium",
                "monthly_cost": 30.0,
                "metrics": {
                    "avg_cpu_utilization": "40%",
                    "peak_cpu_utilization": "70%",
                    "avg_memory_utilization": "55%",
                },
            },
            {
                "instance_id": "i-waste",
                "instance_type": "t3.2xlarge",
                "monthly_cost": 245.28,
                "metrics": {
                    "avg_cpu_utilization": "4%",
                    "peak_cpu_utilization": "12%",
                    "avg_memory_utilization": "10%",
                },
            },
        ]

        anomalies = analyze_billing.detect_anomalies(instances)

        self.assertEqual(anomalies[0]["instance_id"], "i-waste")

    def test_data_quality_flags_missing_fields_and_partial_metrics(self):
        billing_data = {
            "generated_at": "not-a-timestamp",
            "instances": [
                {
                    "instance_id": "i-complete",
                    "instance_type": "t3.large",
                    "monthly_cost": 60.0,
                    "metrics": {
                        "avg_cpu_utilization": "20%",
                        "peak_cpu_utilization": "50%",
                        "avg_memory_utilization": "40%",
                    },
                },
                {"instance_id": "i-missing", "instance_type": "t3.large", "monthly_cost": 60.0},
            ],
        }

        quality = analyze_billing.data_quality_checks(billing_data, billing_data["instances"])

        self.assertTrue(quality["partial_cloudwatch_coverage"])
        self.assertLess(quality["cloudwatch_metric_coverage"], 1.0)
        self.assertTrue(any(item["field"] == "metrics" for item in quality["missing_fields"]))
        self.assertTrue(any(item.get("field") == "generated_at" for item in quality["timestamp_issues"]))

    def test_enterprise_summary_groups_cost_and_large_fleet(self):
        data = generate_mock.generate_billing_data(fleet_size=500, seed=42, autoscale_count=4)
        analysis = analyze_billing.analyze_billing_data(data)
        summary = analysis["enterprise_summary"]

        total_cost = round(sum(float(instance["monthly_cost"]) for instance in data["instances"]), 2)
        business_unit_cost = round(sum(row["total_monthly_cost"] for row in summary["cost_by_business_unit"]), 2)

        self.assertEqual(analysis["fleet_size"], 504)
        self.assertAlmostEqual(business_unit_cost, total_cost, places=2)
        self.assertTrue(summary["cost_by_team_service_environment"])
        self.assertTrue(summary["cost_by_service"])
        self.assertTrue(summary["cost_by_region"])
        self.assertTrue(summary["cost_by_pricing_model"])
        self.assertTrue(summary["utilization_pattern_summary"])
        self.assertGreater(summary["missing_metrics_coverage"]["missing_metrics_count"], 0)
        self.assertGreater(summary["enterprise_savings_summary"]["eligible_candidate_count"], 0)
        self.assertTrue(summary["top_waste_owners"])

    def test_enterprise_summary_excludes_protected_and_minimum_size_from_savings(self):
        billing_data = {
            "instances": [
                {
                    "instance_id": "i-eligible",
                    "instance_type": "t3.xlarge",
                    "monthly_cost": 122.64,
                    "owner": "platform-team",
                    "business_unit": "platform",
                    "service": "api",
                    "environment": "dev",
                    "criticality": "low",
                    "region": "us-east-1",
                    "pricing_model": "on_demand",
                    "utilization_pattern": "idle",
                    "metrics": {
                        "avg_cpu_utilization": "4%",
                        "peak_cpu_utilization": "15%",
                        "avg_memory_utilization": "10%",
                    },
                },
                {
                    "instance_id": "i-protected",
                    "instance_type": "t3.2xlarge",
                    "monthly_cost": 245.28,
                    "owner": "checkout-team",
                    "business_unit": "commerce",
                    "service": "checkout",
                    "environment": "production",
                    "criticality": "critical",
                    "region": "us-east-1",
                    "pricing_model": "on_demand",
                    "utilization_pattern": "idle",
                    "protected": True,
                    "do_not_touch_reason": "critical production workload requires architecture review",
                    "metrics": {
                        "avg_cpu_utilization": "4%",
                        "peak_cpu_utilization": "15%",
                        "avg_memory_utilization": "10%",
                    },
                },
                {
                    "instance_id": "i-micro",
                    "instance_type": "t3.micro",
                    "monthly_cost": 7.67,
                    "owner": "data-team",
                    "business_unit": "data",
                    "service": "etl",
                    "environment": "dev",
                    "criticality": "low",
                    "region": "us-east-1",
                    "pricing_model": "on_demand",
                    "utilization_pattern": "idle",
                    "metrics": {
                        "avg_cpu_utilization": "4%",
                        "peak_cpu_utilization": "15%",
                        "avg_memory_utilization": "10%",
                    },
                },
            ]
        }

        summary = analyze_billing.enterprise_summary(billing_data, billing_data["instances"])
        savings = summary["enterprise_savings_summary"]

        self.assertEqual(savings["eligible_candidate_count"], 1)
        self.assertEqual(savings["protected_low_utilization_count"], 1)
        self.assertEqual(savings["estimated_monthly_savings"], 91.98)
        self.assertEqual(summary["top_waste_owners"][0]["owner"], "platform-team")
        self.assertEqual(summary["protected_resources_summary"][0]["owner"], "checkout-team")

    def test_cost_explorer_source_gets_no_automatic_savings(self):
        billing_data = {
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

        summary = analyze_billing.enterprise_summary(billing_data, billing_data["instances"])

        self.assertEqual(summary["enterprise_savings_summary"]["eligible_candidate_count"], 0)
        self.assertEqual(summary["enterprise_savings_summary"]["estimated_monthly_savings"], 0)

    def test_missing_enterprise_fields_fall_back_to_unknown(self):
        billing_data = {
            "instances": [
                {
                    "instance_id": "i-legacy",
                    "instance_type": "t3.large",
                    "monthly_cost": "61.32",
                    "metrics": {
                        "avg_cpu_utilization": "50%",
                        "peak_cpu_utilization": "80%",
                        "avg_memory_utilization": "60%",
                    },
                }
            ]
        }

        summary = analyze_billing.enterprise_summary(billing_data, billing_data["instances"])
        first_group = summary["cost_by_team_service_environment"][0]

        self.assertEqual(first_group["owner"], "unknown")
        self.assertEqual(first_group["service"], "unknown")
        self.assertEqual(first_group["environment"], "unknown")


if __name__ == "__main__":
    unittest.main()
