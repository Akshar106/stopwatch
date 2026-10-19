# Keyless CI/CD: GitHub Actions exchanges its OIDC token for short-lived AWS credentials. No AWS
# access keys exist anywhere (docs/05 §8).
#
# Per environment:
#   stopwatch-deploy-<env>    trusted ONLY for <subject prefix>:environment:<env>. In GitHub, the
#                             prod environment requires a manual approval, so prod credentials can
#                             only be minted after a human approves the job.
#   stopwatch-boundary-<env>  permissions boundary. The deploy role can create IAM roles only if they
#                             carry this boundary, so a compromised pipeline cannot mint a role more
#                             powerful than "read/write this env's buckets, SSM path and functions".
#   stopwatch-backup-<env>    (backup environments only) nightly pg_dump: read one SSM parameter,
#                             write one S3 prefix. Trusted for GitHub environment <env>-backup, which
#                             has no approval gate so the scheduled job can run unattended.
#
# Why the deploy role can do this much: CI runs `terraform apply`, which creates and deletes the
# env's buckets, functions, roles, schedules, API, CloudFront distribution, alarms and budgets.
# Name-scoped ARNs (stopwatch-<env>-*) keep staging's role away from prod's resources. CloudFront
# and API Gateway v2 have little or no name-based resource scoping; those statements are limited by
# action instead. The deploy roles themselves are named stopwatch-deploy-<env> (outside the
# stopwatch-<env>-* pattern), so no deploy role can modify itself or its boundary.
#
# This module is instantiated from infra/bootstrap, not from the env roots: `make down ENV=staging`
# (and teardown.yml) must never delete the role that is running the destroy, and the OIDC provider
# is account-wide (one per URL).

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}
data "aws_region" "current" {}

locals {
  subject_prefix = coalesce(var.github_subject_prefix, "repo:${var.github_repo}")

  account_id = data.aws_caller_identity.current.account_id
  partition  = data.aws_partition.current.partition
  region     = data.aws_region.current.region
  oidc_host  = "token.actions.githubusercontent.com"

  oidc_provider_arn = var.create_oidc_provider ? aws_iam_openid_connect_provider.github[0].arn : var.existing_oidc_provider_arn

  envs = toset(var.environments)

  arn = {
    for env in var.environments : env => {
      buckets       = "arn:${local.partition}:s3:::stopwatch-${env}-*"
      functions     = "arn:${local.partition}:lambda:${local.region}:${local.account_id}:function:stopwatch-${env}-*"
      roles         = "arn:${local.partition}:iam::${local.account_id}:role/stopwatch-${env}-*"
      params        = "arn:${local.partition}:ssm:${local.region}:${local.account_id}:parameter/stopwatch/${env}"
      queues        = "arn:${local.partition}:sqs:${local.region}:${local.account_id}:stopwatch-${env}-*"
      topics        = "arn:${local.partition}:sns:${local.region}:${local.account_id}:stopwatch-${env}-*"
      alarms        = "arn:${local.partition}:cloudwatch:${local.region}:${local.account_id}:alarm:stopwatch-${env}-*"
      dashboards    = "arn:${local.partition}:cloudwatch::${local.account_id}:dashboard/stopwatch-${env}-*"
      budgets       = "arn:${local.partition}:budgets::${local.account_id}:budget/stopwatch-${env}-*"
      lambda_logs   = "arn:${local.partition}:logs:${local.region}:${local.account_id}:log-group:/aws/lambda/stopwatch-${env}-*"
      api_logs      = "arn:${local.partition}:logs:${local.region}:${local.account_id}:log-group:/aws/apigateway/stopwatch-${env}-*"
      sched_group   = "arn:${local.partition}:scheduler:${local.region}:${local.account_id}:schedule-group/stopwatch-${env}"
      schedules     = "arn:${local.partition}:scheduler:${local.region}:${local.account_id}:schedule/stopwatch-${env}/*"
      boundary      = "arn:${local.partition}:iam::${local.account_id}:policy/stopwatch-boundary-${env}"
      kms_keys      = "arn:${local.partition}:kms:${local.region}:${local.account_id}:key/*"
      state_bucket  = "arn:${local.partition}:s3:::${var.state_bucket_name}"
      cf_distrib    = "arn:${local.partition}:cloudfront::${local.account_id}:distribution/*"
      apigw_regions = "arn:${local.partition}:apigateway:${local.region}::"
    }
  }
}

# --- OIDC provider ---------------------------------------------------------------------------------

resource "aws_iam_openid_connect_provider" "github" {
  count = var.create_oidc_provider ? 1 : 0

  url            = "https://${local.oidc_host}"
  client_id_list = ["sts.amazonaws.com"]
  # No thumbprint_list: AWS validates GitHub's certificate against its own trusted CA store.
}

