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
INSTANCE_DOWNGRADE_ORDER = [
    "t3.micro",
    "t3.small",
    "t3.medium",
    "t3.large",
    "t3.xlarge",
    "t3.2xlarge",
]
INSTANCE_PRICES = {
    "t3.micro": 7.67,
    "t3.small": 15.33,
    "t3.medium": 30.66,
    "t3.large": 61.32,
    "t3.xlarge": 122.64,
    "t3.2xlarge": 245.28,
}
PRICING_MODEL_MULTIPLIERS = {
    "on_demand": 1.00,
    "savings_plan": 0.72,
    "reserved_1yr": 0.68,
    "spot": 0.35,
}
UNKNOWN = "unknown"


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


def monthly_cost(instance: dict[str, Any]) -> float:
    try:
        return float(instance.get("monthly_cost", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def field_value(instance: dict[str, Any], field: str) -> str:
    value = instance.get(field)
    if value in {None, ""}:
        if field == "service":
            value = instance.get("workload")
        elif field == "business_unit":
            value = instance.get("owner")
    return str(value or UNKNOWN)


def metric_value(instance: dict[str, Any], metric: str) -> float | None:
    return parse_percent(instance.get("metrics", {}).get(metric))


def has_complete_metrics(instance: dict[str, Any]) -> bool:
    if instance.get("metrics_source") == "missing":
        return False
    metrics = instance.get("metrics")
    if not isinstance(metrics, dict):
        return False
    return all(parse_percent(metrics.get(field)) is not None for field in REQUIRED_METRIC_FIELDS)


def is_cost_only_source(billing_data: dict[str, Any]) -> bool:
    return billing_data.get("source", {}).get("name") == "aws_cost_explorer"


def is_low_utilization(instance: dict[str, Any]) -> bool:
    avg_cpu = metric_value(instance, "avg_cpu_utilization")
    peak_cpu = metric_value(instance, "peak_cpu_utilization")
    avg_memory = metric_value(instance, "avg_memory_utilization")
    if avg_cpu is None or peak_cpu is None or avg_memory is None:
        return False
    return avg_cpu < 10.0 and peak_cpu <= 30.0 and avg_memory < 20.0


def target_instance_type(instance_type: str) -> str | None:
    if instance_type not in INSTANCE_DOWNGRADE_ORDER:
        return None
    current_index = INSTANCE_DOWNGRADE_ORDER.index(instance_type)
    target_index = max(0, current_index - 2)
    if target_index == current_index:
        return None
    return INSTANCE_DOWNGRADE_ORDER[target_index]


def estimate_target_monthly_cost(instance: dict[str, Any], target_type: str) -> float | None:
    current_type = str(instance.get("instance_type", ""))
    current_price = INSTANCE_PRICES.get(current_type)
    target_price = INSTANCE_PRICES.get(target_type)
    if current_price is None or target_price is None:
        return None

    pricing_model = field_value(instance, "pricing_model")
    multiplier = PRICING_MODEL_MULTIPLIERS.get(pricing_model, 1.0)
    baseline_current_cost = current_price * multiplier
    if baseline_current_cost <= 0:
        return None

    return round(monthly_cost(instance) * ((target_price * multiplier) / baseline_current_cost), 2)


def estimated_monthly_savings(instance: dict[str, Any]) -> tuple[str | None, float]:
    target_type = target_instance_type(str(instance.get("instance_type", "")))
    if target_type is None:
        return None, 0.0
    target_cost = estimate_target_monthly_cost(instance, target_type)
    if target_cost is None:
        return target_type, 0.0
    return target_type, round(max(0.0, monthly_cost(instance) - target_cost), 2)


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
        cost = monthly_cost(instance)

        if avg_cpu is not None:
            groups[instance_type]["cpu"].append(avg_cpu)
        if avg_memory is not None:
            groups[instance_type]["memory"].append(avg_memory)
        groups[instance_type]["cost"].append(cost)

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
    total_cost = sum(monthly_cost(instance) for instance in instances)
    if total_cost <= 0:
        return []

    shares = [
        {
            "instance_id": instance.get("instance_id", "unknown"),
            "instance_type": instance.get("instance_type", "unknown"),
            "monthly_cost": round(monthly_cost(instance), 2),
            "cost_share": round(monthly_cost(instance) / total_cost, 6),
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
    costs = [monthly_cost(instance) for instance in instances]
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
        cost = monthly_cost(instance)
        instance_type = instance.get("instance_type", "unknown")
        if avg_cpu is None:
            continue
        if instance_type in HIGH_SPEC_INSTANCE_TYPES and avg_cpu <= low_cpu_threshold and cost >= high_cost_threshold:
            anomalies.append({
                "instance_id": instance.get("instance_id", "unknown"),
                "instance_type": instance_type,
                "avg_cpu_utilization": round(avg_cpu, 2),
                "monthly_cost": round(cost, 2),
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
        if instance.get("metrics_source") == "missing":
            for field in REQUIRED_METRIC_FIELDS:
                missing_metrics.append({"instance_id": instance_id, "field": f"metrics.{field}", "reason": "missing metrics source"})
        elif isinstance(metrics, dict):
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


def grouped_cost_summary(instances: list[dict[str, Any]], fields: tuple[str, ...]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, ...], dict[str, Any]] = defaultdict(
        lambda: {
            "instance_count": 0,
            "total_monthly_cost": 0.0,
            "cpu": [],
            "memory": [],
            "protected_count": 0,
            "missing_metrics_count": 0,
        }
    )
    total_cost = sum(monthly_cost(instance) for instance in instances)

    for instance in instances:
        key = tuple(field_value(instance, field) for field in fields)
        group = groups[key]
        group["instance_count"] += 1
        group["total_monthly_cost"] += monthly_cost(instance)
        if instance.get("protected"):
            group["protected_count"] += 1
        if not has_complete_metrics(instance):
            group["missing_metrics_count"] += 1

        avg_cpu = metric_value(instance, "avg_cpu_utilization")
        avg_memory = metric_value(instance, "avg_memory_utilization")
        if avg_cpu is not None:
            group["cpu"].append(avg_cpu)
        if avg_memory is not None:
            group["memory"].append(avg_memory)

    rows = []
    for key, values in groups.items():
        row = {field: key[index] for index, field in enumerate(fields)}
        row.update({
            "instance_count": values["instance_count"],
            "total_monthly_cost": round(values["total_monthly_cost"], 2),
            "cost_share": round(values["total_monthly_cost"] / total_cost, 6) if total_cost > 0 else 0.0,
            "avg_cpu_utilization": average(values["cpu"]),
            "avg_memory_utilization": average(values["memory"]),
            "protected_count": values["protected_count"],
            "missing_metrics_count": values["missing_metrics_count"],
        })
        rows.append(row)

    return sorted(
        rows,
        key=lambda row: (-row["total_monthly_cost"], tuple(str(row[field]) for field in fields)),
    )


def savings_candidates(billing_data: dict[str, Any], instances: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if is_cost_only_source(billing_data):
        return []

    candidates = []
    for instance in instances:
        if instance.get("protected") or not is_low_utilization(instance):
            continue
        target_type, savings = estimated_monthly_savings(instance)
        if target_type is None or savings <= 0:
            continue
        candidates.append({
            "instance_id": instance.get("instance_id", UNKNOWN),
            "owner": field_value(instance, "owner"),
            "business_unit": field_value(instance, "business_unit"),
            "service": field_value(instance, "service"),
            "environment": field_value(instance, "environment"),
            "region": field_value(instance, "region"),
            "criticality": field_value(instance, "criticality"),
            "pricing_model": field_value(instance, "pricing_model"),
            "current_type": instance.get("instance_type", UNKNOWN),
            "target_type": target_type,
            "monthly_cost": round(monthly_cost(instance), 2),
            "estimated_monthly_savings": savings,
            "risk_level": "medium" if field_value(instance, "environment") == "production" else "low",
        })

    return sorted(candidates, key=lambda item: (-item["estimated_monthly_savings"], item["instance_id"]))


def top_waste_owners(candidates: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"candidate_count": 0, "candidate_monthly_cost": 0.0, "estimated_monthly_savings": 0.0, "top_instances": []}
    )

    for candidate in candidates:
        owner = candidate["owner"]
        group = groups[owner]
        group["candidate_count"] += 1
        group["candidate_monthly_cost"] += candidate["monthly_cost"]
        group["estimated_monthly_savings"] += candidate["estimated_monthly_savings"]
        group["top_instances"].append({
            "instance_id": candidate["instance_id"],
            "service": candidate["service"],
            "current_type": candidate["current_type"],
            "target_type": candidate["target_type"],
            "estimated_monthly_savings": candidate["estimated_monthly_savings"],
        })

    rows = []
    for owner, values in groups.items():
        top_instances = sorted(
            values["top_instances"],
            key=lambda item: (-item["estimated_monthly_savings"], item["instance_id"]),
        )[:3]
        rows.append({
            "owner": owner,
            "candidate_count": values["candidate_count"],
            "candidate_monthly_cost": round(values["candidate_monthly_cost"], 2),
            "estimated_monthly_savings": round(values["estimated_monthly_savings"], 2),
            "top_instances": top_instances,
        })

    return sorted(rows, key=lambda row: (-row["estimated_monthly_savings"], row["owner"]))[:limit]


def protected_resources_summary(instances: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str, str], dict[str, Any]] = defaultdict(
        lambda: {"protected_count": 0, "protected_monthly_cost": 0.0, "low_utilization_count": 0}
    )

    for instance in instances:
        if not instance.get("protected"):
            continue
        reason = str(instance.get("do_not_touch_reason") or "protected")
        key = (
            field_value(instance, "owner"),
            field_value(instance, "environment"),
            field_value(instance, "criticality"),
            reason,
        )
        group = groups[key]
        group["protected_count"] += 1
        group["protected_monthly_cost"] += monthly_cost(instance)
        if is_low_utilization(instance):
            group["low_utilization_count"] += 1

    rows = []
    for (owner, environment, criticality, reason), values in groups.items():
        rows.append({
            "owner": owner,
            "environment": environment,
            "criticality": criticality,
            "reason": reason,
            "protected_count": values["protected_count"],
            "protected_monthly_cost": round(values["protected_monthly_cost"], 2),
            "low_utilization_count": values["low_utilization_count"],
        })

    return sorted(rows, key=lambda row: (-row["protected_monthly_cost"], row["owner"], row["environment"]))


def missing_metrics_coverage(instances: list[dict[str, Any]]) -> dict[str, Any]:
    missing_instances = [instance for instance in instances if not has_complete_metrics(instance)]
    coverage = round((len(instances) - len(missing_instances)) / len(instances), 4) if instances else 0.0
    return {
        "total_instances": len(instances),
        "instances_with_complete_metrics": len(instances) - len(missing_instances),
        "missing_metrics_count": len(missing_instances),
        "coverage": coverage,
        "by_owner_environment": grouped_cost_summary(missing_instances, ("owner", "environment")),
    }


def enterprise_savings_summary(instances: list[dict[str, Any]], candidates: list[dict[str, Any]]) -> dict[str, Any]:
    total_cost = sum(monthly_cost(instance) for instance in instances)
    estimated_savings = sum(candidate["estimated_monthly_savings"] for candidate in candidates)
    protected_low_utilization_count = sum(
        1 for instance in instances if instance.get("protected") and is_low_utilization(instance)
    )
    risk_breakdown: dict[str, int] = defaultdict(int)
    for candidate in candidates:
        risk_breakdown[candidate["risk_level"]] += 1

    return {
        "total_monthly_cost": round(total_cost, 2),
        "eligible_candidate_count": len(candidates),
        "protected_low_utilization_count": protected_low_utilization_count,
        "estimated_monthly_savings": round(estimated_savings, 2),
        "savings_rate": round(estimated_savings / total_cost, 4) if total_cost > 0 else 0.0,
        "risk_breakdown": dict(sorted(risk_breakdown.items())),
        "top_candidates": candidates[:10],
    }


def enterprise_summary(billing_data: dict[str, Any], instances: list[dict[str, Any]]) -> dict[str, Any]:
    candidates = savings_candidates(billing_data, instances)
    return {
        "cost_by_team_service_environment": grouped_cost_summary(instances, ("owner", "service", "environment")),
        "cost_by_business_unit": grouped_cost_summary(instances, ("business_unit",)),
        "cost_by_service": grouped_cost_summary(instances, ("service",)),
        "cost_by_region": grouped_cost_summary(instances, ("region",)),
        "cost_by_pricing_model": grouped_cost_summary(instances, ("pricing_model",)),
        "criticality_mix": grouped_cost_summary(instances, ("criticality",)),
        "utilization_pattern_summary": grouped_cost_summary(instances, ("utilization_pattern",)),
        "top_waste_owners": top_waste_owners(candidates),
        "protected_resources_summary": protected_resources_summary(instances),
        "missing_metrics_coverage": missing_metrics_coverage(instances),
        "enterprise_savings_summary": enterprise_savings_summary(instances, candidates),
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
        "enterprise_summary": enterprise_summary(billing_data, instances),
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
