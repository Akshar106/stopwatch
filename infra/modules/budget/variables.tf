variable "name_prefix" {
  description = "Resource name prefix, e.g. \"stopwatch-prod\"."
  type        = string
}

variable "actual_limit_usd" {
  description = "Monthly budget; alert when *actual* spend exceeds it (docs/04 §10: $1)."
  type        = number
  default     = 1
}

variable "forecast_limit_usd" {
  description = "Monthly budget; alert when *forecasted* spend exceeds it (docs/04 §10: $5)."
  type        = number
  default     = 5
}

variable "sns_topic_arn" {
  description = "Alerts topic (its policy must allow budgets.amazonaws.com to publish)."
  type        = string
}

variable "email_addresses" {
  description = "Addresses AWS Budgets emails directly, in addition to SNS, so a spend alert arrives even if the SNS subscription was never confirmed."
  type        = list(string)
  default     = []
}

variable "cost_filter_tag" {
  description = "Limit the budget to resources with this cost-allocation tag (e.g. { key = \"env\", value = \"staging\" }). The tag must be activated in the Billing console first. null = whole account."
  type = object({
    key   = string
    value = string
  })
  default = null
}
