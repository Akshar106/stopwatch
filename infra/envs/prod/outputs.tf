output "env" {
  description = "Environment name."
  value       = var.env
}

output "cloudfront_domain" {
  description = "The distribution's *.cloudfront.net domain."
  value       = module.edge.domain_name
}

output "public_base_url" {
  description = "Base URL of the app (custom domain if configured)."
  value       = module.edge.public_base_url
}

output "cloudfront_distribution_id" {
  description = "For invalidations (make deploy-code)."
  value       = module.edge.distribution_id
}

output "site_bucket_name" {
  description = "SPA + published data bucket."
  value       = module.storage.site_bucket_name
}

output "lake_bucket_name" {
  description = "Private data lake bucket."
  value       = module.storage.lake_bucket_name
}

output "artifacts_bucket_name" {
  description = "Lambda package bucket."
  value       = module.storage.artifacts_bucket_name
}

output "function_names" {
  description = "Lambda function names keyed by entry point."
  value       = { for k, f in module.functions : k => f.function_name }
}

output "function_alias" {
  description = "Alias that every trigger targets."
  value       = "live"
}

output "api_endpoint" {
  description = "Direct execute-api endpoint (browsers use <public_base_url>/api)."
  value       = module.api.api_endpoint
}

output "sns_topic_arn" {
  description = "Alerts topic."
  value       = module.observability.sns_topic_arn
}

output "ssm_parameter_names" {
  description = "Secrets to set with `aws ssm put-parameter --overwrite` (created as \"unset\")."
  value       = module.secrets.parameter_names
}

output "schedule_states" {
  description = "ENABLED/DISABLED per job schedule."
  value       = module.scheduler.schedule_states
}

output "alarm_names" {
  description = "CloudWatch alarms in this environment."
  value       = module.observability.alarm_names
}
