# Runtime secrets as SSM SecureString parameters (docs/05 §8, docs/contracts.md §1).
#
# Terraform creates each operator-owned parameter with the placeholder "unset" and never learns the
# real value (the single exception, origin_verify_secret, is at the bottom of this file):
#   - value_wo is a write-only argument (Terraform >= 1.11): it is sent to AWS on create and never
#     stored in state or plan files, and the provider does not read the value back on refresh.
#   - ignore_changes = [value] documents the contract: the operator owns the value.
# The operator then sets real values out-of-band:
#   aws ssm put-parameter --overwrite --type SecureString --name /stopwatch/prod/session_secret --value ...
# The application treats "unset" as missing (stopwatch.platform.config).
#
# Standard-tier parameters and the AWS-managed aws/ssm key are free; Secrets Manager would be
# $0.40/secret/month (9 secrets = $3.60/month, several times the whole budget).

resource "aws_ssm_parameter" "this" {
  #checkov:skip=CKV_AWS_337:Encrypted with the AWS-managed aws/ssm key; a customer-managed key costs $1/month.
  for_each = var.parameters

  name             = "${var.ssm_prefix}/${each.key}"
  description      = each.value
  type             = "SecureString"
  tier             = "Standard"
  value_wo         = "unset"
  value_wo_version = 1

  lifecycle {
    ignore_changes = [value]
  }
}

# --- The one documented exception: origin_verify_secret (docs/05 §2) -------------------------------
#
# CloudFront adds `X-Origin-Verify: <secret>` to every /api/* origin request, and the API rejects
# requests without it in staging/prod. API Gateway HTTP APIs cannot be network-restricted to
# CloudFront, so this shared secret is what closes direct-to-origin access and makes
# CloudFront-Viewer-Address a trustworthy client IP. Terraform must know the value to configure
# CloudFront, so it is generated here and IS in state. It grants no data access; it only proves a
# request came through CloudFront.
#
# Rotate: terraform apply -replace='module.secrets.random_password.origin_verify'
# (CloudFront and the parameter update in the same apply; API containers pick the new value up on
# their next cold start or SSM cache refresh, so expect a few minutes of 403s on warm containers.)

resource "random_password" "origin_verify" {
  length  = 48
  special = false # header-safe: [A-Za-z0-9] only
}

resource "aws_ssm_parameter" "origin_verify_secret" {
  #checkov:skip=CKV_AWS_337:Encrypted with the AWS-managed aws/ssm key; a customer-managed key costs $1/month.
  name        = "${var.ssm_prefix}/origin_verify_secret"
  description = "Shared secret CloudFront sends as X-Origin-Verify on /api/* (managed by Terraform)"
  type        = "SecureString"
  tier        = "Standard"
  value       = random_password.origin_verify.result
}
