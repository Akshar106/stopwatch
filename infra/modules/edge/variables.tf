variable "name_prefix" {
  description = "Resource name prefix, e.g. \"stopwatch-prod\"."
  type        = string
}

variable "site_bucket_regional_domain_name" {
  description = "Regional domain of the site bucket (S3 origin, accessed through OAC)."
  type        = string
}

variable "api_domain_name" {
  description = "Host name of the HTTP API execute-api endpoint (custom origin for /api/*)."
  type        = string
}

variable "aliases" {
  description = "Custom domain names (CNAMEs). Empty = use the free *.cloudfront.net domain."
  type        = list(string)
  default     = []
}

variable "acm_certificate_arn" {
  description = "ACM certificate (us-east-1) covering var.aliases. null = CloudFront default certificate."
  type        = string
  default     = null

  validation {
    condition     = var.acm_certificate_arn == null || can(regex("^arn:aws[a-z-]*:acm:us-east-1:", var.acm_certificate_arn))
    error_message = "CloudFront only accepts ACM certificates from us-east-1."
  }
}

variable "price_class" {
  description = "PriceClass_100 = North America + Europe edges only: cheapest, and where MBTA riders are."
  type        = string
  default     = "PriceClass_100"
}

variable "content_security_policy" {
  description = "Content-Security-Policy, exactly as specified in docs/05 §4."
  type        = string
  default     = "default-src 'self'; connect-src 'self' https://api-v3.mbta.com; img-src 'self' data:; script-src 'self'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
}

variable "permissions_policy" {
  description = "Permissions-Policy header (docs/05 §4). geolocation=(self) powers \"near me\", computed on-device."
  type        = string
  default     = "geolocation=(self), camera=(), microphone=()"
}

variable "hsts_max_age_seconds" {
  description = "Strict-Transport-Security max-age. Two years, per docs/05 §4."
  type        = number
  default     = 63072000
}

variable "origin_verify_secret" {
  description = "Shared secret sent to the API origin as X-Origin-Verify (secrets module). The API rejects /api/* requests without it in staging/prod."
  type        = string
  sensitive   = true
}
