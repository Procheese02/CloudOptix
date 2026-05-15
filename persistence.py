import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    func,
    select,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

import analyze_billing

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_DB_PATH = PROJECT_ROOT / "cloudoptix.db"


class Base(DeclarativeBase):
    metadata = MetaData()


class Scan(Base):
    __tablename__ = "scans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_id: Mapped[str] = mapped_column(String(160), nullable=False, unique=True, index=True)
    source: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    generated_at: Mapped[str | None] = mapped_column(String(80))
    resource_type: Mapped[str | None] = mapped_column(String(80))
    primary_region: Mapped[str | None] = mapped_column(String(80), index=True)
    fleet_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_monthly_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    estimated_monthly_savings: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    savings_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    eligible_candidate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    protected_low_utilization_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    missing_metrics_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metrics_coverage: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    raw_billing_json: Mapped[str] = mapped_column(Text, nullable=False)
    analysis_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))

    instances: Mapped[list["InstanceSnapshot"]] = relationship(back_populates="scan", cascade="all, delete-orphan")
    metrics: Mapped[list["MetricSnapshot"]] = relationship(back_populates="scan", cascade="all, delete-orphan")
    recommendations: Mapped[list["Recommendation"]] = relationship(back_populates="scan", cascade="all, delete-orphan")
    action_plans: Mapped[list["ActionPlan"]] = relationship(back_populates="scan", cascade="all, delete-orphan")
    approvals: Mapped[list["Approval"]] = relationship(back_populates="scan", cascade="all, delete-orphan")


