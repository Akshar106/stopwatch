output "sns_topic_arn" {
  description = "Alerts topic (alarms and budgets publish here; the operator email subscribes)."
  value       = aws_sns_topic.alerts.arn
}

output "alarm_names" {
  description = "All alarm names created in this environment."
  value = concat(
    [for a in aws_cloudwatch_metric_alarm.metric : a.alarm_name],
    aws_cloudwatch_metric_alarm.ingest_error_rate[*].alarm_name,
    aws_cloudwatch_metric_alarm.api_5xx[*].alarm_name,
  )
}

output "dashboard_names" {
  description = "Dashboard names (empty when create_dashboards = false)."
  value = concat(
    aws_cloudwatch_dashboard.pipeline[*].dashboard_name,
    aws_cloudwatch_dashboard.api[*].dashboard_name,
    aws_cloudwatch_dashboard.cost_abuse[*].dashboard_name,
  )
}
