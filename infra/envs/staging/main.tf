# Stopwatch environment root (docs/04 §4, docs/06 §4).
#
# This file is IDENTICAL in envs/staging and envs/prod (CI diffs them). Everything that differs
# between environments lives in variables.tf defaults, terraform.tfvars / TF_VAR_* and backend.tf.
#
#   storage ──► edge (CloudFront) ◄── api (HTTP API) ◄── functions["api"]
#      ▲                                                   functions[jobs] ◄── scheduler
#      └── secrets (SSM), observability (SNS, alarms, dashboards), budget
#
# Cost posture ($0 when idle): no VPC/NAT/ALB/RDS, scale-to-zero compute, reserved-concurrency caps
# on every function, 14-day logs, S3 lifecycle rules, everything tagged project/env/owner/ttl.

terraform {
  required_version = ">= 1.11" # write-only SSM values (modules/secrets)

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      project = "stopwatch"
      env     = var.env
      owner   = var.owner
      ttl     = var.ttl
    }
  }
}

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  name_prefix = "stopwatch-${var.env}"
  ssm_prefix  = "/stopwatch/${var.env}"
  account_id  = data.aws_caller_identity.current.account_id
  partition   = data.aws_partition.current.partition

  # Created by infra/bootstrap (modules/github_oidc). Every role this root creates carries it.
  permissions_boundary_arn = var.use_permissions_boundary ? "arn:${local.partition}:iam::${local.account_id}:policy/stopwatch-boundary-${var.env}" : null

  # Powertools Metrics(service="stopwatch") adds a `service` dimension next to `env`
  # (stopwatch.platform.observability). Alarms must match the emitted dimension set exactly.
  metric_dimensions = { env = var.env, service = "stopwatch" }

  # --- Packages: one upload per zip, content-addressed ------------------------------------------
  # Hashes come from scripts/package_lambda.sh (dist/*.base64sha256) via -var in CI and make;
  # without them, fall back to hashing the file. "unbuilt" only matters for plan/destroy without zips.
  packages = {
    api  = { path = var.api_package_path, sha = coalesce(var.api_package_sha256, try(filebase64sha256(var.api_package_path), "unbuilt")) }
    jobs = { path = var.jobs_package_path, sha = coalesce(var.jobs_package_sha256, try(filebase64sha256(var.jobs_package_path), "unbuilt")) }
  }
  package_keys = { for k, p in local.packages : k => "lambda/${k}/${replace(replace(replace(p.sha, "+", "-"), "/", "_"), "=", "")}.zip" }

  lake = module.storage.lake_bucket_arn
  site = module.storage.site_bucket_arn

  notify_function_arn = "arn:${local.partition}:lambda:${var.region}:${local.account_id}:function:${local.name_prefix}-notify"

  # Environment shared by every function (docs/contracts.md §1).
  common_env = {
    STOPWATCH_ENV                = var.env
    STOPWATCH_VERSION            = var.app_version
    LAKE_URL                     = "s3://${module.storage.lake_bucket_name}"
    SITE_URL                     = "s3://${module.storage.site_bucket_name}"
    AGENCIES                     = join(",", var.agencies)
    PUBLIC_BASE_URL              = module.edge.public_base_url
    INGEST_ENABLED               = tostring(var.ingest_enabled)
    ALERTS_ENABLED               = tostring(var.alerts_enabled)
    ASK_ENABLED                  = tostring(var.ask_enabled)
    DEMO_ENABLED                 = tostring(var.demo_enabled)
    ASK_MONTHLY_CAP_USD          = tostring(var.ask_monthly_cap_usd)
    POWERTOOLS_SERVICE_NAME      = "stopwatch"
    POWERTOOLS_METRICS_NAMESPACE = "Stopwatch"
    LOG_LEVEL                    = var.log_level
    # libpq's CA bundle for the Neon URLs (sslmode=verify-full): certifi ships in both packages via httpx.
    PGSSLROOTCERT = "/var/task/certifi/cacert.pem"
  }

  # --- Entry points: docs/contracts.md §1 (handler, package, memory/timeout, /tmp, concurrency) ----
  # and its IAM table. `ssm` = may read secrets under SSM_PREFIX; SSM_PREFIX is only set when true
  # (ingest-tick holds no database credentials, so its config loader must not try).
  #
  # ListBucket on the lake for readers: without it S3 answers 403 (not 404) for a missing key, and
  # the blobstore only treats 404 as "absent" (first-ever state read, no alert snapshot yet,
  # DuckDB globs). It exposes key names only, never contents.
  functions = {
    api = {
      description = "FastAPI app behind API Gateway (/api/v1)"
      handler     = "stopwatch.api.lambda_handler.handler"
      package     = "api"
      memory      = 512
      timeout     = 15
      tmp         = 512
      concurrency = 10
      ssm         = true
      async       = null
      env         = {}
      statements = [
        { sid = "LakeWriteAlertSnapshot", actions = ["s3:PutObject"], resources = ["${local.lake}/config/alert_rules/*"] },
        { sid = "SiteReadPublishedData", actions = ["s3:GetObject"], resources = ["${local.site}/data/v1/*"] }, # Ask tools
      ]
    }

    ingest-tick = {
      description = "Every minute: poll GTFS-RT, infer arrivals, write events/state/health"
      handler     = "stopwatch.jobs.ingest_tick.handler"
      package     = "jobs"
      memory      = 512
      timeout     = 50
      tmp         = 512
      concurrency = 1 # never two ticks at once (state CAS is the second line of defence)
      ssm         = false
      # A tick never retries past its own minute (docs/05 §10.3): the next tick recovers.
      async = { maximum_retry_attempts = 0, maximum_event_age_in_seconds = 60 }
      # Qualified with the alias so alert delivery follows deploys and rollbacks.
      env = { NOTIFY_FUNCTION_NAME = "${local.name_prefix}-notify:live" }
      statements = [
        { sid = "LakeStateEventsRaw", actions = ["s3:GetObject", "s3:PutObject"], resources = ["${local.lake}/state/*", "${local.lake}/events/*", "${local.lake}/raw/*"] },
        { sid = "LakeReadAlertSnapshot", actions = ["s3:GetObject"], resources = ["${local.lake}/config/alert_rules/*"] },
        { sid = "LakeListForNotFound", actions = ["s3:ListBucket"], resources = [local.lake] },
        { sid = "SitePublishHealth", actions = ["s3:PutObject"], resources = ["${local.site}/data/v1/health/*"] },
        { sid = "InvokeNotify", actions = ["lambda:InvokeFunction"], resources = [local.notify_function_arn, "${local.notify_function_arn}:*"] },
      ]
    }

    schedule-import = {
      description = "Daily 03:30 ET: import MBTA static GTFS if it changed"
      handler     = "stopwatch.jobs.schedule_import.handler"
      package     = "jobs"
      memory      = 1536
      timeout     = 300
      tmp         = 2048
      concurrency = 1
      ssm         = true
      async       = { maximum_retry_attempts = 2, maximum_event_age_in_seconds = 3600 }
      env         = {}
      statements = [
        { sid = "LakeSchedules", actions = ["s3:GetObject", "s3:PutObject"], resources = ["${local.lake}/schedule/*"] },
        { sid = "LakeListForNotFound", actions = ["s3:ListBucket"], resources = [local.lake] },
      ]
    }

    daily-rollup = {
      description = "Daily 04:15 ET: DuckDB rollup of D-1, quality gate, publish build + manifest"
      handler     = "stopwatch.jobs.daily_rollup.handler"
      package     = "jobs"
      memory      = 2048
      timeout     = 600
      tmp         = 4096
      concurrency = 1
      ssm         = true
      async       = { maximum_retry_attempts = 2, maximum_event_age_in_seconds = 3600 }
      env         = {}
      statements = [
        { sid = "LakeRead", actions = ["s3:GetObject"], resources = ["${local.lake}/events/*", "${local.lake}/schedule/*", "${local.lake}/curated/*"] },
        { sid = "LakeWrite", actions = ["s3:PutObject"], resources = ["${local.lake}/curated/*", "${local.lake}/reports/*"] },
        { sid = "SitePublish", actions = ["s3:GetObject", "s3:PutObject"], resources = ["${local.site}/data/v1/*"] },
        { sid = "ListBuckets", actions = ["s3:ListBucket"], resources = [local.lake, local.site] },
      ]
    }

    maintenance = {
      description = "Daily 05:00 ET: purge expired sessions/demo users, reconcile alert snapshot, check backup"
      handler     = "stopwatch.jobs.maintenance.handler"
      package     = "jobs"
      memory      = 256
      timeout     = 120
      tmp         = 512
      concurrency = 1
      ssm         = true
      async       = { maximum_retry_attempts = 0, maximum_event_age_in_seconds = 3600 } # retry next day (docs/04 §9)
      env         = {}
      statements = [
        { sid = "LakeWriteAlertSnapshot", actions = ["s3:PutObject"], resources = ["${local.lake}/config/alert_rules/*"] },
        {
          sid        = "LakeListBackups"
          actions    = ["s3:ListBucket"]
          resources  = [local.lake]
          conditions = [{ test = "StringLike", variable = "s3:prefix", values = ["backups/*"] }]
        },
      ]
    }

    notify = {
      description = "Async from ingest-tick: deliver Web Push alerts (dedupe in Postgres)"
      handler     = "stopwatch.jobs.notify.handler"
      package     = "jobs"
      memory      = 256
      timeout     = 30
      tmp         = 512
      concurrency = 2
      ssm         = true
      # An alert older than 15 minutes is no longer useful; expired events still land in the DLQ.
      async      = { maximum_retry_attempts = 2, maximum_event_age_in_seconds = 900, on_failure_dlq = true }
      env        = { VAPID_SUBJECT = "mailto:${var.alert_email}" }
      statements = []
    }

    lamp-validate = {
      description = "Weekly Mon 06:00 ET: compare inferred arrivals with MBTA LAMP"
      handler     = "stopwatch.jobs.lamp_validate.handler"
      package     = "jobs"
      memory      = 1024
      timeout     = 300
      tmp         = 512
      concurrency = 1
      ssm         = true
      async       = { maximum_retry_attempts = 2, maximum_event_age_in_seconds = 3600 }
      env         = {}
      statements = [
        { sid = "LakeReadCurated", actions = ["s3:GetObject"], resources = ["${local.lake}/curated/*"] },
        { sid = "LakeListForNotFound", actions = ["s3:ListBucket"], resources = [local.lake] },
        { sid = "LakeWriteReport", actions = ["s3:PutObject"], resources = ["${local.lake}/reports/lamp/*"] },
        { sid = "SitePublishValidation", actions = ["s3:PutObject"], resources = ["${local.site}/data/v1/validation/*"] },
      ]
    }
  }

  # --- Schedules: docs/contracts.md §1 "Trigger" column ------------------------------------------
  schedules = {
    ingest-tick = {
      expression      = "rate(1 minute)"
      enabled         = var.ingest_enabled
      description     = "GTFS-RT poll (disabled in staging unless testing)"
      retry_attempts  = 0
      max_event_age_s = 60
    }
    schedule-import = { expression = "cron(30 3 * * ? *)", description = "Static GTFS import, 03:30 ET" }
    daily-rollup    = { expression = "cron(15 4 * * ? *)", description = "Rollup of D-1, 04:15 ET" }
    maintenance     = { expression = "cron(0 5 * * ? *)", description = "Cleanup, 05:00 ET" }
    lamp-validate   = { expression = "cron(0 6 ? * MON *)", description = "LAMP validation, Mondays 06:00 ET" }
  }
}

