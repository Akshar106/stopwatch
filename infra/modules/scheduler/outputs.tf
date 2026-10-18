output "schedule_group_name" {
  description = "Schedule group holding every job schedule for this environment."
  value       = aws_scheduler_schedule_group.this.name
}

output "schedule_names" {
  description = "Schedule names keyed by function key."
  value       = { for k, s in aws_scheduler_schedule.this : k => s.name }
}

output "schedule_states" {
  description = "ENABLED/DISABLED per schedule (staging ingest is DISABLED by default)."
  value       = { for k, s in aws_scheduler_schedule.this : k => s.state }
}

output "role_arn" {
  description = "Scheduler execution role ARN."
  value       = aws_iam_role.this.arn
}

output "dlq_arn" {
  description = "Scheduler delivery-failure queue ARN."
  value       = aws_sqs_queue.dlq.arn
}
