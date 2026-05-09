import argparse
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_BILLING_PATH = PROJECT_ROOT / "data" / "mock_billing.json"
CPU_BUCKETS = [(0, 10), (10, 30), (30, 60), (60, 100)]
REQUIRED_INSTANCE_FIELDS = ["instance_id", "instance_type", "monthly_cost", "metrics"]
REQUIRED_METRIC_FIELDS = ["avg_cpu_utilization", "peak_cpu_utilization", "avg_memory_utilization"]
HIGH_SPEC_INSTANCE_TYPES = {"t3.large", "t3.xlarge", "t3.2xlarge"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze CloudOptix billing data into FinOps features.")
    parser.add_argument("--billing-file", type=Path, default=DEFAULT_BILLING_PATH, help="Billing JSON file to analyze.")
    parser.add_argument("--output", type=Path, help="Optional JSON output path. Prints to stdout when omitted.")
    return parser.parse_args()


def resolve_path(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


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


def parse_percent(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).strip().strip("%"))
    except ValueError:
        return None


def cpu_histogram(instances: list[dict[str, Any]]) -> list[dict[str, Any]]:
    histogram = []
    values = [
        parse_percent(instance.get("metrics", {}).get("avg_cpu_utilization"))
        for instance in instances
    ]
    parsed_values = [value for value in values if value is not None]

    for lower, upper in CPU_BUCKETS:
        label = f"{lower}-{upper}%"
        if upper == 100:
            count = sum(lower <= value <= upper for value in parsed_values)
        else:
            count = sum(lower <= value < upper for value in parsed_values)
        histogram.append({"bucket": label, "count": count})

    return histogram


def average(values: list[float]) -> float:
    return round(sum(values) / len(values), 2) if values else 0.0


def aggregate_by_instance_type(instances: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, list[float]]] = defaultdict(lambda: {"cpu": [], "memory": [], "cost": []})

    for instance in instances:
        instance_type = str(instance.get("instance_type", "unknown"))
        metrics = instance.get("metrics", {})
        avg_cpu = parse_percent(metrics.get("avg_cpu_utilization"))
        avg_memory = parse_percent(metrics.get("avg_memory_utilization"))
        monthly_cost = float(instance.get("monthly_cost", 0) or 0)

        if avg_cpu is not None:
            groups[instance_type]["cpu"].append(avg_cpu)
        if avg_memory is not None:
            groups[instance_type]["memory"].append(avg_memory)
        groups[instance_type]["cost"].append(monthly_cost)

    return [
        {
            "instance_type": instance_type,
            "instance_count": len(values["cost"]),
            "avg_cpu_utilization": average(values["cpu"]),
            "avg_memory_utilization": average(values["memory"]),
            "avg_monthly_cost": average(values["cost"]),
            "total_monthly_cost": round(sum(values["cost"]), 2),
        }
        for instance_type, values in sorted(groups.items())
    ]


def cost_share_by_instance(instances: list[dict[str, Any]]) -> list[dict[str, Any]]:
    total_cost = sum(float(instance.get("monthly_cost", 0) or 0) for instance in instances)
    if total_cost <= 0:
        return []

    shares = [
        {
            "instance_id": instance.get("instance_id", "unknown"),
            "instance_type": instance.get("instance_type", "unknown"),
            "monthly_cost": round(float(instance.get("monthly_cost", 0) or 0), 2),
            "cost_share": round(float(instance.get("monthly_cost", 0) or 0) / total_cost, 6),
        }
        for instance in instances
    ]
    return sorted(shares, key=lambda item: item["cost_share"], reverse=True)