# --- Storage ---------------------------------------------------------------------------------------

module "storage" {
  source = "../../modules/storage"

  name_prefix           = local.name_prefix
  bucket_suffix         = var.bucket_suffix
  force_destroy         = var.force_destroy
  site_distribution_arn = module.edge.distribution_arn
}

resource "aws_s3_object" "package" {
  #checkov:skip=CKV_AWS_186:Bucket-default SSE-S3 encryption; a customer-managed KMS key costs $1/month.
  for_each = local.packages

  bucket       = module.storage.artifacts_bucket_name
  key          = local.package_keys[each.key]
  source       = each.value.path
  source_hash  = each.value.sha
  content_type = "application/zip"

  lifecycle {
    precondition {
      condition     = fileexists(each.value.path)
      error_message = "Missing ${each.value.path}: run `make package` (scripts/package_lambda.sh) first."
    }
  }
}

# --- Secrets (operator sets values out-of-band; only origin_verify_secret is Terraform-generated) --

module "secrets" {
  source = "../../modules/secrets"

  ssm_prefix = local.ssm_prefix
}

# --- Compute ---------------------------------------------------------------------------------------

module "functions" {
  source   = "../../modules/functions"
  for_each = local.functions

  name_prefix              = local.name_prefix
  function_key             = each.key
  description              = each.value.description
  handler                  = each.value.handler
  package_s3_bucket        = aws_s3_object.package[each.value.package].bucket
  package_s3_key           = aws_s3_object.package[each.value.package].key
  source_code_hash         = local.packages[each.value.package].sha
  memory_mb                = each.value.memory
  timeout_s                = each.value.timeout
  ephemeral_storage_mb     = each.value.tmp
  reserved_concurrency     = var.reserve_concurrency ? each.value.concurrency : -1
  ssm_prefix               = each.value.ssm ? local.ssm_prefix : null
  iam_statements           = each.value.statements
  async_invoke             = each.value.async
  permissions_boundary_arn = local.permissions_boundary_arn