class InstanceSnapshot(Base):
    __tablename__ = "instances"
    __table_args__ = (
        UniqueConstraint("scan_id", "instance_id", name="uq_instances_scan_instance"),
        Index("ix_instances_scan_owner_service_env", "scan_id", "owner", "service", "environment"),
        Index("ix_instances_scan_business_unit", "scan_id", "business_unit"),
        Index("ix_instances_scan_region", "scan_id", "region"),
        Index("ix_instances_scan_pricing_model", "scan_id", "pricing_model"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scan_id: Mapped[int] = mapped_column(ForeignKey("scans.id", ondelete="CASCADE"), nullable=False)
    instance_id: Mapped[str] = mapped_column(String(120), nullable=False)
    instance_type: Mapped[str] = mapped_column(String(80), nullable=False)
    monthly_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    environment: Mapped[str] = mapped_column(String(80), nullable=False, default=analyze_billing.UNKNOWN)
    owner: Mapped[str] = mapped_column(String(120), nullable=False, default=analyze_billing.UNKNOWN)
    business_unit: Mapped[str] = mapped_column(String(120), nullable=False, default=analyze_billing.UNKNOWN)
    service: Mapped[str] = mapped_column(String(120), nullable=False, default=analyze_billing.UNKNOWN)
    criticality: Mapped[str] = mapped_column(String(80), nullable=False, default=analyze_billing.UNKNOWN)
    region: Mapped[str] = mapped_column(String(80), nullable=False, default=analyze_billing.UNKNOWN)
    pricing_model: Mapped[str] = mapped_column(String(80), nullable=False, default=analyze_billing.UNKNOWN)
    utilization_pattern: Mapped[str] = mapped_column(String(80), nullable=False, default=analyze_billing.UNKNOWN)
    workload: Mapped[str] = mapped_column(String(120), nullable=False, default=analyze_billing.UNKNOWN)
    protected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    do_not_touch_reason: Mapped[str | None] = mapped_column(Text)
    temporary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    autoscaling_group: Mapped[str | None] = mapped_column(String(160))
    raw_json: Mapped[str] = mapped_column(Text, nullable=False)

    scan: Mapped[Scan] = relationship(back_populates="instances")
    metrics: Mapped["MetricSnapshot"] = relationship(back_populates="instance", cascade="all, delete-orphan")
    recommendations: Mapped[list["Recommendation"]] = relationship(back_populates="instance")
    action_plans: Mapped[list["ActionPlan"]] = relationship(back_populates="instance")


class MetricSnapshot(Base):
    __tablename__ = "metrics"
    __table_args__ = (
        UniqueConstraint("scan_id", "instance_snapshot_id", name="uq_metrics_scan_instance"),
        Index("ix_metrics_scan_complete", "scan_id", "has_complete_metrics"),
        Index("ix_metrics_scan_source", "scan_id", "metrics_source"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scan_id: Mapped[int] = mapped_column(ForeignKey("scans.id", ondelete="CASCADE"), nullable=False)
    instance_snapshot_id: Mapped[int] = mapped_column(ForeignKey("instances.id", ondelete="CASCADE"), nullable=False)
    metrics_source: Mapped[str] = mapped_column(String(80), nullable=False, default=analyze_billing.UNKNOWN)
    avg_cpu_utilization: Mapped[float | None] = mapped_column(Float)
    peak_cpu_utilization: Mapped[float | None] = mapped_column(Float)
    avg_memory_utilization: Mapped[float | None] = mapped_column(Float)
    avg_network_mbps: Mapped[float | None] = mapped_column(Float)
    peak_network_mbps: Mapped[float | None] = mapped_column(Float)
    has_complete_metrics: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    raw_json: Mapped[str] = mapped_column(Text, nullable=False)

    scan: Mapped[Scan] = relationship(back_populates="metrics")
    instance: Mapped[InstanceSnapshot] = relationship(back_populates="metrics")


class Recommendation(Base):
    __tablename__ = "recommendations"
    __table_args__ = (
        UniqueConstraint("scan_id", "instance_snapshot_id", name="uq_recommendations_scan_instance"),
        Index("ix_recommendations_scan_owner", "scan_id", "owner"),
        Index("ix_recommendations_scan_savings", "scan_id", "estimated_monthly_savings"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scan_id: Mapped[int] = mapped_column(ForeignKey("scans.id", ondelete="CASCADE"), nullable=False)
    instance_snapshot_id: Mapped[int] = mapped_column(ForeignKey("instances.id", ondelete="CASCADE"), nullable=False)
    instance_id: Mapped[str] = mapped_column(String(120), nullable=False)
    owner: Mapped[str] = mapped_column(String(120), nullable=False, default=analyze_billing.UNKNOWN)
    business_unit: Mapped[str] = mapped_column(String(120), nullable=False, default=analyze_billing.UNKNOWN)
    service: Mapped[str] = mapped_column(String(120), nullable=False, default=analyze_billing.UNKNOWN)
    environment: Mapped[str] = mapped_column(String(80), nullable=False, default=analyze_billing.UNKNOWN)
    region: Mapped[str] = mapped_column(String(80), nullable=False, default=analyze_billing.UNKNOWN)
    current_type: Mapped[str] = mapped_column(String(80), nullable=False)
    target_type: Mapped[str] = mapped_column(String(80), nullable=False)
    monthly_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    estimated_monthly_savings: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    risk_level: Mapped[str] = mapped_column(String(80), nullable=False, default="low")
    status: Mapped[str] = mapped_column(String(80), nullable=False, default="proposed")
    raw_json: Mapped[str] = mapped_column(Text, nullable=False)

    scan: Mapped[Scan] = relationship(back_populates="recommendations")
    instance: Mapped[InstanceSnapshot] = relationship(back_populates="recommendations")
    action_plans: Mapped[list["ActionPlan"]] = relationship(back_populates="recommendation")


class ActionPlan(Base):
    __tablename__ = "action_plans"
    __table_args__ = (
        UniqueConstraint("scan_id", "recommendation_id", name="uq_action_plans_scan_recommendation"),
        Index("ix_action_plans_scan_mode", "scan_id", "mode"),
        Index("ix_action_plans_scan_status", "scan_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scan_id: Mapped[int] = mapped_column(ForeignKey("scans.id", ondelete="CASCADE"), nullable=False)
    instance_snapshot_id: Mapped[int] = mapped_column(ForeignKey("instances.id", ondelete="CASCADE"), nullable=False)
    recommendation_id: Mapped[int] = mapped_column(ForeignKey("recommendations.id", ondelete="CASCADE"), nullable=False)
    instance_id: Mapped[str] = mapped_column(String(120), nullable=False)
    mode: Mapped[str] = mapped_column(String(40), nullable=False, default="dry-run")
    status: Mapped[str] = mapped_column(String(80), nullable=False, default="planned")
    planned_steps_json: Mapped[str] = mapped_column(Text, nullable=False)
    raw_json: Mapped[str] = mapped_column(Text, nullable=False)

    scan: Mapped[Scan] = relationship(back_populates="action_plans")
    instance: Mapped[InstanceSnapshot] = relationship(back_populates="action_plans")
    recommendation: Mapped[Recommendation] = relationship(back_populates="action_plans")


class Approval(Base):
    __tablename__ = "approvals"
    __table_args__ = (
        Index("ix_approvals_scan_status", "scan_id", "status"),
        Index("ix_approvals_action_plan_status", "action_plan_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scan_id: Mapped[int] = mapped_column(ForeignKey("scans.id", ondelete="CASCADE"), nullable=False)
    action_plan_id: Mapped[int] = mapped_column(ForeignKey("action_plans.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(80), nullable=False, default="pending")
    requested_by: Mapped[str | None] = mapped_column(String(120))
    decided_by: Mapped[str | None] = mapped_column(String(120))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str | None] = mapped_column(Text)
    raw_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    scan: Mapped[Scan] = relationship(back_populates="approvals")


def json_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def make_engine(db_path: Path | str = DEFAULT_DB_PATH) -> Engine:
    return create_engine(f"sqlite:///{Path(db_path)}", future=True)


def create_schema(engine: Engine) -> None:
    Base.metadata.create_all(engine)


def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, future=True)


def _report_id(billing_data: dict[str, Any]) -> str:
    report_id = str(billing_data.get("report_id") or "").strip()
    if report_id:
        return report_id
    generated_at = str(billing_data.get("generated_at") or "unknown-time")
    return f"local-scan-{generated_at}"


def _source_name(billing_data: dict[str, Any]) -> str:
    return str(billing_data.get("source", {}).get("name") or "mock_or_local_json")


def _metric_float(metrics: dict[str, Any], field: str) -> float | None:
    value = metrics.get(field)
    if field.endswith("_utilization"):
        return analyze_billing.parse_percent(value)
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _planned_steps(recommendation: dict[str, Any]) -> list[str]:
    return [
        f"stop instance {recommendation['instance_id']}",
        f"modify instance type from {recommendation['current_type']} to {recommendation['target_type']}",
        f"start instance {recommendation['instance_id']}",
    ]


def persist_scan(session: Session, billing_data: dict[str, Any], analysis: dict[str, Any]) -> Scan:
    report_id = _report_id(billing_data)
    existing_scan = session.scalar(select(Scan).where(Scan.report_id == report_id))
    if existing_scan is not None:
        session.delete(existing_scan)
        session.flush()

    enterprise = analysis.get("enterprise_summary", {})
    savings = enterprise.get("enterprise_savings_summary", {})
    coverage = enterprise.get("missing_metrics_coverage", {})

    scan = Scan(
        report_id=report_id,
        source=_source_name(billing_data),
        generated_at=billing_data.get("generated_at"),
        resource_type=billing_data.get("resource_type"),
        primary_region=billing_data.get("region"),
        fleet_size=int(analysis.get("fleet_size", 0) or 0),
        total_monthly_cost=float(savings.get("total_monthly_cost", 0) or 0),
        estimated_monthly_savings=float(savings.get("estimated_monthly_savings", 0) or 0),
        savings_rate=float(savings.get("savings_rate", 0) or 0),
        eligible_candidate_count=int(savings.get("eligible_candidate_count", 0) or 0),
        protected_low_utilization_count=int(savings.get("protected_low_utilization_count", 0) or 0),
        missing_metrics_count=int(coverage.get("missing_metrics_count", 0) or 0),
        metrics_coverage=float(coverage.get("coverage", 0) or 0),
        raw_billing_json=json_dumps(billing_data),
        analysis_json=json_dumps(analysis),
    )
    session.add(scan)
    session.flush()

    instances_by_id: dict[str, InstanceSnapshot] = {}
    for instance in analyze_billing.get_instances(billing_data):
        instance_id = str(instance.get("instance_id") or "unknown")
        snapshot = InstanceSnapshot(
            scan_id=scan.id,
            instance_id=instance_id,
            instance_type=str(instance.get("instance_type") or analyze_billing.UNKNOWN),
            monthly_cost=analyze_billing.monthly_cost(instance),
            environment=analyze_billing.field_value(instance, "environment"),
            owner=analyze_billing.field_value(instance, "owner"),
            business_unit=analyze_billing.field_value(instance, "business_unit"),
            service=analyze_billing.field_value(instance, "service"),
            criticality=analyze_billing.field_value(instance, "criticality"),
            region=analyze_billing.field_value(instance, "region"),
            pricing_model=analyze_billing.field_value(instance, "pricing_model"),
            utilization_pattern=analyze_billing.field_value(instance, "utilization_pattern"),
            workload=analyze_billing.field_value(instance, "workload"),
            protected=bool(instance.get("protected")),
            do_not_touch_reason=instance.get("do_not_touch_reason"),
            temporary=bool(instance.get("temporary")),
            autoscaling_group=instance.get("autoscaling_group"),
            raw_json=json_dumps(instance),
        )
        session.add(snapshot)
        session.flush()
        instances_by_id[instance_id] = snapshot

        metrics = instance.get("metrics") if isinstance(instance.get("metrics"), dict) else {}
        session.add(MetricSnapshot(
            scan_id=scan.id,
            instance_snapshot_id=snapshot.id,
            metrics_source=str(instance.get("metrics_source") or analyze_billing.UNKNOWN),
            avg_cpu_utilization=_metric_float(metrics, "avg_cpu_utilization"),
            peak_cpu_utilization=_metric_float(metrics, "peak_cpu_utilization"),
            avg_memory_utilization=_metric_float(metrics, "avg_memory_utilization"),
            avg_network_mbps=_metric_float(metrics, "avg_network_mbps"),
            peak_network_mbps=_metric_float(metrics, "peak_network_mbps"),
            has_complete_metrics=analyze_billing.has_complete_metrics(instance),
            raw_json=json_dumps(metrics),
        ))

    recommendations = analyze_billing.savings_candidates(billing_data, analyze_billing.get_instances(billing_data))
    for recommendation_data in recommendations:
        instance_id = str(recommendation_data.get("instance_id") or "unknown")
        instance_snapshot = instances_by_id.get(instance_id)
        if instance_snapshot is None:
            continue

        recommendation = Recommendation(
            scan_id=scan.id,
            instance_snapshot_id=instance_snapshot.id,
            instance_id=instance_id,
            owner=str(recommendation_data.get("owner") or analyze_billing.UNKNOWN),
            business_unit=str(recommendation_data.get("business_unit") or analyze_billing.UNKNOWN),
            service=str(recommendation_data.get("service") or analyze_billing.UNKNOWN),
            environment=str(recommendation_data.get("environment") or analyze_billing.UNKNOWN),
            region=str(recommendation_data.get("region") or analyze_billing.UNKNOWN),
            current_type=str(recommendation_data.get("current_type") or analyze_billing.UNKNOWN),
            target_type=str(recommendation_data.get("target_type") or analyze_billing.UNKNOWN),
            monthly_cost=float(recommendation_data.get("monthly_cost", 0) or 0),
            estimated_monthly_savings=float(recommendation_data.get("estimated_monthly_savings", 0) or 0),
            risk_level=str(recommendation_data.get("risk_level") or "low"),
            raw_json=json_dumps(recommendation_data),
        )
        session.add(recommendation)
        session.flush()

        action_plan_payload = {
            "instance_id": instance_id,
            "mode": "dry-run",
            "status": "planned",
            "planned_steps": _planned_steps(recommendation_data),
        }
        session.add(ActionPlan(
            scan_id=scan.id,
            instance_snapshot_id=instance_snapshot.id,
            recommendation_id=recommendation.id,
            instance_id=instance_id,
            mode="dry-run",
            status="planned",
            planned_steps_json=json_dumps(action_plan_payload["planned_steps"]),
            raw_json=json_dumps(action_plan_payload),
        ))

    session.commit()
    session.refresh(scan)
    return scan


def persist_billing_scan(db_path: Path | str, billing_data: dict[str, Any]) -> Scan:
    analysis = analyze_billing.analyze_billing_data(billing_data)
    engine = make_engine(db_path)
    create_schema(engine)
    SessionLocal = session_factory(engine)
    with SessionLocal() as session:
        return persist_scan(session, billing_data, analysis)


def scan_counts(session: Session, scan_id: int) -> dict[str, int]:
    return {
        "instances": session.scalar(select(func.count()).select_from(InstanceSnapshot).where(InstanceSnapshot.scan_id == scan_id)) or 0,
        "metrics": session.scalar(select(func.count()).select_from(MetricSnapshot).where(MetricSnapshot.scan_id == scan_id)) or 0,
        "recommendations": session.scalar(select(func.count()).select_from(Recommendation).where(Recommendation.scan_id == scan_id)) or 0,
        "action_plans": session.scalar(select(func.count()).select_from(ActionPlan).where(ActionPlan.scan_id == scan_id)) or 0,
        "approvals": session.scalar(select(func.count()).select_from(Approval).where(Approval.scan_id == scan_id)) or 0,
    }
