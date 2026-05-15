import argparse
from pathlib import Path

import analyze_billing
import persistence

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_BILLING_PATH = PROJECT_ROOT / "data" / "mock_billing.json"
DEFAULT_DB_PATH = PROJECT_ROOT / "cloudoptix.db"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Persist a CloudOptix billing scan and analysis into SQLite.")
    parser.add_argument("--billing-file", type=Path, default=DEFAULT_BILLING_PATH, help="Billing JSON file to persist.")
    parser.add_argument("--db-file", type=Path, default=DEFAULT_DB_PATH, help="SQLite database file.")
    return parser.parse_args()


def resolve_path(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


def main() -> None:
    args = parse_args()
    billing_path = resolve_path(args.billing_file)
    db_path = resolve_path(args.db_file)

    billing_data = analyze_billing.load_billing_data(billing_path)
    analysis = analyze_billing.analyze_billing_data(billing_data)

    engine = persistence.make_engine(db_path)
    persistence.create_schema(engine)
    SessionLocal = persistence.session_factory(engine)
    with SessionLocal() as session:
        scan = persistence.persist_scan(session, billing_data, analysis)
        counts = persistence.scan_counts(session, scan.id)

    print(f"Persisted scan {scan.report_id} to {db_path}")
    print(
        "Rows: "
        f"instances={counts['instances']}, "
        f"metrics={counts['metrics']}, "
        f"recommendations={counts['recommendations']}, "
        f"action_plans={counts['action_plans']}, "
        f"approvals={counts['approvals']}"
    )


if __name__ == "__main__":
    main()
