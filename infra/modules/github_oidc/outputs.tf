output "oidc_provider_arn" {
  description = "GitHub Actions OIDC identity provider."
  value       = local.oidc_provider_arn
}

output "deploy_role_arns" {
  description = "Deploy role per environment. Store each as the AWS_DEPLOY_ROLE_ARN variable of the matching GitHub environment."
  value       = { for env, r in aws_iam_role.deploy : env => r.arn }
}

output "backup_role_arns" {
  description = "Backup role per environment. Store as AWS_BACKUP_ROLE_ARN in GitHub environment <env>-backup."
  value       = { for env, r in aws_iam_role.backup : env => r.arn }
}

output "permissions_boundary_arns" {
  description = "Boundary policy per environment; env roots attach it to every role they create."
  value       = { for env, p in aws_iam_policy.boundary : env => p.arn }
}
