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
OWNERS = [
    "platform-team",
    "api-team",
    "checkout-team",
    "web-team",
    "data-team",
    "ml-platform-team",
    "analytics-team",
    "payments-team",
]
WORKLOADS = ["batch", "api", "worker", "web", "etl", "ml", "cache", "search"]


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
    profiles = [
        "idle",
        "underutilized",
        "healthy",
        "busy",
        "protected_low",
        "minimum_size",
    ]
    return profiles[index % len(profiles)]


def utilization_for_profile(profile: str, rng: random.Random, volatility: float) -> tuple[float, float, float]:
    baselines = {
        "idle": (4.5, 13.0, 11.0),
        "underutilized": (7.5, 24.0, 16.0),
        "healthy": (32.0, 65.0, 48.0),
        "busy": (58.0, 88.0, 70.0),
        "protected_low": (6.0, 19.0, 14.0),
        "minimum_size": (5.0, 16.0, 12.0),
    }
    avg_cpu, peak_cpu, avg_memory = baselines[profile]
    avg_cpu = clamp(avg_cpu + rng.uniform(-volatility, volatility), 1.0, 95.0)
    peak_cpu = clamp(max(avg_cpu + 3.0, peak_cpu + rng.uniform(-volatility, volatility)), 5.0, 99.0)
    avg_memory = clamp(avg_memory + rng.uniform(-volatility, volatility), 2.0, 98.0)
    return avg_cpu, peak_cpu, avg_memory


def build_instance(index: int, rng: random.Random, volatility: float) -> dict[str, Any]:
    profile = choose_profile(index)
    environment = ENVIRONMENTS[index % len(ENVIRONMENTS)]
    owner = OWNERS[index % len(OWNERS)]
    workload = WORKLOADS[index % len(WORKLOADS)]

    if profile == "minimum_size":
        instance_type = "t3.micro"
    elif profile in {"busy", "healthy"}:
        instance_type = rng.choice(["t3.medium", "t3.large", "t3.xlarge"])
    else:
        instance_type = rng.choice(["t3.large", "t3.xlarge", "t3.2xlarge"])

    avg_cpu, peak_cpu, avg_memory = utilization_for_profile(profile, rng, volatility)
    instance = {
        "instance_id": instance_id(index),
        "instance_type": instance_type,
        "monthly_cost": INSTANCE_PRICES[instance_type],
        "environment": environment,
        "owner": owner,
        "workload": workload,
        "metrics": {
            "avg_cpu_utilization": percent(avg_cpu),
            "peak_cpu_utilization": percent(peak_cpu),
            "avg_memory_utilization": percent(avg_memory),
        },
    }

    if profile == "protected_low" or (environment == "production" and index % 10 == 0):
        instance["protected"] = True
        instance["do_not_touch_reason"] = "production or owner-protected workload requires manual review"

    return instance


def build_temporary_instance(index: int, rng: random.Random, volatility: float) -> dict[str, Any]:
    avg_cpu, peak_cpu, avg_memory = utilization_for_profile("healthy", rng, volatility)
    instance_type = rng.choice(["t3.medium", "t3.large", "t3.xlarge"])
    return {
        "instance_id": instance_id(index, temporary=True),
        "instance_type": instance_type,
        "monthly_cost": round(INSTANCE_PRICES[instance_type] * rng.uniform(0.10, 0.35), 2),
        "environment": rng.choice(["dev", "staging"]),
        "owner": rng.choice(OWNERS),
        "workload": rng.choice(WORKLOADS),
        "temporary": True,
        "autoscaling_group": f"cloudoptix-demo-asg-{rng.randint(1, 3)}",
        "metrics": {
            "avg_cpu_utilization": percent(avg_cpu),
            "peak_cpu_utilization": percent(peak_cpu),
            "avg_memory_utilization": percent(avg_memory),
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
        "report_id": "BILL-2026-05-MOCK-FLEET",
        "resource_type": "AWS EC2",
        "region": "us-east-1",
        "generated_at": datetime(2026, 5, 9, tzinfo=UTC).isoformat().replace("+00:00", "Z"),
        "simulation": {
            "seed": seed,
            "base_fleet_size": fleet_size,
            "autoscale_temporary_instances": autoscale_count,
            "cpu_volatility_percent": cpu_volatility,
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
