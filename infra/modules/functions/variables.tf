variable "name_prefix" {
  description = "Resource name prefix, e.g. \"stopwatch-prod\"."
  type        = string
}

variable "function_key" {
  description = "Entry-point name from docs/contracts.md §1 (api, ingest-tick, ...). The function is <name_prefix>-<function_key>."
  type        = string
}

variable "description" {
  description = "Human-readable description shown in the Lambda console."
  type        = string
  default     = ""
}

variable "handler" {
  description = "Python handler, e.g. stopwatch.jobs.ingest_tick.handler."
  type        = string
}

variable "runtime" {
  description = "Lambda runtime identifier."
  type        = string
  default     = "python3.13"
}

variable "architecture" {
  description = "Instruction set. arm64 (Graviton) is ~20% cheaper per GB-second than x86_64."
  type        = string
  default     = "arm64"
}

variable "package_s3_bucket" {
  description = "Bucket holding the deployment zip (see storage module, artifacts bucket)."
  type        = string
}

variable "package_s3_key" {
  description = "Key of the deployment zip. Content-addressed, so a new build means a new key."
  type        = string
}

variable "source_code_hash" {
  description = "base64(sha256(zip)), as written by scripts/package_lambda.sh to dist/<pkg>.zip.base64sha256."
  type        = string
  default     = null
}

variable "memory_mb" {
  description = "Memory size in MB (CPU scales with it)."
  type        = number
}

variable "timeout_s" {
  description = "Timeout in seconds."
  type        = number
}

variable "ephemeral_storage_mb" {
  description = "/tmp size in MB (512 is free; DuckDB jobs spill to /tmp)."
  type        = number
  default     = 512
}

variable "reserved_concurrency" {
  description = "Reserved concurrency: both a guarantee and a hard cap that bounds the worst-case bill and prevents overlapping ticks. -1 = unreserved."
  type        = number

  validation {
    condition     = var.reserved_concurrency == -1 || var.reserved_concurrency >= 0
    error_message = "reserved_concurrency must be -1 (unreserved) or >= 0."
  }
}

variable "environment_variables" {
  description = "Environment variables (non-secret configuration only; secrets come from SSM at cold start)."
  type        = map(string)
  default     = {}
}

variable "log_retention_days" {
  description = "CloudWatch Logs retention. 14 days keeps us inside the 5 GB free tier and limits personal-data retention."
  type        = number
  default     = 14
}

variable "ssm_prefix" {
  description = "SSM path (e.g. /stopwatch/prod) the function may read with GetParametersByPath. null = no SSM access."
  type        = string
  default     = null
}

variable "iam_statements" {
  description = "Extra least-privilege IAM statements (S3 prefixes, lambda:InvokeFunction, ...)."
  type = list(object({
    sid       = string
    actions   = list(string)
    resources = list(string)
    conditions = optional(list(object({
      test     = string
      variable = string
      values   = list(string)
    })), [])
  }))
  default = []
}

variable "permissions_boundary_arn" {
  description = "Permissions boundary for the execution role (created by infra/bootstrap). null = none."
  type        = string
  default     = null
}

variable "alias_name" {
  description = "Alias that triggers (Scheduler, API Gateway, async invokes) point at. Deploys and rollbacks move this alias."
  type        = string
  default     = "live"
}

variable "async_invoke" {
  description = <<-EOT
    Asynchronous-invocation settings for the alias (Scheduler and Lambda-to-Lambda invokes are async).
    maximum_retry_attempts: 0-2. maximum_event_age_in_seconds: 60-21600.
    on_failure_dlq: create an SSE-encrypted SQS queue and send events that exhaust their retries to it.
    null = Lambda defaults (2 retries, 6 h, no destination).
  EOT
  type = object({
    maximum_retry_attempts       = number
    maximum_event_age_in_seconds = optional(number, 21600)
    on_failure_dlq               = optional(bool, false)
  })
  default = null
}
