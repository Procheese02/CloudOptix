import argparse
import json
import random
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "data" / "mock_billing.json"
INSTANCE_PRICES = {
    "t3.micro": 7.67,
    "t3.small": 15.33,
    "t3.medium": 30.66,
    "t3.large": 61.32,
    "t3.xlarge": 122.64,
    "t3.2xlarge": 245.28,
}
ENVIRONMENTS = ["dev", "staging", "production"]
BUSINESS_UNITS = [
    "consumer",
    "commerce",
    "platform",
    "data",
    "risk",
    "operations",
]
SERVICE_CATALOG = [
    {"service": "identity-api", "business_unit": "consumer", "owner": "platform-team", "workload": "api"},
    {"service": "checkout-api", "business_unit": "commerce", "owner": "checkout-team", "workload": "api"},
    {"service": "payments-worker", "business_unit": "commerce", "owner": "payments-team", "workload": "worker"},
    {"service": "billing-etl", "business_unit": "data", "owner": "data-team", "workload": "etl"},
    {"service": "analytics-jobs", "business_unit": "data", "owner": "analytics-team", "workload": "batch"},
    {"service": "risk-scoring", "business_unit": "risk", "owner": "ml-platform-team", "workload": "ml"},
    {"service": "search-indexer", "business_unit": "platform", "owner": "search-team", "workload": "search"},
    {"service": "web-edge", "business_unit": "consumer", "owner": "web-team", "workload": "web"},
    {"service": "cache-cluster", "business_unit": "platform", "owner": "platform-team", "workload": "cache"},
    {"service": "ops-reporting", "business_unit": "operations", "owner": "ops-team", "workload": "batch"},
]
OWNERS = sorted({service["owner"] for service in SERVICE_CATALOG})
WORKLOADS = ["batch", "api", "worker", "web", "etl", "ml", "cache", "search"]
CRITICALITIES = ["low", "medium", "high", "critical"]
REGIONS = ["us-east-1", "us-east-2", "us-west-2", "ca-central-1", "eu-west-1"]
PRICING_MODELS = ["on_demand", "savings_plan", "reserved_1yr", "spot"]
PRICING_MODEL_MULTIPLIERS = {
    "on_demand": 1.00,
    "savings_plan": 0.72,
    "reserved_1yr": 0.68,
    "spot": 0.35,
}
UTILIZATION_PATTERNS = [
    "idle",
    "underutilized",
    "healthy",
    "spiky",
    "memory_bound",
    "network_heavy",
    "missing_metrics",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate dynamic mock AWS EC2 billing data.")
    parser.add_argument("--fleet-size", type=int, default=60, help="Base fleet size before temporary autoscaling instances.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducible mock data.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH, help="Output JSON path.")
    parser.add_argument("--cpu-volatility", type=float, default=5.0, help="Maximum CPU utilization fluctuation percentage.")
    parser.add_argument(
        "--autoscale-count",
        type=int,
        default=4,
        help="Temporary instances to add for autoscaling simulation.",
    )
    return parser.parse_args()


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def percent(value: float) -> str:
    return f"{value:.2f}%"


def instance_id(index: int, temporary: bool = False) -> str:
    prefix = "0temp" if temporary else "0ec2"
    return f"i-{prefix}{index:012x}"[:19]


def choose_profile(index: int) -> str:
    return UTILIZATION_PATTERNS[index % len(UTILIZATION_PATTERNS)]


def utilization_for_profile(profile: str, rng: random.Random, volatility: float) -> tuple[float, float, float]:
    baselines = {
        "idle": (4.5, 13.0, 11.0),
        "underutilized": (7.5, 24.0, 16.0),
        "healthy": (32.0, 65.0, 48.0),
        "spiky": (18.0, 88.0, 42.0),
        "memory_bound": (16.0, 46.0, 86.0),
        "network_heavy": (24.0, 58.0, 52.0),
        "missing_metrics": (100.0, 100.0, 100.0),
    }
    avg_cpu, peak_cpu, avg_memory = baselines[profile]
    avg_cpu = clamp(avg_cpu + rng.uniform(-volatility, volatility), 1.0, 95.0)
    peak_cpu = clamp(max(avg_cpu + 3.0, peak_cpu + rng.uniform(-volatility, volatility)), 5.0, 99.0)
    avg_memory = clamp(avg_memory + rng.uniform(-volatility, volatility), 2.0, 98.0)
    return avg_cpu, peak_cpu, avg_memory


def network_for_profile(profile: str, rng: random.Random) -> tuple[float, float]:
    baselines = {
        "idle": (4.0, 15.0),
        "underutilized": (12.0, 35.0),
        "healthy": (55.0, 160.0),
        "spiky": (85.0, 420.0),
        "memory_bound": (35.0, 110.0),
        "network_heavy": (260.0, 920.0),
        "missing_metrics": (0.0, 0.0),
    }
    avg_network, peak_network = baselines[profile]
    avg_network = clamp(avg_network + rng.uniform(-8.0, 8.0), 0.0, 1200.0)
    peak_network = clamp(max(avg_network, peak_network + rng.uniform(-30.0, 30.0)), 0.0, 2000.0)
    return avg_network, peak_network


def choose_instance_type(profile: str, index: int, rng: random.Random) -> str:
    if profile in {"idle", "underutilized"} and index % 29 == 0:
        return "t3.micro"
    if profile in {"idle", "underutilized"}:
        return rng.choice(["t3.large", "t3.xlarge", "t3.2xlarge"])
    if profile in {"spiky", "memory_bound", "network_heavy"}:
        return rng.choice(["t3.large", "t3.xlarge", "t3.2xlarge"])
    return rng.choice(["t3.medium", "t3.large", "t3.xlarge"])


def choose_pricing_model(index: int, environment: str) -> str:
    pricing_model = PRICING_MODELS[index % len(PRICING_MODELS)]
    if environment == "production" and pricing_model == "spot":
        return "savings_plan"
    return pricing_model


def monthly_cost(instance_type: str, pricing_model: str) -> float:
    return round(INSTANCE_PRICES[instance_type] * PRICING_MODEL_MULTIPLIERS[pricing_model], 2)


def criticality_for_instance(index: int, environment: str) -> str:
    if environment == "production" and index % 4 == 0:
        return "critical"
    return CRITICALITIES[index % len(CRITICALITIES)]


def protection_reason(
    profile: str,
    environment: str,
    criticality: str,
    pricing_model: str,
    index: int,
) -> str | None:
    if profile == "missing_metrics":
        return "missing utilization metrics require manual review"
    if environment == "production" and criticality == "critical":
        return "critical production workload requires architecture review"
    if environment == "production" and index % 10 == 0:
        return "production workload requires owner approval"
    if pricing_model == "reserved_1yr" and index % 11 == 0:
        return "reserved commitment requires finance review before resizing"
    return None


def build_instance(index: int, rng: random.Random, volatility: float) -> dict[str, Any]:
    profile = choose_profile(index)
    environment = ENVIRONMENTS[index % len(ENVIRONMENTS)]
    service = SERVICE_CATALOG[index % len(SERVICE_CATALOG)]
    owner = service["owner"]
    workload = service["workload"]
    business_unit = service["business_unit"]
    criticality = criticality_for_instance(index, environment)
    region = REGIONS[index % len(REGIONS)]
    pricing_model = choose_pricing_model(index, environment)
    instance_type = choose_instance_type(profile, index, rng)
    instance = {
        "instance_id": instance_id(index),
        "instance_type": instance_type,
        "monthly_cost": monthly_cost(instance_type, pricing_model),
        "environment": environment,
        "owner": owner,
        "business_unit": business_unit,
        "service": service["service"],
        "criticality": criticality,
        "region": region,
        "pricing_model": pricing_model,
        "utilization_pattern": profile,
        "workload": workload,
        "metrics_source": "missing" if profile == "missing_metrics" else "cloudwatch",
    }

    if profile == "missing_metrics":
        instance["metrics"] = {}
    else:
        avg_cpu, peak_cpu, avg_memory = utilization_for_profile(profile, rng, volatility)
        avg_network, peak_network = network_for_profile(profile, rng)
        instance["metrics"] = {
            "avg_cpu_utilization": percent(avg_cpu),
            "peak_cpu_utilization": percent(peak_cpu),
            "avg_memory_utilization": percent(avg_memory),
            "avg_network_mbps": round(avg_network, 2),
            "peak_network_mbps": round(peak_network, 2),
        }

    reason = protection_reason(profile, environment, criticality, pricing_model, index)
    if reason:
        instance["protected"] = True
        instance["do_not_touch_reason"] = reason

    return instance


def build_temporary_instance(index: int, rng: random.Random, volatility: float) -> dict[str, Any]:
    avg_cpu, peak_cpu, avg_memory = utilization_for_profile("healthy", rng, volatility)
    avg_network, peak_network = network_for_profile("healthy", rng)
    instance_type = rng.choice(["t3.medium", "t3.large", "t3.xlarge"])
    service = rng.choice(SERVICE_CATALOG)
    pricing_model = rng.choice(["on_demand", "spot"])
    return {
        "instance_id": instance_id(index, temporary=True),
        "instance_type": instance_type,
        "monthly_cost": round(monthly_cost(instance_type, pricing_model) * rng.uniform(0.10, 0.35), 2),
        "environment": rng.choice(["dev", "staging"]),
        "owner": service["owner"],
        "business_unit": service["business_unit"],
        "service": service["service"],
        "criticality": "low",
        "region": rng.choice(REGIONS),
        "pricing_model": pricing_model,
        "utilization_pattern": "healthy",
        "workload": service["workload"],
        "temporary": True,
        "autoscaling_group": f"cloudoptix-demo-asg-{rng.randint(1, 3)}",
        "metrics_source": "cloudwatch",
        "metrics": {
            "avg_cpu_utilization": percent(avg_cpu),
            "peak_cpu_utilization": percent(peak_cpu),
            "avg_memory_utilization": percent(avg_memory),
            "avg_network_mbps": round(avg_network, 2),
            "peak_network_mbps": round(peak_network, 2),
        },
    }


def generate_billing_data(
    fleet_size: int = 60,
    seed: int = 42,
    cpu_volatility: float = 5.0,
    autoscale_count: int = 4,
) -> dict[str, Any]:
    if fleet_size < 1:
        raise ValueError("fleet_size must be at least 1")
    if autoscale_count < 0:
        raise ValueError("autoscale_count cannot be negative")

    rng = random.Random(seed)
    instances = [build_instance(index, rng, cpu_volatility) for index in range(fleet_size)]
    instances.extend(
        build_temporary_instance(fleet_size + index, rng, cpu_volatility)
        for index in range(autoscale_count)
    )

    return {
        "report_id": "BILL-2026-05-MOCK-FLEET-V2",
        "resource_type": "AWS EC2",
        "region": "us-east-1",
        "generated_at": datetime(2026, 5, 9, tzinfo=UTC).isoformat().replace("+00:00", "Z"),
        "simulation": {
            "version": "enterprise_mock_fleet_v2",
            "seed": seed,
            "base_fleet_size": fleet_size,
            "autoscale_temporary_instances": autoscale_count,
            "cpu_volatility_percent": cpu_volatility,
            "dimensions": [
                "business_unit",
                "service",
                "criticality",
                "region",
                "pricing_model",
                "utilization_pattern",
            ],
        },
        "instances": instances,
    }


def write_billing_data(data: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    data = generate_billing_data(
        fleet_size=args.fleet_size,
        seed=args.seed,
        cpu_volatility=args.cpu_volatility,
        autoscale_count=args.autoscale_count,
    )
    output_path = args.output if args.output.is_absolute() else PROJECT_ROOT / args.output
    write_billing_data(data, output_path)
    print(f"Generated {len(data['instances'])} mock EC2 instances at {output_path}")


if __name__ == "__main__":
    main()
