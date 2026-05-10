import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import fetch_aws_pricing

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_BILLING_PATH = PROJECT_ROOT / "data" / "mock_billing.json"
DEFAULT_PRICING_PATH = PROJECT_ROOT / "data" / "aws_pricing.json"
DEFAULT_REGION = "us-east-1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync mock billing monthly costs from structured AWS pricing data.")
    parser.add_argument("--billing-file", type=Path, default=DEFAULT_BILLING_PATH, help="Mock billing JSON file to update.")
    parser.add_argument("--pricing-file", type=Path, default=DEFAULT_PRICING_PATH, help="Structured AWS pricing JSON file.")
    parser.add_argument("--output", type=Path, help="Output billing JSON path. Defaults to overwriting --billing-file.")
    parser.add_argument("--refresh-aws-pricing", action="store_true", help="Fetch current AWS Pricing API data before syncing costs.")
    parser.add_argument("--region", default=DEFAULT_REGION, help="EC2 region code to price when refreshing AWS pricing.")
    parser.add_argument("--pricing-region", default=DEFAULT_REGION, help="AWS Pricing API endpoint region.")
    parser.add_argument(
        "--instance-types",
        help="Comma-separated EC2 instance types to refresh. Defaults to the types present in the billing file.",
    )
    return parser.parse_args()


def resolve_path(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def get_instances(billing_data: dict[str, Any]) -> list[dict[str, Any]]:
    instances = billing_data.get("instances")
    if isinstance(instances, list):
        return instances
    if billing_data.get("instance_id"):
        return [billing_data]
    return []


def instance_types_from_billing(billing_data: dict[str, Any]) -> list[str]:
    return sorted({
        str(instance["instance_type"])
        for instance in get_instances(billing_data)
        if instance.get("instance_type")
    })


def load_or_refresh_pricing_data(
    billing_data: dict[str, Any],
    pricing_path: Path,
    refresh_aws_pricing: bool,
    region: str,
    pricing_region: str,
    instance_types_value: str | None,
) -> tuple[dict[str, Any], bool]:
    if not refresh_aws_pricing:
        return load_json(pricing_path), False

    if instance_types_value:
        instance_types = fetch_aws_pricing.parse_instance_types(instance_types_value)
    else:
        instance_types = instance_types_from_billing(billing_data)

    if not instance_types:
        raise ValueError("billing data does not include any instance types to refresh")

    pricing_data = fetch_aws_pricing.fetch_pricing_data(region, pricing_region, instance_types, pricing_path)
    fetch_aws_pricing.write_pricing_data(pricing_data, pricing_path)
    return pricing_data, True


def pricing_monthly_estimates(pricing_data: dict[str, Any]) -> dict[str, float]:
    estimates = {}
    for instance_type, details in pricing_data.get("instance_types", {}).items():
        if "monthly_estimate" in details:
            estimates[instance_type] = float(details["monthly_estimate"])
    return estimates


def previous_cost_by_type(instances: list[dict[str, Any]]) -> dict[str, float]:
    costs: dict[str, float] = {}
    for instance in instances:
        if instance.get("temporary"):
            continue
        instance_type = instance.get("instance_type")
        monthly_cost = instance.get("monthly_cost")
        if instance_type and monthly_cost is not None:
            costs.setdefault(str(instance_type), float(monthly_cost))
    return costs


def synced_cost(instance: dict[str, Any], new_monthly_cost: float, previous_full_cost: float | None) -> float:
    old_cost = float(instance.get("monthly_cost", 0) or 0)
    if instance.get("temporary") and previous_full_cost and previous_full_cost > 0:
        return round(new_monthly_cost * (old_cost / previous_full_cost), 2)
    return round(new_monthly_cost, 2)


def sync_billing_costs(billing_data: dict[str, Any], pricing_data: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    estimates = pricing_monthly_estimates(pricing_data)
    instances = get_instances(billing_data)
    previous_costs = previous_cost_by_type(instances)
    updated = 0
    unchanged_instance_types = set()

    for instance in instances:
        instance_type = instance.get("instance_type")
        if instance_type not in estimates:
            unchanged_instance_types.add(str(instance_type or "unknown"))
            continue
        instance["monthly_cost"] = synced_cost(instance, estimates[instance_type], previous_costs.get(instance_type))
        updated += 1

    pricing_metadata = pricing_data.get("metadata", {})
    billing_data["cost_sync"] = {
        "source": pricing_metadata.get("source", {}).get("name", "aws_pricing_json"),
        "pricing_name": pricing_metadata.get("name"),
        "pricing_region": pricing_metadata.get("region"),
        "synced_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "updated_instance_count": updated,
        "unchanged_instance_types": sorted(unchanged_instance_types),
    }
    summary = {
        "updated_instance_count": updated,
        "unchanged_instance_types": sorted(unchanged_instance_types),
    }
    return billing_data, summary


def write_json(data: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    billing_path = resolve_path(args.billing_file)
    pricing_path = resolve_path(args.pricing_file)
    output_path = resolve_path(args.output) if args.output else billing_path

    billing_data = load_json(billing_path)
    pricing_data, refreshed_pricing = load_or_refresh_pricing_data(
        billing_data,
        pricing_path,
        args.refresh_aws_pricing,
        args.region,
        args.pricing_region,
        args.instance_types,
    )
    synced_data, summary = sync_billing_costs(billing_data, pricing_data)
    write_json(synced_data, output_path)

    if refreshed_pricing:
        print(f"Refreshed AWS pricing for {len(pricing_data['instance_types'])} instance types at {pricing_path}")
    print(f"Updated {summary['updated_instance_count']} billing records at {output_path}")
    if summary["unchanged_instance_types"]:
        print("Unchanged instance types: " + ", ".join(summary["unchanged_instance_types"]))


if __name__ == "__main__":
    main()
