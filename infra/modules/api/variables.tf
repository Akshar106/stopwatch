variable "name_prefix" {
  description = "Resource name prefix, e.g. \"stopwatch-prod\"."
  type        = string
}

variable "function_name" {
  description = "Name of the api Lambda function."
  type        = string
}

variable "alias_name" {
  description = "Alias of the api function that API Gateway invokes."
  type        = string
}

variable "alias_invoke_arn" {
  description = "Invoke ARN of that alias."
  type        = string
}

variable "throttle" {
  description = "Stage-wide throttle (docs/05 §7): steady-state requests/second and burst."
  type = object({
    rate_limit  = number
    burst_limit = number
  })
  default = {
    rate_limit  = 20
    burst_limit = 40
  }
}

variable "auth_throttle" {
  description = "Tighter throttle for ANY /api/v1/auth/{proxy+} (login, callback, demo creation)."
  type = object({
    rate_limit  = number
    burst_limit = number
  })
  default = {
    rate_limit  = 5
    burst_limit = 10
  }
}

variable "integration_timeout_ms" {
  description = "API Gateway -> Lambda timeout. Slightly above the 15 s function timeout so Lambda's own error surfaces."
  type        = number
  default     = 16000
}

variable "log_retention_days" {
  description = "Access-log retention in days."
  type        = number
  default     = 14
}
