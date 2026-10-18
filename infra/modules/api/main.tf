# API Gateway HTTP API in front of the api Lambda (ADR-005). HTTP API rather than a Function URL for
# stage/route throttling; rather than a REST API because it is ~3.5x cheaper and we need none of
# the REST-only features. CloudFront forwards /api/* here, so browsers only ever see one origin.
#
# Routes:
#   ANY /api/{proxy+}          everything under /api (payload format 2.0)
#   ANY /api/v1/auth/{proxy+}  same integration, own (tighter) throttle; more specific, so it wins

resource "aws_apigatewayv2_api" "this" {
  name          = "${var.name_prefix}-api"
  description   = "Stopwatch dynamic API (/api/v1), reached through CloudFront"
  protocol_type = "HTTP"
  # No CORS configuration: the SPA and the API are same-origin behind CloudFront (docs/05 §2).
}

resource "aws_apigatewayv2_integration" "lambda" {
  api_id                 = aws_apigatewayv2_api.this.id
  integration_type       = "AWS_PROXY"
  integration_method     = "POST"
  integration_uri        = var.alias_invoke_arn
  payload_format_version = "2.0"
  timeout_milliseconds   = var.integration_timeout_ms
}

locals {
  routes = {
    api  = "ANY /api/{proxy+}"
    auth = "ANY /api/v1/auth/{proxy+}"
  }
}

resource "aws_apigatewayv2_route" "this" {
  #checkov:skip=CKV_AWS_309:Authorization is enforced by the application (sessions + CSRF, deny-by-default per route, docs/05 §3); public endpoints such as /healthz and /auth/login must stay reachable.
  for_each = local.routes

  api_id    = aws_apigatewayv2_api.this.id
  route_key = each.value
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

resource "aws_cloudwatch_log_group" "access" {
  #checkov:skip=CKV_AWS_158:CloudWatch-managed encryption; a customer-managed KMS key costs $1/month.
  #checkov:skip=CKV_AWS_338:14-day retention is deliberate (free tier, data minimisation).
  name              = "/aws/apigateway/${var.name_prefix}-api"
  retention_in_days = var.log_retention_days
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.this.id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    throttling_rate_limit  = var.throttle.rate_limit
    throttling_burst_limit = var.throttle.burst_limit
    # Detailed (per-route) metrics are billed as custom metrics; the built-in API metrics are enough.
    detailed_metrics_enabled = false
  }

  route_settings {
    route_key              = aws_apigatewayv2_route.this["auth"].route_key
    throttling_rate_limit  = var.auth_throttle.rate_limit
    throttling_burst_limit = var.auth_throttle.burst_limit
  }

  # One JSON line per request; no query strings, cookies or headers. Behind CloudFront, `ip` is the
  # edge address: the viewer's IP reaches the app in CloudFront-Viewer-Address / X-Forwarded-For.
  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.access.arn
    format = jsonencode({
      requestId        = "$context.requestId"
      time             = "$context.requestTime"
      ip               = "$context.identity.sourceIp"
      method           = "$context.httpMethod"
      path             = "$context.path"
      routeKey         = "$context.routeKey"
      status           = "$context.status"
      latencyMs        = "$context.responseLatency"
      integrationMs    = "$context.integration.latency"
      integrationError = "$context.integrationErrorMessage"
      responseLength   = "$context.responseLength"
      userAgent        = "$context.identity.userAgent"
    })
  }
}

# Allow this API (any stage/route) to invoke the alias, and nothing else.
resource "aws_lambda_permission" "api" {
  statement_id  = "AllowApiGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = var.function_name
  qualifier     = var.alias_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.this.execution_arn}/*/*"
}
