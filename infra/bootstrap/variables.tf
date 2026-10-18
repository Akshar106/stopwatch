variable "region" {
  description = "AWS region for the state bucket and all IAM-scoped ARNs."
  type        = string
  default     = "us-east-1"
}

variable "owner" {
  description = "Value of the owner tag (who to ask about these resources)."
  type        = string
}

variable "github_repo" {
  description = "GitHub repository (owner/name) whose Actions may deploy."
  type        = string
}

variable "state_bucket_name" {
  description = "State bucket name. null = stopwatch-tfstate-<account id> (globally unique without hardcoding the account)."
  type        = string
  default     = null
}

variable "environments" {
  description = "Environments that get a deploy role and permissions boundary."
  type        = list(string)
  default     = ["staging", "prod"]
}

variable "backup_environments" {
  description = "Environments whose database GitHub Actions backs up nightly."
  type        = list(string)
  default     = ["prod"]
}

variable "create_oidc_provider" {
  description = "Create the account-wide GitHub OIDC provider (false if the account already has one)."
  type        = bool
  default     = true
}

variable "existing_oidc_provider_arn" {
  description = "Existing provider ARN when create_oidc_provider = false."
  type        = string
  default     = null
}
