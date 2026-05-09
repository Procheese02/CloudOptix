import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "data" / "aws_pricing.json"
DEFAULT_INSTANCE_TYPES = ["t3.micro", "t3.small", "t3.medium", "t3.large", "t3.xlarge", "t3.2xlarge"]
DEFAULT_DOWNGRADE_RULES = [
    {
        "name": "two_step_low_utilization_downsize",
        "category": "compute",
        "scope": "ec2",
        "action": "downsizing",
        "avg_cpu_below_percent": 10,
        "peak_cpu_at_or_below_percent": 30,
        "avg_memory_below_percent": 20,
        "recommendation": "Downgrade at least two sizes when average CPU is below 10%, peak CPU does not exceed 30%, and memory utilization is below 20%.",
        "downgrade_steps": 2,
        "instance_order": DEFAULT_INSTANCE_TYPES,
    }
]
DEFAULT_CONSTRAINTS = [
    {
        "name": "minimum_size_guardrail",
        "category": "compute",
        "scope": "ec2",
        "action": "downsizing",
        "description": "Do not recommend automatic downsizing for instances already at the minimum supported size.",
    },
    {
        "name": "protected_workload_guardrail",
        "category": "compute",
        "scope": "ec2",
        "action": "downsizing",
        "description": "Instances marked protected require manual owner review even if utilization is low.",
    },
    {
        "name": "production_manual_review",
        "category": "compute",
        "scope": "ec2",
        "action": "downsizing",
        "description": "Production workloads should be treated as medium risk and reviewed before execution.",
    },
    {
        "name": "missing_utilization_guardrail",
        "category": "compute",
        "scope": "ec2",
        "action": "downsizing",
        "description": "Do not generate automatic rightsizing recommendations when CPU or memory utilization data is missing.",
    },
    {
        "name": "cost_explorer_cost_only_guardrail",
        "category": "compute",
        "scope": "ec2",
        "action": "downsizing",
        "description": "AWS Cost Explorer exports contain cost data only and should be used for cost analysis until CloudWatch or Compute Optimizer utilization is joined.",
    },
]
REGION_LOCATION_FALLBACKS = {
    "us-east-1": "US East (N. Virginia)",
    "us-east-2": "US East (Ohio)",
    "us-west-1": "US West (N. California)",
    "us-west-2": "US West (Oregon)",
}

load_dotenv(dotenv_path=PROJECT_ROOT / ".env")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch AWS EC2 On-Demand pricing into CloudOptix structured pricing JSON.")
    parser.add_argument("--region", default="us-east-1", help="EC2 region code to price, such as us-east-1.")
    parser.add_argument(
        "--instance-types",
        default=",".join(DEFAULT_INSTANCE_TYPES),
        help="Comma-separated EC2 instance types to fetch.",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH, help="Output structured pricing JSON path.")
    parser.add_argument("--pricing-region", default="us-east-1", help="AWS Pricing API endpoint region.")
    return parser.parse_args()


def resolve_path(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


def parse_instance_types(value: str) -> list[str]:
    instance_types = [item.strip() for item in value.split(",") if item.strip()]
    if not instance_types:
        raise ValueError("--instance-types must include at least one instance type")
    return instance_types


def region_to_location(region: str) -> str:
    return REGION_LOCATION_FALLBACKS.get(region, region)


def fetch_region_location(client: Any, region: str) -> str:
    fallback = region_to_location(region)
    try:
        paginator = client.get_paginator("get_attribute_values")
        for page in paginator.paginate(ServiceCode="AmazonEC2", AttributeName="location"):
            for item in page.get("AttributeValues", []):
                location = item.get("Value", "")
                if location == fallback:
                    return location
    except (BotoCoreError, ClientError):
        return fallback
    return fallback


def pricing_filters(instance_type: str, location: str) -> list[dict[str, str]]:
    values = {
        "instanceType": instance_type,
        "location": location,
        "operatingSystem": "Linux",
        "tenancy": "Shared",
        "preInstalledSw": "NA",
        "capacitystatus": "Used",
    }
    return [{"Type": "TERM_MATCH", "Field": field, "Value": value} for field, value in values.items()]


def parse_memory_gib(value: str) -> float:
    normalized = value.replace(",", "").split()[0]
    return round(float(normalized), 2)


def parse_product_price(price_item: str) -> dict[str, Any]:
    product = json.loads(price_item)
    attributes = product.get("product", {}).get("attributes", {})
    on_demand_terms = product.get("terms", {}).get("OnDemand", {})

    for term in on_demand_terms.values():
        for dimension in term.get("priceDimensions", {}).values():
            price_per_unit = dimension.get("pricePerUnit", {})
            if "USD" not in price_per_unit:
                continue
            hourly_price = round(float(price_per_unit["USD"]), 6)
            return {
                "vcpu": int(float(attributes.get("vcpu", 0) or 0)),
                "memory_gib": parse_memory_gib(attributes.get("memory", "0 GiB")),
                "hourly_price": hourly_price,
                "monthly_estimate": round(hourly_price * 730, 2),
            }

    raise ValueError("AWS Pricing API response did not include an On-Demand USD price dimension")


def fetch_instance_price(client: Any, instance_type: str, location: str) -> dict[str, Any]:
    paginator = client.get_paginator("get_products")
    for page in paginator.paginate(ServiceCode="AmazonEC2", Filters=pricing_filters(instance_type, location)):
        for price_item in page.get("PriceList", []):
            return parse_product_price(price_item)
    raise ValueError(f"No Linux shared On-Demand price found for {instance_type} in {location}")


def load_existing_pricing(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def build_pricing_data(
    existing_data: dict[str, Any],
    region: str,
    pricing_region: str,
    instance_types: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    return {
        "metadata": {
            "name": f"AWS EC2 {region} On-Demand pricing reference",
            "effective_year": datetime.now(UTC).year,
            "region": region,
            "currency": "USD",
            "category": "compute",
            "scope": "ec2",
            "action": "downsizing",
            "source": {
                "name": "aws_pricing_api",
                "pricing_region": pricing_region,
                "operating_system": "Linux",
                "tenancy": "Shared",
                "pre_installed_sw": "NA",
                "capacity_status": "Used",
                "fetched_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            },
        },
        "instance_types": instance_types,
        "downgrade_rules": existing_data.get("downgrade_rules", DEFAULT_DOWNGRADE_RULES),
        "constraints": existing_data.get("constraints", DEFAULT_CONSTRAINTS),
    }


def write_pricing_data(data: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def fetch_pricing_data(region: str, pricing_region: str, instance_type_names: list[str], output_path: Path) -> dict[str, Any]:
    client = boto3.client("pricing", region_name=pricing_region)
    location = fetch_region_location(client, region)
    instance_types = {
        instance_type: fetch_instance_price(client, instance_type, location)
        for instance_type in instance_type_names
    }
    existing_data = load_existing_pricing(output_path)
    return build_pricing_data(existing_data, region, pricing_region, instance_types)


def main() -> None:
    args = parse_args()
    output_path = resolve_path(args.output)

    try:
        instance_types = parse_instance_types(args.instance_types)
        pricing_data = fetch_pricing_data(args.region, args.pricing_region, instance_types, output_path)
    except (BotoCoreError, ClientError, ValueError) as exc:
        raise SystemExit(f"Failed to fetch AWS EC2 pricing: {exc}") from exc

    write_pricing_data(pricing_data, output_path)
    print(f"Fetched {len(pricing_data['instance_types'])} EC2 prices into {output_path}")


if __name__ == "__main__":
    main()