data "aws_iam_policy_document" "trust" {
  for_each = toset(concat(var.environments, [for e in var.backup_environments : "${e}-backup"]))

  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [local.oidc_provider_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "${local.oidc_host}:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "${local.oidc_host}:sub"
      values   = ["${local.subject_prefix}:environment:${each.key}"]
    }
  }
}

# --- Permissions boundary for workload roles (Lambda + Scheduler) ---------------------------------

data "aws_iam_policy_document" "boundary" {
  for_each = local.envs

  statement {
    sid       = "EnvBuckets"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:AbortMultipartUpload", "s3:ListBucket"]
    resources = [local.arn[each.key].buckets, "${local.arn[each.key].buckets}/*"]
  }
  statement {
    sid       = "EnvSecrets"
    actions   = ["ssm:GetParameter", "ssm:GetParameters", "ssm:GetParametersByPath"]
    resources = [local.arn[each.key].params, "${local.arn[each.key].params}/*"]
  }
  statement {
    sid       = "DecryptViaSsm"
    actions   = ["kms:Decrypt"]
    resources = [local.arn[each.key].kms_keys]
    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["ssm.${local.region}.amazonaws.com"]
    }
  }
  statement {
    sid       = "EnvLogs"
    actions   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
    resources = [local.arn[each.key].lambda_logs, "${local.arn[each.key].lambda_logs}:*"]
  }
  statement {
    sid       = "Tracing"
    actions   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords", "xray:GetSamplingRules", "xray:GetSamplingTargets"]
    resources = ["*"]
  }
  statement {
    sid       = "EnvFunctionsAndQueues"
    actions   = ["lambda:InvokeFunction", "sqs:SendMessage"]
    resources = [local.arn[each.key].functions, "${local.arn[each.key].functions}:*", local.arn[each.key].queues]
  }
  statement {
    sid       = "AppMetrics"
    actions   = ["cloudwatch:PutMetricData"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "cloudwatch:namespace"
      values   = ["Stopwatch"]
    }
  }
}

resource "aws_iam_policy" "boundary" {
  for_each = local.envs

  name        = "stopwatch-boundary-${each.key}"
  description = "Upper bound for every IAM role the ${each.key} pipeline creates"
  policy      = data.aws_iam_policy_document.boundary[each.key].json
}

# --- Deploy role -----------------------------------------------------------------------------------

resource "aws_iam_role" "deploy" {
  for_each = local.envs

  name                 = "stopwatch-deploy-${each.key}"
  description          = "GitHub Actions deploys to ${each.key} (environment-scoped OIDC trust)"
  assume_role_policy   = data.aws_iam_policy_document.trust[each.key].json
  max_session_duration = var.max_session_duration_s
}

# 1/3: Terraform state for this env only (S3 backend with native lockfile: <env>/terraform.tfstate[.tflock]).
data "aws_iam_policy_document" "deploy_state" {
  for_each = local.envs

  statement {
    sid       = "ListStateBucket"
    actions   = ["s3:ListBucket"]
    resources = [local.arn[each.key].state_bucket]
  }
  statement {
    sid       = "ReadWriteOwnState"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["${local.arn[each.key].state_bucket}/${each.key}/*"]
  }
}

# 2/3: what `make deploy-code`, migrations, rollback and smoke tests need. (Also covered by the
# infra policy today; kept separate so a code-only role can reuse it without Terraform rights.)
data "aws_iam_policy_document" "deploy_code" {
  for_each = local.envs

  statement {
    sid = "PromoteLambdaVersions"
    actions = [
      "lambda:GetFunction", "lambda:GetFunctionConfiguration", "lambda:UpdateFunctionCode",
      "lambda:PublishVersion", "lambda:ListVersionsByFunction", "lambda:GetAlias", "lambda:UpdateAlias",
      "lambda:DeleteFunction", # deletes old *versions* (qualified ARNs) to stay under the 75 GB code quota
    ]
    resources = [local.arn[each.key].functions, "${local.arn[each.key].functions}:*"]
  }
  statement {
    sid = "UploadArtifactsAndSite"
    actions = [
      "s3:ListBucket", "s3:ListBucketVersions", "s3:GetObject", "s3:GetObjectVersion", "s3:PutObject",
    ]
    resources = [local.arn[each.key].buckets, "${local.arn[each.key].buckets}/*"]
  }
  statement {
    sid       = "InvalidateCdn"
    actions   = ["cloudfront:CreateInvalidation", "cloudfront:GetInvalidation"]
    resources = [local.arn[each.key].cf_distrib]
  }
  statement {
    sid       = "ReadMigrationUrl"
    actions   = ["ssm:GetParameter"]
    resources = ["${local.arn[each.key].params}/database_owner_url"]
  }
}

