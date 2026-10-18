output "api_id" {
  description = "HTTP API id (CloudWatch dimension ApiId)."
  value       = aws_apigatewayv2_api.this.id
}

output "api_endpoint" {
  description = "Direct execute-api endpoint, e.g. https://abc123.execute-api.us-east-1.amazonaws.com. Browsers use CloudFront instead."
  value       = aws_apigatewayv2_api.this.api_endpoint
}

output "api_domain_name" {
  description = "Host name of the execute-api endpoint (CloudFront custom origin)."
  value       = trimprefix(aws_apigatewayv2_api.this.api_endpoint, "https://")
}

output "stage_name" {
  description = "Stage name."
  value       = aws_apigatewayv2_stage.default.name
}

output "access_log_group_name" {
  description = "Access-log group."
  value       = aws_cloudwatch_log_group.access.name
}
