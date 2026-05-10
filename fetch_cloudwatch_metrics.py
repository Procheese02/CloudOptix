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
DEFAULT_BILLING_PATH = PROJECT_ROOT / "data" / "cost_explorer_billing.json"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "data" / "cloudwatch_enriched_billing.json"
TAG_ALIASES = {
    "environment": ["Environment", "Env", "environment", "env"],
    "owner": ["Owner", "Team", "ServiceOwner", "owner", "team"],
    "workload": ["Workload", "Service", "Application", "Name", "workload", "service"],
}

load_dotenv(dotenv_path=PROJECT_ROOT / ".env")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Enrich CloudOptix billing JSON with read-only EC2 CloudWatch metrics and tags.")
    parser.add_argument("--billing-file", type=Path, default=DEFAULT_BILLING_PATH, help="Input billing JSON file.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH, help="Output enriched billing JSON path.")
    parser.add_argument("--start", help="Inclusive metric start date in YYYY-MM-DD format. Defaults to 14 days ago.")
    parser.add_argument("--end", help="Exclusive metric end date in YYYY-MM-DD format. Defaults to today.")
    parser.add_argument("--region", default=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"), help="AWS region for EC2 and CloudWatch.")
    parser.add_argument("--period", type=int, default=3600, help="CloudWatch metric period in seconds.")
    return parser.parse_args()


def resolve_path(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


def parse_date(value: str, field_name: str) -> datetime:
    try:
        return datetime.combine(date.fromisoformat(value), datetime.min.time(), tzinfo=UTC)
    except ValueError as exc:
        raise ValueError(f"{field_name} must use YYYY-MM-DD format: {value}") from exc


def default_time_period() -> tuple[datetime, datetime]:
    end = datetime.combine(date.today(), datetime.min.time(), tzinfo=UTC)
    return end - timedelta(days=14), end


def get_time_period(args: argparse.Namespace) -> tuple[datetime, datetime]:
    default_start, default_end = default_time_period()
    start = parse_date(args.start, "--start") if args.start else default_start
    end = parse_date(args.end, "--end") if args.end else default_end
    if start >= end:
        raise ValueError("--start must be earlier than --end")
    return start, end


def load_billing_data(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def get_instances(billing_data: dict[str, Any]) -> list[dict[str, Any]]:
    instances = billing_data.get("instances")
    if isinstance(instances, list):
        return instances
    if billing_data.get("instance_id"):
        return [billing_data]
    return []


def tag_map(tags: list[dict[str, str]]) -> dict[str, str]:
    return {tag.get("Key", ""): tag.get("Value", "") for tag in tags if tag.get("Key")}


def tag_value(tags: dict[str, str], field: str) -> str | None:
    for key in TAG_ALIASES[field]:
        value = tags.get(key)
        if value:
            return value
    return None


def fetch_ec2_metadata(region: str) -> dict[str, dict[str, Any]]:
    client = boto3.client("ec2", region_name=region)
    metadata: dict[str, dict[str, Any]] = {}
    paginator = client.get_paginator("describe_instances")
    for page in paginator.paginate():
        for reservation in page.get("Reservations", []):
            for instance in reservation.get("Instances", []):
                instance_id = instance.get("InstanceId")
                if not instance_id:
                    continue
                tags = tag_map(instance.get("Tags", []))
                metadata[instance_id] = {
                    "instance_type": instance.get("InstanceType"),
                    "environment": tag_value(tags, "environment"),
                    "owner": tag_value(tags, "owner"),
                    "workload": tag_value(tags, "workload"),
                    "tags": tags,
                }
    return metadata


def metric_query(query_id: str, metric_name: str, instance_id: str, stat: str, period: int) -> dict[str, Any]:
    return {
        "Id": query_id,
        "MetricStat": {
            "Metric": {
                "Namespace": "AWS/EC2",
                "MetricName": metric_name,
                "Dimensions": [{"Name": "InstanceId", "Value": instance_id}],
            },
            "Period": period,
            "Stat": stat,
        },
        "ReturnData": True,
    }


def build_metric_queries(instance_id: str, period: int) -> list[dict[str, Any]]:
    return [
        metric_query("cpu_avg", "CPUUtilization", instance_id, "Average", period),
        metric_query("cpu_max", "CPUUtilization", instance_id, "Maximum", period),
        metric_query("network_in", "NetworkIn", instance_id, "Average", period),
        metric_query("network_out", "NetworkOut", instance_id, "Average", period),
        metric_query("disk_read", "DiskReadBytes", instance_id, "Average", period),
        metric_query("disk_write", "DiskWriteBytes", instance_id, "Average", period),
    ]


def average(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def maximum(values: list[float]) -> float | None:
    if not values:
        return None
    return round(max(values), 2)


def percent(value: float | None) -> str | None:
    if value is None:
        return None
    return f"{value:.2f}%"


def result_values(results: list[dict[str, Any]]) -> dict[str, list[float]]:
    return {result.get("Id", ""): [float(value) for value in result.get("Values", [])] for result in results}


def fetch_instance_metrics(client: Any, instance_id: str, start: datetime, end: datetime, period: int) -> dict[str, Any]:
    response = client.get_metric_data(
        MetricDataQueries=build_metric_queries(instance_id, period),
        StartTime=start,
        EndTime=end,
    )
    values = result_values(response.get("MetricDataResults", []))
    cpu_avg = average(values.get("cpu_avg", []))
    cpu_peak = maximum(values.get("cpu_max", []))
    metrics = {
        "avg_cpu_utilization": percent(cpu_avg),
        "peak_cpu_utilization": percent(cpu_peak),
        "avg_network_in_bytes": average(values.get("network_in", [])),
        "avg_network_out_bytes": average(values.get("network_out", [])),
        "avg_disk_read_bytes": average(values.get("disk_read", [])),
        "avg_disk_write_bytes": average(values.get("disk_write", [])),
    }
    return {key: value for key, value in metrics.items() if value is not None}


def enrich_instance(
    instance: dict[str, Any],
    ec2_metadata: dict[str, dict[str, Any]],
    cloudwatch_metrics: dict[str, Any],
) -> dict[str, Any]:
    instance_id = instance.get("instance_id", "")
    metadata = ec2_metadata.get(instance_id, {})
    enriched = dict(instance)

    for field in ["instance_type", "environment", "owner", "workload"]:
        value = metadata.get(field)
        if value:
            enriched[field] = value

    if metadata.get("tags"):
        enriched["tags"] = metadata["tags"]

    metrics = dict(enriched.get("metrics", {}))
    metrics.update(cloudwatch_metrics)
    if "avg_memory_utilization" not in metrics:
        metrics["avg_memory_utilization"] = "100.00%"
    enriched["metrics"] = metrics

    has_memory_placeholder = metrics.get("avg_memory_utilization") == "100.00%"
    if cloudwatch_metrics.get("avg_cpu_utilization"):
        enriched["protected"] = bool(enriched.get("protected")) or has_memory_placeholder
        if has_memory_placeholder:
            enriched.setdefault(
                "do_not_touch_reason",
                "CloudWatch default EC2 metrics do not include memory; install CloudWatch Agent before automatic rightsizing.",
            )
    else:
        enriched["protected"] = True
        enriched["do_not_touch_reason"] = "CloudWatch returned no CPU utilization data for this instance."

    return enriched


def enrich_billing_data(
    billing_data: dict[str, Any],
    ec2_metadata: dict[str, dict[str, Any]],
    metrics_by_instance: dict[str, dict[str, Any]],
    region: str,
    start: datetime,
    end: datetime,
) -> dict[str, Any]:
    instances = [
        enrich_instance(instance, ec2_metadata, metrics_by_instance.get(str(instance.get("instance_id", "")), {}))
        for instance in get_instances(billing_data)
    ]
    enriched = dict(billing_data)
    enriched["instances"] = instances
    enriched["generated_at"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    enriched["source"] = {
        "name": "aws_cost_explorer_cloudwatch_enriched",
        "base_source": billing_data.get("source", {}).get("name", "local_billing_json"),
        "region": region,
        "time_period": {
            "start": start.date().isoformat(),
            "end": end.date().isoformat(),
        },
        "metrics": [
            "CPUUtilization",
            "NetworkIn",
            "NetworkOut",
            "DiskReadBytes",
            "DiskWriteBytes",
        ],
        "memory_note": "EC2 memory utilization requires CloudWatch Agent and is not included in default CloudWatch metrics.",
    }
    return enriched


def write_billing_data(data: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    billing_path = resolve_path(args.billing_file)
    output_path = resolve_path(args.output)

    try:
        start, end = get_time_period(args)
        billing_data = load_billing_data(billing_path)
        ec2_metadata = fetch_ec2_metadata(args.region)
        cloudwatch = boto3.client("cloudwatch", region_name=args.region)
        metrics_by_instance = {
            str(instance.get("instance_id")): fetch_instance_metrics(cloudwatch, str(instance.get("instance_id")), start, end, args.period)
            for instance in get_instances(billing_data)
            if str(instance.get("instance_id", "")).startswith("i-")
        }
    except (BotoCoreError, ClientError) as exc:
        raise SystemExit(f"Failed to read AWS CloudWatch data: {exc}") from exc
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    enriched = enrich_billing_data(billing_data, ec2_metadata, metrics_by_instance, args.region, start, end)
    write_billing_data(enriched, output_path)
    print(f"Enriched {len(enriched['instances'])} billing records with CloudWatch metrics at {output_path}")


if __name__ == "__main__":
    main()
