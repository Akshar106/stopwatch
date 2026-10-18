output "parameter_names" {
  description = "Full names of the parameters the operator must set (values start as \"unset\")."
  value       = sort([for p in aws_ssm_parameter.this : p.name])
}

output "parameter_arns" {
  description = "Parameter ARNs keyed by short name (including the Terraform-managed origin_verify_secret)."
  value = merge(
    { for k, p in aws_ssm_parameter.this : k => p.arn },
    { origin_verify_secret = aws_ssm_parameter.origin_verify_secret.arn },
  )
}

output "origin_verify_secret" {
  description = "Value CloudFront sends as X-Origin-Verify on /api/* (edge module)."
  value       = random_password.origin_verify.result
  sensitive   = true
}
