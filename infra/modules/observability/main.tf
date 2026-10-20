# Alerting and dashboards (docs/06 §8-9), sized to CloudWatch's always-free tier:
# 10 alarms, 3 dashboards and the 10 custom metrics the app emits. Everything pages one SNS topic,
# which emails the operator. Each alarm description carries its severity and a one-line summary.

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  region     = data.aws_region.current.region
  account_id = data.aws_caller_identity.current.account_id

  # Dashboard metric arrays want dimensions flattened: ["env", "prod", "service", "stopwatch"].
  app_dims = flatten([for k in sort(keys(var.metric_dimensions)) : [k, var.metric_dimensions[k]]])

  # Single-metric alarms. The two ratio alarms (IngestErrorRate, Api5xx) use metric math below.
  metric_alarms = merge(
    {
      IngestStale = {
        severity   = "SEV-2"
        summary    = "No successful ingest tick in 5 consecutive minutes; observations are being lost."
        namespace  = var.metric_namespace, metric = "IngestSuccess", dimensions = var.metric_dimensions
        statistic  = "Sum", period = 60, evaluation_periods = 5, datapoints = 5
        comparison = "LessThanThreshold", threshold = 1
        # Silence is the failure mode, so missing data counts as breaching while ingest is on.
        missing = var.ingest_enabled ? "breaching" : "notBreaching"
      }
      FeedStale = {
        severity   = "SEV-3"
        summary    = "MBTA feed header older than 300 s for 10 minutes (usually upstream)."
        namespace  = var.metric_namespace, metric = "FeedAgeSeconds", dimensions = var.metric_dimensions
        statistic  = "Maximum", period = 60, evaluation_periods = 10, datapoints = 10
        comparison = "GreaterThanThreshold", threshold = 300, missing = "notBreaching"
      }
      # The rollup runs at 04:15 ET. 25 hourly periods without a success means the previous
      # success has aged out of the window by ~06:00 ET: "not published by 06:00".
      RollupLate = {
        severity   = "SEV-3"
        summary    = "No successful daily rollup in the last 25 h (due by 06:00 ET)."
        namespace  = var.metric_namespace, metric = "RollupSuccess", dimensions = var.metric_dimensions
        statistic  = "Sum", period = 3600, evaluation_periods = 25, datapoints = 25
        comparison = "LessThanThreshold", threshold = 1, missing = "breaching"
      }
      # One datapoint per day; "ignore" keeps the alarm in ALARM until the next rollup reports.
      RollupLowCoverage = {
        severity   = "SEV-3"
        summary    = "Daily rollup coverage below 80% (quality gate keeps the previous build live)."
        namespace  = var.metric_namespace, metric = "RollupCoveragePct", dimensions = var.metric_dimensions
        statistic  = "Minimum", period = 3600, evaluation_periods = 1, datapoints = 1
        comparison = "LessThanThreshold", threshold = 80, missing = "ignore"
      }
      ApiLatencyP95 = {
        severity   = "SEV-3"
        summary    = "API p95 latency above 1 s for 15 minutes."
        namespace  = "AWS/ApiGateway", metric = "Latency", dimensions = { ApiId = var.api_id }
        statistic  = "p95", period = 300, evaluation_periods = 3, datapoints = 3
        comparison = "GreaterThanThreshold", threshold = 1000, missing = "notBreaching"
      }
      ApiThrottles = {
        severity   = "SEV-3"
        summary    = "api Lambda throttled (reserved concurrency exhausted) within 5 minutes."
        namespace  = "AWS/Lambda", metric = "Throttles", dimensions = { FunctionName = var.function_names["api"] }
        statistic  = "Sum", period = 300, evaluation_periods = 1, datapoints = 1
        comparison = "GreaterThanThreshold", threshold = 0, missing = "notBreaching"
      }
      AuthFailureSpike = {
        severity   = "SEV-3"
        summary    = "More than 50 authentication failures in 10 minutes."
        namespace  = var.metric_namespace, metric = "AuthFailures", dimensions = var.metric_dimensions
        statistic  = "Sum", period = 600, evaluation_periods = 1, datapoints = 1
        comparison = "GreaterThanThreshold", threshold = 50, missing = "notBreaching"
      }
    },
    var.notify_dlq_name == null ? {} : {
      NotifyDLQ = {
        severity   = "SEV-3"
        summary    = "Alert notifications failed after retries and are waiting in the DLQ."
        namespace  = "AWS/SQS", metric = "ApproximateNumberOfMessagesVisible", dimensions = { QueueName = var.notify_dlq_name }
        statistic  = "Maximum", period = 300, evaluation_periods = 1, datapoints = 1
        comparison = "GreaterThanThreshold", threshold = 0, missing = "notBreaching"
      }
    },
  )

  percentile_stat = { for k, a in local.metric_alarms : k => can(regex("^p\\d", a.statistic)) }

  describe = { for k, a in merge(local.metric_alarms, {
    IngestErrorRate = { severity = "SEV-3", summary = "ingest-tick errors above 20% of invocations over 15 minutes." }
    Api5xx          = { severity = "SEV-2", summary = "API 5xx above 5% of at least 20 requests in 5 minutes." }
  }) : k => "${a.severity} | ${a.summary}" }
}