# 3/3: what `terraform apply` / `destroy` of envs/<env> needs.
data "aws_iam_policy_document" "deploy_infra" {
  #checkov:skip=CKV_AWS_111:Terraform must create/delete CloudFront, API Gateway v2 and log-delivery resources, which offer no (or no name-based) resource-level scoping; those statements are limited by action set and documented above.
  #checkov:skip=CKV_AWS_356:Same as CKV_AWS_111: "*" only for CloudFront, API Gateway v2 paths and account-level read/log-delivery APIs.
  for_each = local.envs

  # IAM: only stopwatch-<env>-* roles, and only with the boundary attached.
  statement {
    sid       = "CreateBoundedRoles"
    actions   = ["iam:CreateRole", "iam:PutRolePolicy", "iam:AttachRolePolicy", "iam:PutRolePermissionsBoundary"]
    resources = [local.arn[each.key].roles]
    condition {
      test     = "StringEquals"
      variable = "iam:PermissionsBoundary"
      values   = [local.arn[each.key].boundary]
    }
  }
  statement {
    sid = "ManageEnvRoles"
    actions = [
      "iam:GetRole", "iam:DeleteRole", "iam:UpdateRole", "iam:UpdateRoleDescription", "iam:UpdateAssumeRolePolicy",
      "iam:TagRole", "iam:UntagRole", "iam:ListRoleTags", "iam:GetRolePolicy", "iam:DeleteRolePolicy",
      "iam:ListRolePolicies", "iam:ListAttachedRolePolicies", "iam:DetachRolePolicy", "iam:ListInstanceProfilesForRole",
    ]
    resources = [local.arn[each.key].roles]
  }
  statement {
    sid       = "PassEnvRolesToServices"
    actions   = ["iam:PassRole"]
    resources = [local.arn[each.key].roles]
    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["lambda.amazonaws.com", "scheduler.amazonaws.com"]
    }
  }
  statement {
    sid       = "KeepBoundary"
    effect    = "Deny"
    actions   = ["iam:DeleteRolePermissionsBoundary"]
    resources = ["*"]
  }

  statement {
    sid = "EnvFunctions"
    actions = [
      "lambda:Get*", "lambda:List*", "lambda:CreateFunction", "lambda:DeleteFunction", "lambda:UpdateFunction*",
      "lambda:PublishVersion", "lambda:CreateAlias", "lambda:UpdateAlias", "lambda:DeleteAlias",
      "lambda:AddPermission", "lambda:RemovePermission", "lambda:PutFunctionConcurrency",
      "lambda:DeleteFunctionConcurrency", "lambda:PutFunctionEventInvokeConfig",
      "lambda:DeleteFunctionEventInvokeConfig", "lambda:TagResource", "lambda:UntagResource",
    ]
    resources = [local.arn[each.key].functions, "${local.arn[each.key].functions}:*"]
  }
  statement {
    sid       = "EnvBuckets"
    actions   = ["s3:*"]
    resources = [local.arn[each.key].buckets, "${local.arn[each.key].buckets}/*"]
  }
  statement {
    sid = "EnvLogGroups"
    actions = [
      "logs:CreateLogGroup", "logs:DeleteLogGroup", "logs:PutRetentionPolicy", "logs:DeleteRetentionPolicy",
      "logs:TagResource", "logs:UntagResource", "logs:ListTagsForResource", "logs:TagLogGroup", "logs:ListTagsLogGroup",
    ]
    resources = [
      local.arn[each.key].lambda_logs, "${local.arn[each.key].lambda_logs}:*",
      local.arn[each.key].api_logs, "${local.arn[each.key].api_logs}:*",
    ]
  }
  statement {
    sid       = "EnvSchedules"
    actions   = ["scheduler:*"]
    resources = [local.arn[each.key].sched_group, local.arn[each.key].schedules]
  }
  statement {
    sid = "EnvQueuesTopicsParams"
    actions = [
      "sqs:CreateQueue", "sqs:DeleteQueue", "sqs:GetQueueAttributes", "sqs:SetQueueAttributes", "sqs:GetQueueUrl",
      "sqs:TagQueue", "sqs:UntagQueue", "sqs:ListQueueTags",
      "sns:CreateTopic", "sns:DeleteTopic", "sns:GetTopicAttributes", "sns:SetTopicAttributes", "sns:Subscribe",
      "sns:Unsubscribe", "sns:GetSubscriptionAttributes", "sns:ListSubscriptionsByTopic", "sns:TagResource",
      "sns:UntagResource", "sns:ListTagsForResource",
      "ssm:PutParameter", "ssm:DeleteParameter", "ssm:GetParameter", "ssm:GetParameters",
      "ssm:AddTagsToResource", "ssm:RemoveTagsFromResource", "ssm:ListTagsForResource",
    ]
    resources = [local.arn[each.key].queues, local.arn[each.key].topics, "${local.arn[each.key].params}/*"]
  }
  statement {
    sid = "EnvAlarmsDashboardsBudgets"
    actions = [
      "cloudwatch:PutMetricAlarm", "cloudwatch:DeleteAlarms", "cloudwatch:TagResource", "cloudwatch:UntagResource",
      "cloudwatch:ListTagsForResource", "cloudwatch:PutDashboard", "cloudwatch:GetDashboard", "cloudwatch:DeleteDashboards",
      "budgets:ViewBudget", "budgets:ModifyBudget", "budgets:TagResource", "budgets:UntagResource", "budgets:ListTagsForResource",
    ]
    resources = [local.arn[each.key].alarms, local.arn[each.key].dashboards, local.arn[each.key].budgets]
  }
  # CloudFront is global and supports little name-based scoping; limited by action set instead.
  statement {
    sid = "Cdn"
    actions = [
      "cloudfront:*Distribution*", "cloudfront:*OriginAccessControl*", "cloudfront:*Function*",
      "cloudfront:*ResponseHeadersPolic*", "cloudfront:*CachePolic*", "cloudfront:*OriginRequestPolic*",
      "cloudfront:*Invalidation*", "cloudfront:TagResource", "cloudfront:UntagResource", "cloudfront:ListTagsForResource",
    ]
    resources = ["*"]
  }
  # API Gateway v2 IAM is per-HTTP-verb on API paths; it cannot be scoped by API name.
  statement {
    sid       = "HttpApi"
    actions   = ["apigateway:GET", "apigateway:POST", "apigateway:PUT", "apigateway:PATCH", "apigateway:DELETE"]
    resources = ["${local.arn[each.key].apigw_regions}/apis", "${local.arn[each.key].apigw_regions}/apis/*", "${local.arn[each.key].apigw_regions}/tags/*"]
  }
  # HTTP API access logging uses CloudWatch Logs "vended log delivery" APIs (account-level).
  statement {
    sid = "AccountLevelReadsAndLogDelivery"
    actions = [
      "logs:DescribeLogGroups", "logs:CreateLogDelivery", "logs:GetLogDelivery", "logs:UpdateLogDelivery",
      "logs:DeleteLogDelivery", "logs:ListLogDeliveries", "logs:PutResourcePolicy", "logs:DescribeResourcePolicies",
      "ssm:DescribeParameters", "cloudwatch:DescribeAlarms", "sqs:ListQueues", "lambda:GetAccountSettings",
    ]
    resources = ["*"]
  }
}

