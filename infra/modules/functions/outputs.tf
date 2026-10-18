output "function_name" {
  description = "Lambda function name (<name_prefix>-<function_key>)."
  value       = aws_lambda_function.this.function_name
}

output "function_arn" {
  description = "Unqualified function ARN."
  value       = aws_lambda_function.this.arn
}

output "alias_name" {
  description = "Name of the promoted alias."
  value       = aws_lambda_alias.live.name
}

output "alias_arn" {
  description = "Qualified ARN of the live alias (target for Scheduler and IAM grants)."
  value       = aws_lambda_alias.live.arn
}

output "alias_invoke_arn" {
  description = "Invoke ARN of the live alias (for API Gateway integrations)."
  value       = aws_lambda_alias.live.invoke_arn
}

output "role_name" {
  description = "Execution role name."
  value       = aws_iam_role.this.name
}

output "role_arn" {
  description = "Execution role ARN."
  value       = aws_iam_role.this.arn
}

output "log_group_name" {
  description = "CloudWatch log group."
  value       = aws_cloudwatch_log_group.this.name
}

output "dlq_arn" {
  description = "On-failure SQS queue ARN, or null when async_invoke.on_failure_dlq is false."
  value       = try(aws_sqs_queue.dlq[0].arn, null)
}

output "dlq_name" {
  description = "On-failure SQS queue name, or null."
  value       = try(aws_sqs_queue.dlq[0].name, null)
}
