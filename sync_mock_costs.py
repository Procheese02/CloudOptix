import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_BILLING_PATH = PROJECT_ROOT / "data" / "mock_billing.json"
DEFAULT_PRICING_PATH = PROJECT_ROOT / "data" / "aws_pricing.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync mock billing monthly costs from structured AWS pricing data.")
    parser.add_argument("--billing-file", type=Path, default=DEFAULT_BILLING_PATH, help="Mock billing JSON file to update.")
    parser.add_argument("--pricing-file", type=Path, default=DEFAULT_PRICING_PATH, help="Structured AWS pricing JSON file.")
    parser.add_argument("--output", type=Path, help="Output billing JSON path. Defaults to overwriting --billing-file.")
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
        "source": "aws_pricing_json",
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
    pricing_data = load_json(pricing_path)
    synced_data, summary = sync_billing_costs(billing_data, pricing_data)
    write_json(synced_data, output_path)

    print(f"Updated {summary['updated_instance_count']} billing records at {output_path}")
    if summary["unchanged_instance_types"]:
        print("Unchanged instance types: " + ", ".join(summary["unchanged_instance_types"]))


if __name__ == "__main__":
    main()
