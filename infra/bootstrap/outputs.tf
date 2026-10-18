output "state_bucket_name" {
  description = "Pass to the env roots: TF_STATE_BUCKET=<this> make up ENV=..., and set it as the TF_STATE_BUCKET GitHub variable."
  value       = aws_s3_bucket.state.bucket
}

output "state_bucket_arn" {
  description = "ARN of the state bucket."
  value       = aws_s3_bucket.state.arn
}

output "region" {
  description = "Region of the state bucket."
  value       = var.region
}

output "oidc_provider_arn" {
  description = "GitHub Actions OIDC provider."
  value       = module.github_oidc.oidc_provider_arn
}

output "deploy_role_arns" {
  description = "Set each as AWS_DEPLOY_ROLE_ARN on the matching GitHub environment (staging, prod)."
  value       = module.github_oidc.deploy_role_arns
}

output "backup_role_arns" {
  description = "Set as AWS_BACKUP_ROLE_ARN on GitHub environment <env>-backup."
  value       = module.github_oidc.backup_role_arns
}

output "permissions_boundary_arns" {
  description = "Boundary policies attached to every role the env roots create."
  value       = module.github_oidc.permissions_boundary_arns
}
