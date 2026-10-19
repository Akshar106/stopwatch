variable "ssm_prefix" {
  description = "Parameter path prefix without trailing slash, e.g. /stopwatch/prod (SSM_PREFIX)."
  type        = string

  validation {
    condition     = can(regex("^/[A-Za-z0-9_./-]+[^/]$", var.ssm_prefix))
    error_message = "ssm_prefix must start with / and must not end with /."
  }
}

variable "parameters" {
  description = "Parameter names (relative to ssm_prefix) mapped to descriptions."
  type        = map(string)
  default = {
    database_url         = "Neon connection string for the runtime role (stopwatch_app), sslmode=verify-full"
    database_owner_url   = "Neon connection string for the owner role (migrations, maintenance)"
    google_client_id     = "Google OAuth client id"
    google_client_secret = "Google OAuth client secret"
    session_secret       = "Session/CSRF signing key (rotate = invalidate all sessions)"
    vapid_public_key     = "Web Push VAPID public key"
    vapid_private_key    = "Web Push VAPID private key"
    groq_api_key         = "Groq API key for Ask Stopwatch"
  }
}
