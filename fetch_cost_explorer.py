import argparse
import json
import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "data" / "cost_explorer_billing.json"
EC2_SERVICE_NAME = "Amazon Elastic Compute Cloud - Compute"

load_dotenv(dotenv_path=PROJECT_ROOT / ".env")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch read-only AWS Cost Explorer EC2 cost data into the CloudOptix billing JSON shape."
    )
    parser.add_argument("--start", help="Inclusive start date in YYYY-MM-DD format. Defaults to the first day of last month.")
    parser.add_argument("--end", help="Exclusive end date in YYYY-MM-DD format. Defaults to the first day of this month.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH, help="Output JSON path.")
    parser.add_argument(
        "--ce-region",
        default=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"),
        help="Region used for the Cost Explorer API client.",
    )
    parser.add_argument(
        "--include-non-instance-resources",
        action="store_true",
        help="Include Cost Explorer resource IDs that do not look like EC2 instance IDs.",
    )
    return parser.parse_args()


def default_time_period() -> tuple[str, str]:
    today = date.today()
    first_day_this_month = today.replace(day=1)
    last_day_previous_month = first_day_this_month - timedelta(days=1)
    first_day_previous_month = last_day_previous_month.replace(day=1)
    return first_day_previous_month.isoformat(), first_day_this_month.isoformat()


def parse_date(value: str, field_name: str) -> str:
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ValueError(f"{field_name} must use YYYY-MM-DD format: {value}") from exc


def get_time_period(args: argparse.Namespace) -> tuple[str, str]:
    default_start, default_end = default_time_period()
    start = parse_date(args.start, "--start") if args.start else default_start
    end = parse_date(args.end, "--end") if args.end else default_end
    if start >= end:
        raise ValueError("--start must be earlier than --end")
    return start, end


def fetch_cost_groups(start: str, end: str, ce_region: str) -> list[dict[str, Any]]:
    client = boto3.client("ce", region_name=ce_region)
    request: dict[str, Any] = {
        "TimePeriod": {"Start": start, "End": end},
        "Granularity": "MONTHLY",
        "Metrics": ["UnblendedCost"],
        "Filter": {
            "Dimensions": {
                "Key": "SERVICE",
                "Values": [EC2_SERVICE_NAME],
            }
        },
        "GroupBy": [
            {"Type": "DIMENSION", "Key": "RESOURCE_ID"},
            {"Type": "DIMENSION", "Key": "INSTANCE_TYPE"},
        ],
    }

    groups: list[dict[str, Any]] = []
    while True:
        response = client.get_cost_and_usage(**request)
        for result in response.get("ResultsByTime", []):
            groups.extend(result.get("Groups", []))
        next_token = response.get("NextPageToken")
        if not next_token:
            return groups
        request["NextPageToken"] = next_token


def cost_amount(group: dict[str, Any]) -> float:
    amount = group.get("Metrics", {}).get("UnblendedCost", {}).get("Amount", "0")
    return round(float(amount), 2)


def build_instance(group: dict[str, Any], include_non_instance_resources: bool) -> dict[str, Any] | None:
    keys = group.get("Keys", [])
    resource_id = keys[0] if keys else "unknown-resource"
    instance_type = keys[1] if len(keys) > 1 and keys[1] else "unknown"

    if not include_non_instance_resources and not resource_id.startswith("i-"):
        return None

    return {
        "instance_id": resource_id,
        "instance_type": instance_type,
        "monthly_cost": cost_amount(group),
        "environment": "unknown",
        "owner": "unknown",
        "workload": "unknown",
        "metrics": {
            "avg_cpu_utilization": "100.00%",
            "peak_cpu_utilization": "100.00%",
            "avg_memory_utilization": "100.00%",
        },
        "protected": True,
        "do_not_touch_reason": "Cost Explorer provides cost data only; utilization and ownership require separate review.",
    }


def build_billing_data(groups: list[dict[str, Any]], start: str, end: str, include_non_instance_resources: bool) -> dict[str, Any]:
    instances = [
        instance
        for group in groups
        if (instance := build_instance(group, include_non_instance_resources)) is not None and instance["monthly_cost"] > 0
    ]
    instances.sort(key=lambda instance: instance["monthly_cost"], reverse=True)

    return {
        "report_id": f"BILL-{start}-TO-{end}-COST-EXPLORER",
        "resource_type": "AWS EC2",
        "region": "all",
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "source": {
            "name": "aws_cost_explorer",
            "service_filter": EC2_SERVICE_NAME,
            "time_period": {"start": start, "end": end},
            "metrics": ["UnblendedCost"],
            "group_by": ["RESOURCE_ID", "INSTANCE_TYPE"],
        },
        "instances": instances,
    }


def write_billing_data(data: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    output_path = args.output if args.output.is_absolute() else PROJECT_ROOT / args.output

    try:
        start, end = get_time_period(args)
        groups = fetch_cost_groups(start, end, args.ce_region)
    except (BotoCoreError, ClientError) as exc:
        raise SystemExit(f"Failed to read AWS Cost Explorer data: {exc}") from exc
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    data = build_billing_data(groups, start, end, args.include_non_instance_resources)
    write_billing_data(data, output_path)
    print(f"Fetched {len(data['instances'])} Cost Explorer EC2 cost records at {output_path}")


if __name__ == "__main__":
    main()
