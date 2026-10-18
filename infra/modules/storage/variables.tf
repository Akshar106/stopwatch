variable "name_prefix" {
  description = "Resource name prefix, e.g. \"stopwatch-prod\". Buckets become <prefix>-lake, <prefix>-site, <prefix>-artifacts."
  type        = string
}

variable "bucket_suffix" {
  description = "Optional suffix appended to every bucket name, for when the default names are already taken in the global S3 namespace (e.g. \"-a1b2\")."
  type        = string
  default     = ""
}

variable "force_destroy" {
  description = "Allow `terraform destroy` to delete non-empty buckets. Keep false in prod: curated data and backups live here."
  type        = bool
  default     = false
}

variable "site_distribution_arn" {
  description = "ARN of the CloudFront distribution allowed to read the site bucket through Origin Access Control."
  type        = string
}

variable "lake_retention_days" {
  description = "Expiry (days) for short-lived lake prefixes. Long-lived prefixes (schedule/, curated/, reports/, config/, state/) never expire."
  type = object({
    events  = number
    raw     = number
    backups = number
  })
  default = {
    events  = 14
    raw     = 7
    backups = 30
  }
}

variable "noncurrent_version_retention_days" {
  description = "How long overwritten/deleted object versions are kept (the undo window for a bad publish or rollup)."
  type        = number
  default     = 30
}

variable "artifact_retention_days" {
  description = "Expiry (days) for uploaded Lambda packages. Lambda keeps its own copy of every published version, so old zips are only needed for re-deploys."
  type        = number
  default     = 90
}
