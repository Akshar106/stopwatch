# One Lambda entry point (docs/contracts.md §1): execution role, log group, function, "live" alias
# and, for async targets, retry/destination settings. The env roots instantiate this once per entry
# point; every instance shares one zip artifact per package (api.zip or jobs.zip).
#
# Deliberate choices:
# - No VPC (ADR-010): Neon is reached over TLS on the public internet, so there is no NAT gateway
#   (~$32/month) and no VPC endpoints. Least-privilege IAM is the main control instead.
# - Terraform publishes a version whenever code or config changes, but does NOT move the alias after
#   creation. Promotion (and rollback) is `make deploy-code` / `make rollback`, so an unrelated
#   `terraform apply` during an incident can never re-promote a bad build.

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}
data "aws_region" "current" {}

locals {
  function_name = "${var.name_prefix}-${var.function_key}"
  account_id    = data.aws_caller_identity.current.account_id
  partition     = data.aws_partition.current.partition
  region        = data.aws_region.current.region
  create_dlq    = try(var.async_invoke.on_failure_dlq, false)
}

# --- Logs ------------------------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "this" {
  #checkov:skip=CKV_AWS_158:Encrypted at rest with CloudWatch-managed keys; a customer-managed KMS key costs $1/month.
  #checkov:skip=CKV_AWS_338:14-day retention is deliberate: free-tier volume and personal-data minimisation (docs/06 §8).
  name              = "/aws/lambda/${local.function_name}"
  retention_in_days = var.log_retention_days
}

# --- IAM -------------------------------------------------------------------------------------------

data "aws_iam_policy_document" "assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "this" {
  name                 = local.function_name
  description          = "Execution role for ${local.function_name}"
  assume_role_policy   = data.aws_iam_policy_document.assume.json
  permissions_boundary = var.permissions_boundary_arn
}

data "aws_iam_policy_document" "this" {
  statement {
    sid       = "WriteOwnLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.this.arn}:*"]
  }

  # X-Ray actions do not support resource-level permissions.
  statement {
    sid       = "XRayTracing"
    actions   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords"]
    resources = ["*"]
  }

  dynamic "statement" {
    for_each = var.ssm_prefix == null ? [] : [var.ssm_prefix]
    content {
      sid     = "ReadSecretsAtColdStart"
      actions = ["ssm:GetParametersByPath"]
      resources = [
        "arn:${local.partition}:ssm:${local.region}:${local.account_id}:parameter${statement.value}",
        "arn:${local.partition}:ssm:${local.region}:${local.account_id}:parameter${statement.value}/*",
      ]
    }
  }

  # SecureStrings use the AWS-managed aws/ssm key; decryption is allowed only when SSM asks for it.
  dynamic "statement" {
    for_each = var.ssm_prefix == null ? [] : [var.ssm_prefix]
    content {
      sid       = "DecryptSecretsViaSsm"
      actions   = ["kms:Decrypt"]
      resources = ["arn:${local.partition}:kms:${local.region}:${local.account_id}:key/*"]
      condition {
        test     = "StringEquals"
        variable = "kms:ViaService"
        values   = ["ssm.${local.region}.amazonaws.com"]
      }
    }
  }

  dynamic "statement" {
    for_each = local.create_dlq ? [1] : []
    content {
      sid       = "SendFailedEventsToDlq"
      actions   = ["sqs:SendMessage"]
      resources = [aws_sqs_queue.dlq[0].arn]
    }
  }

  dynamic "statement" {
    for_each = var.iam_statements
    content {
      sid       = statement.value.sid
      actions   = statement.value.actions
      resources = statement.value.resources

      dynamic "condition" {
        for_each = statement.value.conditions
        content {
          test     = condition.value.test
          variable = condition.value.variable
          values   = condition.value.values
        }
      }
    }
  }
}

resource "aws_iam_role_policy" "this" {
  name   = "least-privilege"
  role   = aws_iam_role.this.id
  policy = data.aws_iam_policy_document.this.json
}

# --- Function + alias ------------------------------------------------------------------------------

resource "aws_lambda_function" "this" {
  #checkov:skip=CKV_AWS_117:Lambdas run outside a VPC by design (ADR-010): no NAT gateway cost; Neon is reached over TLS.
  #checkov:skip=CKV_AWS_116:Sync (API) functions return errors to the caller; async functions use on-failure destinations configured below instead of a legacy DLQ.
  #checkov:skip=CKV_AWS_173:Environment variables hold only non-secret config; secrets are SSM SecureStrings read at cold start.
  #checkov:skip=CKV_AWS_272:No code-signing profile; artifacts are built once in CI and verified by SHA-256 before promotion.
  function_name = local.function_name
  description   = var.description
  role          = aws_iam_role.this.arn
  runtime       = var.runtime
  handler       = var.handler
  architectures = [var.architecture]

  s3_bucket        = var.package_s3_bucket
  s3_key           = var.package_s3_key
  source_code_hash = var.source_code_hash
  publish          = true

  memory_size                    = var.memory_mb
  timeout                        = var.timeout_s
  reserved_concurrent_executions = var.reserved_concurrency

  ephemeral_storage {
    size = var.ephemeral_storage_mb
  }

  tracing_config {
    mode = "Active"
  }

  environment {
    variables = var.environment_variables
  }

  logging_config {
    log_format = "Text" # Powertools already writes one JSON object per line
    log_group  = aws_cloudwatch_log_group.this.name
  }

  depends_on = [aws_iam_role_policy.this]
}

resource "aws_lambda_alias" "live" {
  name             = var.alias_name
  description      = "Promoted version; moved by make deploy-code / make rollback"
  function_name    = aws_lambda_function.this.function_name
  function_version = aws_lambda_function.this.version

  lifecycle {
    ignore_changes = [function_version]
  }
}

# --- Async invocation ------------------------------------------------------------------------------

resource "aws_sqs_queue" "dlq" {
  count = local.create_dlq ? 1 : 0

  name                      = "${local.function_name}-dlq"
  sqs_managed_sse_enabled   = true
  message_retention_seconds = 1209600 # 14 days, the SQS maximum: time to inspect and replay
}

resource "aws_lambda_function_event_invoke_config" "this" {
  count = var.async_invoke == null ? 0 : 1

  function_name                = aws_lambda_function.this.function_name
  qualifier                    = aws_lambda_alias.live.name
  maximum_retry_attempts       = var.async_invoke.maximum_retry_attempts
  maximum_event_age_in_seconds = var.async_invoke.maximum_event_age_in_seconds

  dynamic "destination_config" {
    for_each = local.create_dlq ? [1] : []
    content {
      on_failure {
        destination = aws_sqs_queue.dlq[0].arn
      }
    }
  }
}
