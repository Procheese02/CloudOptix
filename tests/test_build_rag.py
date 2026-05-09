import tempfile
import unittest
from pathlib import Path

import build_rag


class BuildRagTests(unittest.TestCase):
    def test_pricing_documents_include_metadata_tags(self):
        pricing_data = {
            "metadata": {
                "category": "compute",
                "scope": "ec2",
                "action": "downsizing",
                "region": "us-east-1",
                "currency": "USD",
            },
            "instance_types": {
                "t3.large": {
                    "vcpu": 2,
                    "memory_gib": 8,
                    "hourly_price": 0.0832,
                    "monthly_estimate": 60.0,
                }
            },
            "downgrade_rules": [
                {
                    "name": "test_rule",
                    "avg_cpu_below_percent": 10,
                    "peak_cpu_at_or_below_percent": 30,
                    "avg_memory_below_percent": 20,
                    "recommendation": "downsize",
                    "downgrade_steps": 2,
                    "instance_order": ["t3.micro", "t3.large"],
                }
            ],
            "constraints": [{"name": "test_constraint", "description": "manual review"}],
        }

        documents = build_rag.build_pricing_documents(pricing_data)

        self.assertEqual(len(documents), 3)
        self.assertTrue(all(document.metadata["category"] == "compute" for document in documents))
        self.assertTrue(all(document.metadata["scope"] == "ec2" for document in documents))
        self.assertTrue(all(document.metadata["action"] == "downsizing" for document in documents))
        self.assertEqual(documents[0].metadata["chunk_type"], "instance_pricing")

    def test_markdown_fallback_loads_documents_when_json_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            missing_json = Path(tmpdir) / "missing.json"
            documents = build_rag.load_pricing_documents(missing_json)

        self.assertGreater(len(documents), 0)


if __name__ == "__main__":
    unittest.main()