# --- Notification topic -------------------------------------------------------------------------

resource "aws_sns_topic" "alerts" {
  #checkov:skip=CKV_AWS_26:CloudWatch alarms and AWS Budgets cannot publish to a topic encrypted with the AWS-managed aws/sns key, and a customer-managed key costs $1/month. Messages carry alarm metadata only, no user data.
  name = "${var.name_prefix}-alerts"
}

data "aws_iam_policy_document" "alerts" {
  statement {
    sid       = "CloudWatchAlarms"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.alerts.arn]
    principals {
      type        = "Service"
      identifiers = ["cloudwatch.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }

  statement {
    sid       = "AwsBudgets"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.alerts.arn]
    principals {
      type        = "Service"
      identifiers = ["budgets.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

resource "aws_sns_topic_policy" "alerts" {
  arn    = aws_sns_topic.alerts.arn
  policy = data.aws_iam_policy_document.alerts.json
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# --- Alarms -------------------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "metric" {
  for_each = var.create_alarms ? local.metric_alarms : {}

  alarm_name          = "${var.name_prefix}-${each.key}"
  alarm_description   = local.describe[each.key]
  namespace           = each.value.namespace
  metric_name         = each.value.metric
  dimensions          = each.value.dimensions
  statistic           = local.percentile_stat[each.key] ? null : each.value.statistic
  extended_statistic  = local.percentile_stat[each.key] ? each.value.statistic : null
  period              = each.value.period
  evaluation_periods  = each.value.evaluation_periods
  datapoints_to_alarm = each.value.datapoints
  comparison_operator = each.value.comparison
  threshold           = each.value.threshold
  treat_missing_data  = each.value.missing
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "ingest_error_rate" {
  count = var.create_alarms ? 1 : 0

  alarm_name          = "${var.name_prefix}-IngestErrorRate"
  alarm_description   = local.describe["IngestErrorRate"]
  comparison_operator = "GreaterThanThreshold"
  threshold           = 20
  evaluation_periods  = 1
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]

  metric_query {
    id          = "error_pct"
    expression  = "IF(invocations > 0, 100 * errors / invocations, 0)"
    label       = "ingest-tick error %"
    return_data = true
  }

  metric_query {
    id = "errors"
    metric {
      namespace   = "AWS/Lambda"
      metric_name = "Errors"
      dimensions  = { FunctionName = var.function_names["ingest-tick"] }
      stat        = "Sum"
      period      = 900
    }
  }

  metric_query {
    id = "invocations"
    metric {
      namespace   = "AWS/Lambda"
      metric_name = "Invocations"
      dimensions  = { FunctionName = var.function_names["ingest-tick"] }
      stat        = "Sum"
      period      = 900
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "api_5xx" {
  count = var.create_alarms ? 1 : 0

  alarm_name          = "${var.name_prefix}-Api5xx"
  alarm_description   = local.describe["Api5xx"]
  comparison_operator = "GreaterThanThreshold"
  threshold           = 5
  evaluation_periods  = 1
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]

  # Below 20 requests a single error would be >5%; the minimum keeps one bad request from paging.
  metric_query {
    id          = "error_pct"
    expression  = "IF(requests >= 20, 100 * errors / requests, 0)"
    label       = "API 5xx %"
    return_data = true
  }

  metric_query {
    id = "errors"
    metric {
      namespace   = "AWS/ApiGateway"
      metric_name = "5xx"
      dimensions  = { ApiId = var.api_id }
      stat        = "Sum"
      period      = 300
    }
  }

  metric_query {
    id = "requests"
    metric {
      namespace   = "AWS/ApiGateway"
      metric_name = "Count"
      dimensions  = { ApiId = var.api_id }
      stat        = "Sum"
      period      = 300
    }
  }
}

# --- Dashboards ---------------------------------------------------------------------------------

locals {
  alarm_arns = concat(
    [for a in aws_cloudwatch_metric_alarm.metric : a.arn],
    aws_cloudwatch_metric_alarm.ingest_error_rate[*].arn,
    aws_cloudwatch_metric_alarm.api_5xx[*].arn,
  )

  app_metric = { for m in ["IngestSuccess", "IngestDurationMs", "FeedAgeSeconds", "ArrivalsEmitted", "LowConfidenceRatio", "RollupSuccess", "RollupCoveragePct", "AuthFailures", "NotificationsSent", "AskCostMicroUSD"] :
    m => concat([var.metric_namespace, m], local.app_dims)
  }

  job_keys = [for k in ["ingest-tick", "schedule-import", "daily-rollup", "maintenance", "notify", "lamp-validate"] : k if contains(keys(var.function_names), k)]
  cf_dims  = ["DistributionId", var.distribution_id, "Region", "Global"]

  # Small helper shapes, so the widget lists below read like a layout.
  ts = { type = "metric", width = 8, height = 6 }

  pipeline_widgets = concat(
    [{
      type       = "text", x = 0, y = 0, width = 24, height = 2
      properties = { markdown = "## ${var.name_prefix} pipeline\nFreshness SLO: 99% of minutes have a successful tick." }
    }],
    [
      merge(local.ts, { x = 0, y = 2, properties = { title = "Successful ticks / min", region = local.region, stat = "Sum", period = 60, view = "timeSeries", metrics = [local.app_metric["IngestSuccess"]] } }),
      merge(local.ts, { x = 8, y = 2, properties = { title = "Feed age (s)", region = local.region, stat = "Maximum", period = 60, view = "timeSeries", metrics = [local.app_metric["FeedAgeSeconds"]], annotations = { horizontal = [{ label = "FeedStale", value = 300 }] } } }),
      merge(local.ts, { x = 16, y = 2, properties = { title = "Tick duration (ms)", region = local.region, period = 300, view = "timeSeries", metrics = [concat(local.app_metric["IngestDurationMs"], [{ stat = "p95", label = "p95" }]), concat(local.app_metric["IngestDurationMs"], [{ stat = "Maximum", label = "max" }])], annotations = { horizontal = [{ label = "timeout", value = 50000 }] } } }),
      merge(local.ts, { x = 0, y = 8, properties = { title = "Arrivals emitted / min", region = local.region, stat = "Sum", period = 60, view = "timeSeries", metrics = [local.app_metric["ArrivalsEmitted"]] } }),
      merge(local.ts, { x = 8, y = 8, properties = { title = "Low-confidence arrivals (%)", region = local.region, stat = "Average", period = 300, view = "timeSeries", metrics = [local.app_metric["LowConfidenceRatio"]] } }),
      merge(local.ts, { x = 16, y = 8, properties = { title = "Daily rollup coverage (%)", region = local.region, stat = "Minimum", period = 86400, view = "timeSeries", metrics = [local.app_metric["RollupCoveragePct"]], annotations = { horizontal = [{ label = "quality gate", value = 80 }] } } }),
      merge(local.ts, { x = 0, y = 14, properties = { title = "Job errors", region = local.region, stat = "Sum", period = 300, view = "timeSeries", metrics = [for k in local.job_keys : ["AWS/Lambda", "Errors", "FunctionName", var.function_names[k], { label = k }]] } }),
      merge(local.ts, { x = 8, y = 14, properties = { title = "Job duration p95 (ms)", region = local.region, stat = "p95", period = 300, view = "timeSeries", metrics = [for k in local.job_keys : ["AWS/Lambda", "Duration", "FunctionName", var.function_names[k], { label = k }]] } }),
      merge(local.ts, { x = 16, y = 14, properties = { title = "Daily rollup successes", region = local.region, stat = "Sum", period = 86400, view = "singleValue", metrics = [local.app_metric["RollupSuccess"]] } }),
    ],
    length(local.alarm_arns) == 0 ? [] : [{
      type       = "alarm", x = 0, y = 20, width = 24, height = 3
      properties = { title = "Alarm status", alarms = local.alarm_arns }
    }],
  )

  api_widgets = [
    merge(local.ts, { x = 0, y = 0, properties = { title = "API requests", region = local.region, stat = "Sum", period = 300, view = "timeSeries", metrics = [["AWS/ApiGateway", "Count", "ApiId", var.api_id]] } }),
    merge(local.ts, { x = 8, y = 0, properties = { title = "API 4xx / 5xx", region = local.region, stat = "Sum", period = 300, view = "timeSeries", metrics = [["AWS/ApiGateway", "4xx", "ApiId", var.api_id], ["AWS/ApiGateway", "5xx", "ApiId", var.api_id]] } }),
    merge(local.ts, { x = 16, y = 0, properties = { title = "API latency (ms)", region = local.region, period = 300, view = "timeSeries", metrics = [for p in ["p50", "p95", "p99"] : ["AWS/ApiGateway", "Latency", "ApiId", var.api_id, { stat = p, label = p }]], annotations = { horizontal = [{ label = "SLO p95 (warm)", value = 300 }] } } }),
    merge(local.ts, { x = 0, y = 6, properties = { title = "api Lambda: concurrency & throttles", region = local.region, period = 60, view = "timeSeries", metrics = [["AWS/Lambda", "ConcurrentExecutions", "FunctionName", var.function_names["api"], { stat = "Maximum" }], ["AWS/Lambda", "Throttles", "FunctionName", var.function_names["api"], { stat = "Sum" }]], annotations = { horizontal = [{ label = "reserved", value = 10 }] } } }),
    merge(local.ts, { x = 8, y = 6, properties = { title = "api Lambda: errors & duration p95", region = local.region, period = 300, view = "timeSeries", metrics = [["AWS/Lambda", "Errors", "FunctionName", var.function_names["api"], { stat = "Sum" }], ["AWS/Lambda", "Duration", "FunctionName", var.function_names["api"], { stat = "p95", yAxis = "right" }]] } }),
    merge(local.ts, { x = 16, y = 6, properties = { title = "Auth failures", region = local.region, stat = "Sum", period = 300, view = "timeSeries", metrics = [local.app_metric["AuthFailures"]] } }),
    merge(local.ts, { x = 0, y = 12, properties = { title = "CloudFront requests", region = "us-east-1", stat = "Sum", period = 300, view = "timeSeries", metrics = [concat(["AWS/CloudFront", "Requests"], local.cf_dims)] } }),
    merge(local.ts, { x = 8, y = 12, properties = { title = "CloudFront error rate (%)", region = "us-east-1", stat = "Average", period = 300, view = "timeSeries", metrics = [concat(["AWS/CloudFront", "4xxErrorRate"], local.cf_dims), concat(["AWS/CloudFront", "5xxErrorRate"], local.cf_dims)] } }),
    {
      type = "log", x = 16, y = 12, width = 8, height = 6
      properties = {
        title = "Slowest routes (last window)", region = local.region, view = "table"
        query = "SOURCE '${var.api_access_log_group_name}' | stats count(*) as requests, pct(latencyMs, 95) as p95_ms by routeKey | sort p95_ms desc | limit 10"
      }
    },
  ]

  cost_widgets = [
    merge(local.ts, { x = 0, y = 0, width = 12, properties = { title = "Invocations per function (hourly)", region = local.region, stat = "Sum", period = 3600, view = "timeSeries", stacked = true, metrics = [for k, n in var.function_names : ["AWS/Lambda", "Invocations", "FunctionName", n, { label = k }]] } }),
    merge(local.ts, { x = 12, y = 0, width = 12, properties = { title = "Compute (ms, hourly) per function", region = local.region, stat = "Sum", period = 3600, view = "timeSeries", stacked = true, metrics = [for k, n in var.function_names : ["AWS/Lambda", "Duration", "FunctionName", n, { label = k }]] } }),
    merge(local.ts, { x = 0, y = 6, properties = { title = "Ask spend (micro-USD / day)", region = local.region, stat = "Sum", period = 86400, view = "timeSeries", metrics = [local.app_metric["AskCostMicroUSD"]] } }),
    merge(local.ts, { x = 8, y = 6, properties = { title = "Push notifications sent", region = local.region, stat = "Sum", period = 3600, view = "timeSeries", metrics = [local.app_metric["NotificationsSent"]] } }),
    # Requires "Receive Billing Alerts" in the billing console; shows nothing until enabled.
    merge(local.ts, { x = 16, y = 6, properties = { title = "Estimated charges (USD, account)", region = "us-east-1", stat = "Maximum", period = 21600, view = "singleValue", metrics = [["AWS/Billing", "EstimatedCharges", "Currency", "USD"]] } }),
    {
      type = "log", x = 0, y = 12, width = 12, height = 6
      properties = {
        title = "Demo accounts created (hourly)", region = local.region, view = "timeSeries"
        query = "SOURCE '${var.api_access_log_group_name}' | filter method = 'POST' and path = '/api/v1/auth/demo' and status like /^201$/ | stats count(*) as demos by bin(1h)"
      }
    },
    {
      type = "log", x = 12, y = 12, width = 12, height = 6
      properties = {
        title = "Rate-limited requests (429, hourly)", region = local.region, view = "timeSeries"
        query = "SOURCE '${var.api_access_log_group_name}' | filter status like /^429$/ | stats count(*) as blocked by bin(1h)"
      }
    },
  ]
}

resource "aws_cloudwatch_dashboard" "pipeline" {
  count          = var.create_dashboards ? 1 : 0
  dashboard_name = "${var.name_prefix}-pipeline"
  dashboard_body = jsonencode({ widgets = local.pipeline_widgets })
}

resource "aws_cloudwatch_dashboard" "api" {
  count          = var.create_dashboards ? 1 : 0
  dashboard_name = "${var.name_prefix}-api"
  dashboard_body = jsonencode({ widgets = local.api_widgets })
}

resource "aws_cloudwatch_dashboard" "cost_abuse" {
  count          = var.create_dashboards ? 1 : 0
  dashboard_name = "${var.name_prefix}-cost-abuse"
  dashboard_body = jsonencode({ widgets = local.cost_widgets })
}
