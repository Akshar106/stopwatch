variable "name_prefix" {
  description = "Resource name prefix, e.g. \"stopwatch-prod\". Also the schedule-group name."
  type        = string
}

variable "schedules" {
  description = <<-EOT
    Schedules keyed by function key. Each targets a Lambda alias ARN.
    expression: rate(...) or cron(...) (EventBridge Scheduler syntax).
    timezone:   IANA zone for cron expressions (ignored by rate expressions). Cron jobs use
                America/New_York so "03:30" means MBTA local time across DST changes.
    enabled:    false creates the schedule in the DISABLED state (staging ingest).
    retry_attempts / max_event_age_s: Scheduler retries cover *delivery* failures (throttling,
                service errors). Function errors are retried by Lambda's async config instead.
  EOT
  type = map(object({
    target_arn      = string
    expression      = string
    timezone        = optional(string, "America/New_York")
    enabled         = optional(bool, true)
    description     = optional(string, "")
    input           = optional(string, "{}")
    retry_attempts  = optional(number, 2)
    max_event_age_s = optional(number, 3600)
  }))
}

variable "permissions_boundary_arn" {
  description = "Permissions boundary for the Scheduler execution role. null = none."
  type        = string
  default     = null
}
