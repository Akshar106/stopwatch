# AWS Budgets guardrails (docs/04 §10, docs/06 §9): the project targets about $0.55/month, so an
# actual spend above $1 or a forecast above $5 means something is wrong (runaway loop, abuse, a
# forgotten resource). Budgets without actions are free.

locals {
  budgets = {
    actual   = { limit = var.actual_limit_usd, type = "ACTUAL", severity = "SEV-3" }
    forecast = { limit = var.forecast_limit_usd, type = "FORECASTED", severity = "SEV-2" }
  }
}

resource "aws_budgets_budget" "this" {
  for_each = local.budgets

  name         = "${var.name_prefix}-monthly-${each.key}"
  budget_type  = "COST"
  limit_amount = format("%.2f", each.value.limit)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  # Gross usage: with the default (credits included) a Free-plan or promo-credit account reads ~$0
  # and these alerts could never fire while credits are being burned.
  cost_types {
    include_credit = false
  }

  dynamic "cost_filter" {
    for_each = var.cost_filter_tag == null ? [] : [var.cost_filter_tag]
    content {
      name   = "TagKeyValue"
      values = [format("user:%s$%s", cost_filter.value.key, cost_filter.value.value)]
    }
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = each.value.type
    subscriber_sns_topic_arns  = [var.sns_topic_arn]
    subscriber_email_addresses = var.email_addresses
  }

  tags = { severity = each.value.severity }
}
