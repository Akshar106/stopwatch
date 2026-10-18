# EventBridge Scheduler: one schedule per job, all in one group, each targeting a function's "live"
# alias. Scheduler (not EventBridge rules) because cron expressions can carry a time zone and its
# 14M free invocations/month cover the per-minute ingest tick ~300x over (docs/04 §2).
#
# Flexible time windows are OFF: the ingest tick must fire every minute on the minute, and the daily
# jobs have deadlines (rollup published by 06:00 ET).

data "aws_caller_identity" "current" {}

resource "aws_scheduler_schedule_group" "this" {
  name = var.name_prefix
}

# --- Execution role: may invoke exactly the target aliases and write to the DLQ -------------------

data "aws_iam_policy_document" "assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
    # Confused-deputy protection: only schedules in this account may use the role.
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_iam_role" "this" {
  name                 = "${var.name_prefix}-scheduler"
  description          = "EventBridge Scheduler: invoke ${var.name_prefix} job aliases"
  assume_role_policy   = data.aws_iam_policy_document.assume.json
  permissions_boundary = var.permissions_boundary_arn
}

data "aws_iam_policy_document" "this" {
  statement {
    sid       = "InvokeJobAliases"
    actions   = ["lambda:InvokeFunction"]
    resources = distinct([for s in var.schedules : s.target_arn])
  }

  statement {
    sid       = "DeadLetter"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.dlq.arn]
  }
}

resource "aws_iam_role_policy" "this" {
  name   = "invoke-jobs"
  role   = aws_iam_role.this.id
  policy = data.aws_iam_policy_document.this.json
}

# Events Scheduler could not deliver after its retries (e.g. the target was deleted or throttled for
# longer than max_event_age). Costs nothing while empty.
resource "aws_sqs_queue" "dlq" {
  name                      = "${var.name_prefix}-scheduler-dlq"
  sqs_managed_sse_enabled   = true
  message_retention_seconds = 1209600
}

# --- Schedules -------------------------------------------------------------------------------------

resource "aws_scheduler_schedule" "this" {
  #checkov:skip=CKV_AWS_297:Schedules carry a constant "{}" payload; a customer-managed KMS key would cost $1/month (the whole budget) to encrypt nothing sensitive.
  for_each = var.schedules

  name        = "${var.name_prefix}-${each.key}"
  group_name  = aws_scheduler_schedule_group.this.name
  description = each.value.description
  state       = each.value.enabled ? "ENABLED" : "DISABLED"

  schedule_expression          = each.value.expression
  schedule_expression_timezone = startswith(each.value.expression, "cron(") ? each.value.timezone : null

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = each.value.target_arn
    role_arn = aws_iam_role.this.arn
    input    = each.value.input

    retry_policy {
      maximum_retry_attempts       = each.value.retry_attempts
      maximum_event_age_in_seconds = each.value.max_event_age_s
    }

    dead_letter_config {
      arn = aws_sqs_queue.dlq.arn
    }
  }

  depends_on = [aws_iam_role_policy.this]
}