  environment_variables = merge(
    local.common_env,
    each.value.ssm ? { SSM_PREFIX = local.ssm_prefix } : {},
    each.value.env,
  )
}

module "scheduler" {
  source = "../../modules/scheduler"

  name_prefix              = local.name_prefix
  permissions_boundary_arn = local.permissions_boundary_arn
  schedules = {
    for k, s in local.schedules : k => merge(s, { target_arn = module.functions[k].alias_arn })
  }
}

# --- Edge ------------------------------------------------------------------------------------------

module "api" {
  source = "../../modules/api"

  name_prefix      = local.name_prefix
  function_name    = module.functions["api"].function_name
  alias_name       = module.functions["api"].alias_name
  alias_invoke_arn = module.functions["api"].alias_invoke_arn
}

module "edge" {
  source = "../../modules/edge"

  name_prefix                      = local.name_prefix
  site_bucket_regional_domain_name = module.storage.site_bucket_regional_domain_name
  api_domain_name                  = module.api.api_domain_name
  aliases                          = var.domain_aliases
  acm_certificate_arn              = var.acm_certificate_arn
  origin_verify_secret             = module.secrets.origin_verify_secret
}

# --- Operations ------------------------------------------------------------------------------------

module "observability" {
  source = "../../modules/observability"

  name_prefix               = local.name_prefix
  alert_email               = var.alert_email
  create_alarms             = var.create_alarms
  create_dashboards         = var.create_dashboards
  ingest_enabled            = var.ingest_enabled
  metric_dimensions         = local.metric_dimensions
  function_names            = { for k, f in module.functions : k => f.function_name }
  api_id                    = module.api.api_id
  api_access_log_group_name = module.api.access_log_group_name
  distribution_id           = module.edge.distribution_id
  notify_dlq_name           = module.functions["notify"].dlq_name
}

module "budget" {
  source = "../../modules/budget"
  count  = var.create_budgets ? 1 : 0

  name_prefix     = local.name_prefix
  sns_topic_arn   = module.observability.sns_topic_arn
  email_addresses = [var.alert_email]
  cost_filter_tag = var.budget_scope_to_env ? { key = "env", value = var.env } : null
}
