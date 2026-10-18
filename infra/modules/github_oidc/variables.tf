variable "github_repo" {
  description = "GitHub repository allowed to assume the roles, as owner/name (case-sensitive, as GitHub puts it in the token)."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.github_repo))
    error_message = "github_repo must look like owner/name."
  }
}

variable "environments" {
  description = "Deployment environments. Each gets role stopwatch-deploy-<env>, trusted only for GitHub environment <env>."
  type        = list(string)
  default     = ["staging", "prod"]
}

variable "backup_environments" {
  description = "Environments whose database is backed up nightly by GitHub Actions. Each gets role stopwatch-backup-<env>, trusted only for GitHub environment <env>-backup."
  type        = list(string)
  default     = ["prod"]
}

variable "state_bucket_name" {
  description = "Terraform state bucket. Each deploy role may read/write only its own <env>/ prefix."
  type        = string
}

variable "create_oidc_provider" {
  description = "Create the account-wide GitHub OIDC provider. Set false if the account already has one (only one per URL is allowed)."
  type        = bool
  default     = true
}

variable "existing_oidc_provider_arn" {
  description = "ARN of an existing token.actions.githubusercontent.com provider, used when create_oidc_provider = false."
  type        = string
  default     = null
}

variable "max_session_duration_s" {
  description = "Maximum role session length. One hour covers a CloudFront create/destroy."
  type        = number
  default     = 3600
}