def percentile(values: list[float], percentile_rank: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    index = (len(sorted_values) - 1) * percentile_rank
    lower = int(index)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = index - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def detect_anomalies(instances: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cpu_values = [
        value
        for instance in instances
        if (value := parse_percent(instance.get("metrics", {}).get("avg_cpu_utilization"))) is not None
    ]
    costs = [float(instance.get("monthly_cost", 0) or 0) for instance in instances]
    if not cpu_values or not costs:
        return []

    cpu_q1 = percentile(cpu_values, 0.25)
    cpu_q3 = percentile(cpu_values, 0.75)
    cpu_iqr = cpu_q3 - cpu_q1
    low_cpu_threshold = max(10.0, cpu_q1 - 1.5 * cpu_iqr)

    cost_q1 = percentile(costs, 0.25)
    cost_q3 = percentile(costs, 0.75)
    cost_iqr = cost_q3 - cost_q1
    high_cost_threshold = max(cost_q3, cost_q3 + 0.5 * cost_iqr)

    anomalies = []
    for instance in instances:
        avg_cpu = parse_percent(instance.get("metrics", {}).get("avg_cpu_utilization"))
        monthly_cost = float(instance.get("monthly_cost", 0) or 0)
        instance_type = instance.get("instance_type", "unknown")
        if avg_cpu is None:
            continue
        if instance_type in HIGH_SPEC_INSTANCE_TYPES and avg_cpu <= low_cpu_threshold and monthly_cost >= high_cost_threshold:
            anomalies.append({
                "instance_id": instance.get("instance_id", "unknown"),
                "instance_type": instance_type,
                "avg_cpu_utilization": round(avg_cpu, 2),
                "monthly_cost": round(monthly_cost, 2),
                "protected": bool(instance.get("protected")),
                "reason": "high-spec instance has low average CPU and high monthly cost",
            })

    return sorted(anomalies, key=lambda item: item["monthly_cost"], reverse=True)


def parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def timestamp_continuity_issues(instance: dict[str, Any]) -> list[str]:
    timestamps = instance.get("metric_timestamps")
    if not timestamps:
        return []
    parsed = [parse_timestamp(timestamp) for timestamp in timestamps]
    if any(timestamp is None for timestamp in parsed):
        return ["metric_timestamps contains invalid timestamp values"]
    sorted_timestamps = sorted(timestamp for timestamp in parsed if timestamp is not None)
    if len(sorted_timestamps) < 2:
        return []

    expected_delta = sorted_timestamps[1] - sorted_timestamps[0]
    gaps = [
        index
        for index in range(1, len(sorted_timestamps))
        if sorted_timestamps[index] - sorted_timestamps[index - 1] != expected_delta
    ]
    if gaps:
        return ["metric_timestamps are not continuous"]
    return []


def data_quality_checks(billing_data: dict[str, Any], instances: list[dict[str, Any]]) -> dict[str, Any]:
    missing_fields = []
    missing_metrics = []
    timestamp_issues = []
    instances_with_metrics = 0

    for index, instance in enumerate(instances):
        instance_id = instance.get("instance_id", f"index-{index}")
        for field in REQUIRED_INSTANCE_FIELDS:
            if field not in instance:
                missing_fields.append({"instance_id": instance_id, "field": field})

        metrics = instance.get("metrics")
        if isinstance(metrics, dict):
            present_metric = False
            for field in REQUIRED_METRIC_FIELDS:
                value = metrics.get(field)
                if value is None:
                    missing_metrics.append({"instance_id": instance_id, "field": f"metrics.{field}"})
                elif parse_percent(value) is None:
                    missing_metrics.append({"instance_id": instance_id, "field": f"metrics.{field}", "reason": "invalid percent"})
                else:
                    present_metric = True
            if present_metric:
                instances_with_metrics += 1
        else:
            for field in REQUIRED_METRIC_FIELDS:
                missing_metrics.append({"instance_id": instance_id, "field": f"metrics.{field}"})

        for issue in timestamp_continuity_issues(instance):
            timestamp_issues.append({"instance_id": instance_id, "issue": issue})

    generated_at = billing_data.get("generated_at")
    if generated_at and parse_timestamp(generated_at) is None:
        timestamp_issues.append({"scope": "report", "field": "generated_at", "issue": "invalid timestamp"})

    coverage = round(instances_with_metrics / len(instances), 4) if instances else 0.0
    return {
        "instance_count": len(instances),
        "missing_fields": missing_fields,
        "missing_metrics": missing_metrics,
        "timestamp_issues": timestamp_issues,
        "cloudwatch_metric_coverage": coverage,
        "partial_cloudwatch_coverage": coverage < 1.0,
    }


def analyze_billing_data(billing_data: dict[str, Any]) -> dict[str, Any]:
    instances = get_instances(billing_data)
    return {
        "report_id": billing_data.get("report_id"),
        "source": billing_data.get("source", {}).get("name", "mock_or_local_json"),
        "generated_at": billing_data.get("generated_at"),
        "fleet_size": len(instances),
        "cpu_distribution": cpu_histogram(instances),
        "instance_type_aggregation": aggregate_by_instance_type(instances),
        "cost_share_by_instance": cost_share_by_instance(instances),
        "anomalies": detect_anomalies(instances),
        "data_quality": data_quality_checks(billing_data, instances),
    }


def write_analysis(analysis: dict[str, Any], output_path: Path | None) -> None:
    content = json.dumps(analysis, indent=2, ensure_ascii=False) + "\n"
    if output_path is None:
        print(content, end="")
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    print(f"Wrote billing analysis to {output_path}")


def main() -> None:
    args = parse_args()
    billing_path = resolve_path(args.billing_file)
    output_path = resolve_path(args.output) if args.output else None
    analysis = analyze_billing_data(load_billing_data(billing_path))
    write_analysis(analysis, output_path)


if __name__ == "__main__":
    main()
