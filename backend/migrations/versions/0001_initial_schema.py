"""Initial schema (docs/04-architecture.md §6.2).

Revision ID: 0001
Revises:
Create Date: 2026-10-18
"""
from __future__ import annotations

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

UPGRADE = r"""
create extension if not exists citext;
create extension if not exists pgcrypto;

create table users (
  id              uuid primary key default gen_random_uuid(),
  email           citext unique,
  display_name    text,
  oidc_issuer     text,
  oidc_subject    text,
  is_demo         boolean not null default false,
  demo_expires_at timestamptz,
  created_at      timestamptz not null default now(),
  last_login_at   timestamptz,
  unique (oidc_issuer, oidc_subject),
  check (is_demo or (oidc_issuer is not null and oidc_subject is not null)),
  check (not is_demo or demo_expires_at is not null)
);

create table sessions (
  token_hash   bytea primary key,
  user_id      uuid not null references users(id) on delete cascade,
  created_at   timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  expires_at   timestamptz not null,
  ip_prefix    inet,
  user_agent   text
);
create index sessions_user_idx on sessions (user_id);
create index sessions_expiry_idx on sessions (expires_at);

create table agencies (
  id              text primary key,
  name            text not null,
  timezone        text not null,
  on_time_early_s smallint not null default -60,
  on_time_late_s  smallint not null default 300
);

create table feed_versions (
  agency_id   text references agencies(id),
  version     text,
  imported_at timestamptz not null default now(),
  start_date  date not null,
  end_date    date not null,
  primary key (agency_id, version)
);

create table routes (
  agency_id  text references agencies(id),
  route_id   text,
  short_name text,
  long_name  text,
  route_type smallint not null,
  color      text,
  text_color text,
  sort_order int,
  primary key (agency_id, route_id)
);

create table stops (
  agency_id      text references agencies(id),
  stop_id        text,
  name           text not null,
  lat            double precision not null,
  lon            double precision not null,
  parent_station text,
  primary key (agency_id, stop_id)
);

create table route_stops (
  agency_id    text,
  route_id     text,
  direction_id smallint check (direction_id in (0, 1)),
  stop_id      text,
  stop_order   smallint not null,
  primary key (agency_id, route_id, direction_id, stop_id),
  foreign key (agency_id, route_id) references routes on delete cascade,
  foreign key (agency_id, stop_id) references stops on delete cascade
);

create table saved_commutes (
  id           uuid primary key default gen_random_uuid(),
  user_id      uuid not null references users(id) on delete cascade,
  agency_id    text not null,
  route_id     text not null,
  direction_id smallint not null check (direction_id in (0, 1)),
  stop_id      text not null,
  label        text check (char_length(label) <= 60),
  days_mask    smallint not null check (days_mask between 1 and 127),
  window_start time not null,
  window_end   time not null,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  check (window_end > window_start)
);
create index saved_commutes_user_idx on saved_commutes (user_id);

create table idempotency_keys (
  user_id      uuid not null references users(id) on delete cascade,
  key          text not null check (char_length(key) between 8 and 64),
  request_hash bytea not null,
  status_code  smallint not null,
  response     jsonb not null,
  created_at   timestamptz not null default now(),
  primary key (user_id, key)
);

create table rate_limit_counters (
  bucket       text not null,
  window_start timestamptz not null,
  count        int not null,
  primary key (bucket, window_start)
);

create table audit_log (
  id            bigint generated always as identity primary key,
  at            timestamptz not null default now(),
  actor_kind    text not null check (actor_kind in ('user', 'system', 'anonymous')),
  actor_user_id uuid,
  action        text not null,
  target_kind   text,
  target_id     text,
  outcome       text not null check (outcome in ('success', 'denied', 'error')),
  request_id    text,
  ip_prefix     inet,
  details       jsonb not null default '{}'
);
create index audit_actor_idx on audit_log (actor_user_id, at desc);
create index audit_at_idx on audit_log (at);

create table route_daily_metrics (
  agency_id       text,
  route_id        text,
  direction_id    smallint,
  service_date    date,
  trips_scheduled int not null,
  trips_observed  int not null,
  trips_canceled  int not null,
  on_time_pct     numeric(5, 2),
  median_delay_s  int,
  p90_delay_s     int,
  excess_wait_s   int,
  primary key (agency_id, route_id, direction_id, service_date)
);

create table push_subscriptions (
  id              uuid primary key default gen_random_uuid(),
  user_id         uuid not null references users(id) on delete cascade,
  endpoint        text not null unique,
  p256dh          text not null,
  auth_secret     text not null,
  created_at      timestamptz not null default now(),
  last_success_at timestamptz
);
create index push_subscriptions_user_idx on push_subscriptions (user_id);

create table alert_rules (
  id                   uuid primary key default gen_random_uuid(),
  commute_id           uuid not null unique references saved_commutes(id) on delete cascade,
  threshold_min        smallint not null check (threshold_min between 3 and 60),
  notify_cancellations boolean not null default true,
  active               boolean not null default true
);

create table notifications (
  id            uuid primary key default gen_random_uuid(),
  alert_rule_id uuid not null references alert_rules(id) on delete cascade,
  dedupe_key    text not null unique,
  status        text not null check (status in ('pending', 'sent', 'failed', 'dropped')),
  attempts      smallint not null default 0,
  created_at    timestamptz not null default now(),
  sent_at       timestamptz,
  last_error    text
);
create index notifications_created_idx on notifications (created_at);

create table ask_usage (
  user_id       uuid references users(id) on delete cascade,
  day           date,
  requests      int not null,
  cost_microusd bigint not null,
  primary key (user_id, day)
);
"""

DOWNGRADE = r"""
drop table if exists ask_usage, notifications, alert_rules, push_subscriptions, route_daily_metrics,
  audit_log, rate_limit_counters, idempotency_keys, saved_commutes, route_stops, stops, routes,
  feed_versions, agencies, sessions, users cascade;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
