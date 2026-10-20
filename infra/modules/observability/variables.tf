variable "name_prefix" {
  description = "Resource name prefix, e.g. \"stopwatch-prod\"."
  type        = string
}

variable "alert_email" {
  description = "Operator address subscribed to the alerts topic. AWS emails a confirmation link that must be clicked once."
  type        = string
}

variable "create_alarms" {
  description = "Create the 10 CloudWatch alarms. The free tier is 10 alarms per *account*, so only one environment (prod) should have them on by default."
  type        = bool
  default     = true
}

variable "create_dashboards" {
  description = "Create the 3 dashboards. The free tier is 3 dashboards per account; each extra one is $3/month."
  type        = bool
  default     = true
}

variable "ingest_enabled" {
  description = "Whether the ingest schedule is on. When off, a silent pipeline is expected, so IngestStale treats missing data as OK."
  type        = bool
}

variable "metric_namespace" {
  description = "Namespace of the application's EMF metrics (docs/06 §8)."
  type        = string
  default     = "Stopwatch"
}

variable "metric_dimensions" {
  description = "Exact dimension set the application emits with every custom metric. Alarms match it exactly, so it must stay in sync with stopwatch.platform.observability."
  type        = map(string)
}

variable "function_names" {
  description = "Lambda function names keyed by entry point (api, ingest-tick, schedule-import, daily-rollup, maintenance, notify, lamp-validate)."
  type        = map(string)
}

variable "api_id" {
  description = "HTTP API id (AWS/ApiGateway dimension ApiId)."
  type        = string
}

variable "api_access_log_group_name" {
  description = "API Gateway access-log group (dashboard Logs Insights widgets)."
  type        = string
}

variable "distribution_id" {
  description = "CloudFront distribution id (dashboard widgets)."
  type        = string
}

variable "notify_dlq_name" {
  description = "Name of the notify on-failure queue, for the NotifyDLQ alarm. null = skip that alarm."
  type        = string
  default     = null
}