locals {
  deploy_policies = merge(
    { for env in var.environments : "${env}/state" => { env = env, kind = "state", json = data.aws_iam_policy_document.deploy_state[env].json } },
    { for env in var.environments : "${env}/code" => { env = env, kind = "code", json = data.aws_iam_policy_document.deploy_code[env].json } },
    { for env in var.environments : "${env}/infra" => { env = env, kind = "infra", json = data.aws_iam_policy_document.deploy_infra[env].json } },
  )
}

resource "aws_iam_policy" "deploy" {
  for_each = local.deploy_policies

  name        = "stopwatch-deploy-${each.value.env}-${each.value.kind}"
  description = "GitHub deploy (${each.value.env}): ${each.value.kind}"
  policy      = each.value.json
}

resource "aws_iam_role_policy_attachment" "deploy" {
  for_each = local.deploy_policies

  role       = aws_iam_role.deploy[each.value.env].name
  policy_arn = aws_iam_policy.deploy[each.key].arn
}

# --- Backup role -----------------------------------------------------------------------------------

resource "aws_iam_role" "backup" {
  for_each = toset(var.backup_environments)

  name                 = "stopwatch-backup-${each.key}"
  description          = "GitHub Actions nightly pg_dump for ${each.key} (environment ${each.key}-backup)"
  assume_role_policy   = data.aws_iam_policy_document.trust["${each.key}-backup"].json
  max_session_duration = 3600
}

data "aws_iam_policy_document" "backup" {
  for_each = toset(var.backup_environments)

  statement {
    sid       = "ReadOwnerUrl"
    actions   = ["ssm:GetParameter"]
    resources = ["arn:${local.partition}:ssm:${local.region}:${local.account_id}:parameter/stopwatch/${each.key}/database_owner_url"]
  }
  statement {
    sid       = "WriteDumps"
    actions   = ["s3:PutObject"]
    resources = ["arn:${local.partition}:s3:::stopwatch-${each.key}-lake*/backups/postgres/*"]
  }
}

resource "aws_iam_role_policy" "backup" {
  for_each = toset(var.backup_environments)

  name   = "nightly-pg-dump"
  role   = aws_iam_role.backup[each.key].id
  policy = data.aws_iam_policy_document.backup[each.key].json
}
