# Prod: ingest on, data protected (no force_destroy), and the account's free-tier monitoring quota
# (10 alarms, 3 dashboards) plus the account-wide budgets live here.

# --- Identity / tagging ----------------------------------------------------------------------------

variable "env" {
  description = "Environment name; drives every resource name (stopwatch-<env>-*) and the SSM path."
  type        = string
  default     = "prod"

  validation {
    condition     = contains(["staging", "prod"], var.env)
    error_message = "env must be staging or prod."
  }
}

variable "region" {
  description = "AWS region. CloudFront certificates and billing metrics require us-east-1 anyway."
  type        = string
  default     = "us-east-1"
}

variable "owner" {
  description = "owner tag on every resource."
  type        = string
}

variable "ttl" {
  description = "ttl tag: a date after which this environment may be torn down, or \"none\"."
  type        = string
  default     = "none"
}

variable "github_repo" {
  description = "owner/name of the GitHub repository (runbook links in alarm descriptions)."
  type        = string
}

variable "alert_email" {
  description = "Operator email for alarms and budgets (SNS subscription must be confirmed once). Personal data: pass via TF_VAR_alert_email or an uncommitted tfvars file."
  type        = string
}

# --- Application configuration (Lambda environment) ------------------------------------------------

variable "app_version" {
  description = "STOPWATCH_VERSION (git SHA), shown by /api/v1/healthz."
  type        = string
  default     = "dev"
}

variable "agencies" {
  description = "Agency ids to ingest (stopwatch.platform.agencies)."
  type        = list(string)
  default     = ["mbta"]
}

variable "ingest_enabled" {
  description = "Run the per-minute ingest schedule. Observations cannot be collected retroactively, so prod keeps it on."
  type        = bool
  default     = true
}

variable "alerts_enabled" {
  description = "ALERTS_ENABLED feature flag (turned on per rollout, docs/06 §6)."
  type        = bool
  default     = false
}

variable "ask_enabled" {
  description = "ASK_ENABLED feature flag (turned on per rollout, docs/06 §6)."
  type        = bool
  default     = false
}

variable "demo_enabled" {
  description = "DEMO_ENABLED feature flag."
  type        = bool
  default     = true
}

variable "ask_monthly_cap_usd" {
  description = "Global monthly LLM spend cap for Ask (docs/06 §6)."
  type        = number
  default     = 1.0
}

variable "log_level" {
  description = "LOG_LEVEL for all functions."
  type        = string
  default     = "INFO"
}

# --- Artifacts -------------------------------------------------------------------------------------

variable "api_package_path" {
  description = "Path to api.zip built by scripts/package_lambda.sh."
  type        = string
  default     = "../../../dist/api.zip"
}

variable "jobs_package_path" {
  description = "Path to jobs.zip built by scripts/package_lambda.sh."
  type        = string
  default     = "../../../dist/jobs.zip"
}

variable "api_package_sha256" {
  description = "base64(sha256(api.zip)); CI passes the hash of the artifact it built once. null = hash the file."
  type        = string
  default     = null
}

variable "jobs_package_sha256" {
  description = "base64(sha256(jobs.zip)); see api_package_sha256."
  type        = string
  default     = null
}

# --- Storage / edge --------------------------------------------------------------------------------

variable "bucket_suffix" {
  description = "Suffix for bucket names if stopwatch-<env>-* is taken in the global S3 namespace."
  type        = string
  default     = ""
}

variable "force_destroy" {
  description = "Let `make down` delete non-empty buckets. false in prod: curated data and backups are not reproducible. `make down ENV=prod ALLOW_DATA_DESTROY=1` flips it deliberately."
  type        = bool
  default     = false
}

variable "domain_aliases" {
  description = "Optional custom domain(s) for CloudFront. Default: the free *.cloudfront.net name."
  type        = list(string)
  default     = []
}

variable "acm_certificate_arn" {
  description = "ACM certificate in us-east-1 for domain_aliases."
  type        = string
  default     = null
}

variable "use_permissions_boundary" {
  description = "Attach the bootstrap-created boundary (stopwatch-boundary-<env>) to every role. Required when deploying with the GitHub deploy role."
  type        = bool
  default     = true
}

# --- Monitoring and cost guardrails ----------------------------------------------------------------

variable "reserve_concurrency" {
  description = "Give every function its reserved concurrency (the per-function caps in main.tf). false = unreserved (-1), bounded only by the account limit: for a new account whose limit is still 10, where AWS keeps 10 unreserved and no function can reserve any until the quota increase is approved."
  type        = bool
  default     = true
}

variable "create_alarms" {
  description = "The 10 CloudWatch alarms of docs/06 §9 (exactly the account's free tier)."
  type        = bool
  default     = true
}

variable "create_dashboards" {
  description = "The 3 CloudWatch dashboards (exactly the account's free tier)."
  type        = bool
  default     = true
}

variable "create_budgets" {
  description = "AWS Budgets: $1 actual / $5 forecast."
  type        = bool
  default     = true
}

variable "budget_scope_to_env" {
  description = "Filter budgets to env=<env>. false (default) = whole account, so staging and anything forgotten are covered too."
  type        = bool
  default     = false
}
