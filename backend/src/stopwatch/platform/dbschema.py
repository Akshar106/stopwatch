"""SQLAlchemy Core table definitions mirroring migrations/versions/0001_initial_schema.py.

The migration is the source of truth for DDL (constraints, indexes, grants). These Table objects exist so
queries are composed with bound parameters, never string formatting.
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    Integer,
    LargeBinary,
    MetaData,
    Numeric,
    SmallInteger,
    String,
    Table,
    Text,
    Time,
    func,
)
from sqlalchemy.dialects.postgresql import CITEXT, INET, JSONB, UUID

metadata = MetaData()

users = Table(
    "users", metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()),
    Column("email", CITEXT, unique=True),
    Column("display_name", Text),
    Column("oidc_issuer", Text),
    Column("oidc_subject", Text),
    Column("is_demo", Boolean, nullable=False, server_default="false"),
    Column("demo_expires_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("last_login_at", DateTime(timezone=True)),
)

sessions = Table(
    "sessions", metadata,
    Column("token_hash", LargeBinary, primary_key=True),
    Column("user_id", UUID(as_uuid=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("last_seen_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("ip_prefix", INET),
    Column("user_agent", Text),
)

agencies = Table(
    "agencies", metadata,
    Column("id", Text, primary_key=True),
    Column("name", Text, nullable=False),
    Column("timezone", Text, nullable=False),
    Column("on_time_early_s", SmallInteger, nullable=False, server_default="-60"),
    Column("on_time_late_s", SmallInteger, nullable=False, server_default="300"),
)

feed_versions = Table(
    "feed_versions", metadata,
    Column("agency_id", Text, primary_key=True),
    Column("version", Text, primary_key=True),
    Column("imported_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("start_date", Date, nullable=False),
    Column("end_date", Date, nullable=False),
)

routes = Table(
    "routes", metadata,
    Column("agency_id", Text, primary_key=True),
    Column("route_id", Text, primary_key=True),
    Column("short_name", Text),
    Column("long_name", Text),
    Column("route_type", SmallInteger, nullable=False),
    Column("color", Text),
    Column("text_color", Text),
    Column("sort_order", Integer),
)

stops = Table(
    "stops", metadata,
    Column("agency_id", Text, primary_key=True),
    Column("stop_id", Text, primary_key=True),
    Column("name", Text, nullable=False),
    Column("lat", Float, nullable=False),
    Column("lon", Float, nullable=False),
    Column("parent_station", Text),
)

route_stops = Table(
    "route_stops", metadata,
    Column("agency_id", Text, primary_key=True),
    Column("route_id", Text, primary_key=True),
    Column("direction_id", SmallInteger, primary_key=True),
    Column("stop_id", Text, primary_key=True),
    Column("stop_order", SmallInteger, nullable=False),
)

saved_commutes = Table(
    "saved_commutes", metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()),
    Column("user_id", UUID(as_uuid=True), nullable=False),
    Column("agency_id", Text, nullable=False),
    Column("route_id", Text, nullable=False),
    Column("direction_id", SmallInteger, nullable=False),
    Column("stop_id", Text, nullable=False),
    Column("label", Text),
    Column("days_mask", SmallInteger, nullable=False),
    Column("window_start", Time, nullable=False),
    Column("window_end", Time, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

idempotency_keys = Table(
    "idempotency_keys", metadata,
    Column("user_id", UUID(as_uuid=True), primary_key=True),
    Column("key", Text, primary_key=True),
    Column("request_hash", LargeBinary, nullable=False),
    Column("status_code", SmallInteger, nullable=False),
    Column("response", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

rate_limit_counters = Table(
    "rate_limit_counters", metadata,
    Column("bucket", Text, primary_key=True),
    Column("window_start", DateTime(timezone=True), primary_key=True),
    Column("count", Integer, nullable=False),
)

audit_log = Table(
    "audit_log", metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("actor_kind", Text, nullable=False),
    Column("actor_user_id", UUID(as_uuid=True)),
    Column("action", Text, nullable=False),
    Column("target_kind", Text),
    Column("target_id", Text),
    Column("outcome", Text, nullable=False),
    Column("request_id", Text),
    Column("ip_prefix", INET),
    Column("details", JSONB, nullable=False, server_default="{}"),
)

route_daily_metrics = Table(
    "route_daily_metrics", metadata,
    Column("agency_id", Text, primary_key=True),
    Column("route_id", Text, primary_key=True),
    Column("direction_id", SmallInteger, primary_key=True),
    Column("service_date", Date, primary_key=True),
    Column("trips_scheduled", Integer, nullable=False),
    Column("trips_observed", Integer, nullable=False),
    Column("trips_canceled", Integer, nullable=False),
    Column("on_time_pct", Numeric(5, 2)),
    Column("median_delay_s", Integer),
    Column("p90_delay_s", Integer),
    Column("excess_wait_s", Integer),
)

push_subscriptions = Table(
    "push_subscriptions", metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()),
    Column("user_id", UUID(as_uuid=True), nullable=False),
    Column("endpoint", Text, nullable=False, unique=True),
    Column("p256dh", Text, nullable=False),
    Column("auth_secret", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("last_success_at", DateTime(timezone=True)),
)

alert_rules = Table(
    "alert_rules", metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()),
    Column("commute_id", UUID(as_uuid=True), nullable=False, unique=True),
    Column("threshold_min", SmallInteger, nullable=False),
    Column("notify_cancellations", Boolean, nullable=False, server_default="true"),
    Column("active", Boolean, nullable=False, server_default="true"),
)

notifications = Table(
    "notifications", metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()),
    Column("alert_rule_id", UUID(as_uuid=True), nullable=False),
    Column("dedupe_key", Text, nullable=False, unique=True),
    Column("status", String, nullable=False),
    Column("attempts", SmallInteger, nullable=False, server_default="0"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("sent_at", DateTime(timezone=True)),
    Column("last_error", Text),
)

ask_usage = Table(
    "ask_usage", metadata,
    Column("user_id", UUID(as_uuid=True), primary_key=True),
    Column("day", Date, primary_key=True),
    Column("requests", Integer, nullable=False),
    Column("cost_microusd", BigInteger, nullable=False),
)

__all__ = [
    "agencies", "alert_rules", "ask_usage", "audit_log", "feed_versions", "idempotency_keys", "metadata",
    "notifications", "push_subscriptions", "rate_limit_counters", "route_daily_metrics", "route_stops",
    "routes", "saved_commutes", "sessions", "stops", "users",
]
