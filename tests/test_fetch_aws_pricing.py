import json
import unittest

import fetch_aws_pricing


class FakePaginator:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def paginate(self, **kwargs):
        self.calls.append(kwargs)
        return self.pages


class FakeClient:
    def __init__(self, paginators):
        self.paginators = paginators

    def get_paginator(self, name):
        return self.paginators[name]


class FetchAwsPricingTests(unittest.TestCase):
    def test_region_location_fallback(self):
        self.assertEqual(fetch_aws_pricing.region_to_location("us-east-1"), "US East (N. Virginia)")
        self.assertEqual(fetch_aws_pricing.region_to_location("unknown-region"), "unknown-region")

    def test_fetch_region_location_uses_matching_attribute_value(self):
        paginator = FakePaginator([
            {"AttributeValues": [{"Value": "US East (N. Virginia)"}]}
        ])
        client = FakeClient({"get_attribute_values": paginator})

        location = fetch_aws_pricing.fetch_region_location(client, "us-east-1")

        self.assertEqual(location, "US East (N. Virginia)")
        self.assertEqual(paginator.calls[0]["ServiceCode"], "AmazonEC2")

    def test_parse_product_price_extracts_hourly_and_monthly_values(self):
        price_item = json.dumps({
            "product": {
                "attributes": {
                    "vcpu": "2",
                    "memory": "8 GiB",
                }
            },
            "terms": {
                "OnDemand": {
                    "term": {
                        "priceDimensions": {
                            "dimension": {"pricePerUnit": {"USD": "0.0832000000"}}
                        }
                    }
                }
            },
        })

        parsed = fetch_aws_pricing.parse_product_price(price_item)

        self.assertEqual(parsed["vcpu"], 2)
        self.assertEqual(parsed["memory_gib"], 8.0)
        self.assertEqual(parsed["hourly_price"], 0.0832)
        self.assertEqual(parsed["monthly_estimate"], 60.74)

    def test_build_pricing_data_preserves_rules_and_constraints(self):
        existing = {
            "downgrade_rules": [{"name": "keep-rule"}],
            "constraints": [{"name": "keep-constraint"}],
        }
        instance_types = {"t3.large": {"vcpu": 2, "memory_gib": 8, "hourly_price": 0.0832, "monthly_estimate": 60.74}}

        data = fetch_aws_pricing.build_pricing_data(existing, "us-east-1", "us-east-1", instance_types)

        self.assertEqual(data["instance_types"], instance_types)
        self.assertEqual(data["downgrade_rules"], existing["downgrade_rules"])
        self.assertEqual(data["constraints"], existing["constraints"])
        self.assertEqual(data["metadata"]["source"]["name"], "aws_pricing_api")

    def test_fetch_instance_price_uses_pricing_filters(self):
        price_item = json.dumps({
            "product": {"attributes": {"vcpu": "4", "memory": "16 GiB"}},
            "terms": {"OnDemand": {"term": {"priceDimensions": {"dimension": {"pricePerUnit": {"USD": "0.1664000000"}}}}}},
        })
        paginator = FakePaginator([{"PriceList": [price_item]}])
        client = FakeClient({"get_products": paginator})

        price = fetch_aws_pricing.fetch_instance_price(client, "t3.xlarge", "US East (N. Virginia)")

        self.assertEqual(price["hourly_price"], 0.1664)
        filters = paginator.calls[0]["Filters"]
        self.assertIn({"Type": "TERM_MATCH", "Field": "instanceType", "Value": "t3.xlarge"}, filters)


if __name__ == "__main__":
    unittest.main()
