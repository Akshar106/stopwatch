# CloudFront: the single public origin for the app (docs/04 §4).
#
#   /*       -> site bucket (SPA). A viewer-request CloudFront Function maps client-side routes to
#               /index.html. Caching follows the object's Cache-Control (assets immutable,
#               index.html no-cache), set at upload time by `make deploy-code`.
#   /data/*  -> site bucket (published JSON). Cache-Control is written by the rollup/ingest jobs:
#               manifest/health 60 s, builds immutable.
#   /api/*   -> API Gateway HTTP API. Never cached; every viewer header except Host is forwarded,
#               plus CloudFront-Viewer-Address (the only client IP the API trusts) and the
#               X-Origin-Verify secret that proves the request came through CloudFront.
#
# Same-origin by construction: no CORS, first-party SameSite cookies. Cost: CloudFront's always-free
# tier (1 TB/month, 10M requests) covers us, and PriceClass_100 avoids the priciest edges.
# No WAF: a web ACL starts at ~$5/month. Abuse is handled by API Gateway throttles, application
# rate limits and reserved concurrency instead (docs/05 §7).

data "aws_cloudfront_cache_policy" "caching_disabled" {
  name = "Managed-CachingDisabled"
}

# Managed-AllViewerExceptHostHeader forwards all viewer headers, cookies and query strings except
# Host (API Gateway needs its own Host), and also "all device type and viewer location headers",
# which includes CloudFront-Viewer-Address (AWS CloudFront Developer Guide, "Use managed origin
# request policies" / "Add CloudFront request headers"). A custom policy cannot express this: the
# allViewerAndWhitelistCloudFront behaviour would also forward the viewer's Host header.
data "aws_cloudfront_origin_request_policy" "all_viewer_except_host" {
  name = "Managed-AllViewerExceptHostHeader"
}

locals {
  site_origin_id = "site-s3"
  api_origin_id  = "api-gateway"
  custom_cert    = var.acm_certificate_arn != null
}

resource "aws_cloudfront_origin_access_control" "site" {
  name                              = "${var.name_prefix}-site"
  description                       = "CloudFront -> ${var.name_prefix} site bucket (SigV4)"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_function" "spa_rewrite" {
  name    = "${var.name_prefix}-spa-rewrite"
  comment = "Serve /index.html for extensionless SPA routes outside /data/ and /api/"
  runtime = "cloudfront-js-2.0"
  code    = file("${path.module}/spa_rewrite.js")
  publish = true
}

# Like Managed-CachingOptimized, but with min TTL 0 so `Cache-Control: no-cache` on index.html is
# honoured exactly. Nothing varies the cache key: no cookies, headers or query strings.
resource "aws_cloudfront_cache_policy" "honor_origin" {
  name        = "${var.name_prefix}-honor-origin"
  comment     = "Respect origin Cache-Control; 1 h default when the object has none"
  min_ttl     = 0
  default_ttl = 3600
  max_ttl     = 31536000

  parameters_in_cache_key_and_forwarded_to_origin {
    enable_accept_encoding_brotli = true
    enable_accept_encoding_gzip   = true

    cookies_config {
      cookie_behavior = "none"
    }
    headers_config {
      header_behavior = "none"
    }
    query_strings_config {
      query_string_behavior = "none"
    }
  }
}

# Security headers from docs/05 §4, applied to every response (SPA, data and API).
resource "aws_cloudfront_response_headers_policy" "security" {
  #checkov:skip=CKV_AWS_259:HSTS is 2 years + includeSubDomains as docs/05 §4 specifies; "preload" is omitted because a *.cloudfront.net name cannot be preloaded and preloading a future custom domain is a separate, hard-to-reverse decision.
  name    = "${var.name_prefix}-security-headers"
  comment = "CSP, HSTS, nosniff, Referrer-Policy, Permissions-Policy (docs/05 §4)"

  security_headers_config {
    content_security_policy {
      content_security_policy = var.content_security_policy
      override                = true
    }

    strict_transport_security {
      access_control_max_age_sec = var.hsts_max_age_seconds
      include_subdomains         = true
      preload                    = false
      override                   = true
    }

    content_type_options {
      override = true
    }

    referrer_policy {
      referrer_policy = "strict-origin-when-cross-origin"
      override        = true
    }
  }

  custom_headers_config {
    items {
      header   = "Permissions-Policy"
      value    = var.permissions_policy
      override = true
    }
  }
}

resource "aws_cloudfront_distribution" "this" {
  #checkov:skip=CKV_AWS_68:No WAF: a web ACL starts at ~$5/month (5x the budget). API Gateway throttles + app rate limits + reserved concurrency instead (docs/05 §7).
  #checkov:skip=CKV2_AWS_47:No WAF (see CKV_AWS_68), so no Log4j managed rule group.
  #checkov:skip=CKV_AWS_86:Standard logs need an extra bucket and cost; built-in CloudFront metrics are on the dashboard.
  #checkov:skip=CKV_AWS_310:Single-region app; an origin group would need a replica bucket (cost, docs/05 §10.5).
  #checkov:skip=CKV_AWS_374:No geo restriction: public transit data for anyone.
  #checkov:skip=CKV_AWS_174:TLSv1.2_2021 is set whenever a custom certificate is used; the default *.cloudfront.net certificate does not allow choosing a minimum protocol.
  #checkov:skip=CKV2_AWS_42:The free *.cloudfront.net domain is the default (docs/04 §10.1); a custom certificate is optional via var.acm_certificate_arn.
  enabled             = true
  comment             = "${var.name_prefix}: SPA, published data and /api"
  aliases             = var.aliases
  default_root_object = "index.html"
  http_version        = "http2and3"
  is_ipv6_enabled     = true
  price_class         = var.price_class

  origin {
    origin_id                = local.site_origin_id
    domain_name              = var.site_bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.site.id
  }

  origin {
    origin_id   = local.api_origin_id
    domain_name = var.api_domain_name

    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
      origin_read_timeout    = 30
    }

    # Direct calls to the execute-api URL lack this header and get 403 from the app (docs/05 §2).
    custom_header {
      name  = "X-Origin-Verify"
      value = var.origin_verify_secret
    }
  }

  # /api/*: dynamic, per-user, never cached.
  ordered_cache_behavior {
    path_pattern               = "/api/*"
    target_origin_id           = local.api_origin_id
    viewer_protocol_policy     = "https-only"
    allowed_methods            = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods             = ["GET", "HEAD"]
    cache_policy_id            = data.aws_cloudfront_cache_policy.caching_disabled.id
    origin_request_policy_id   = data.aws_cloudfront_origin_request_policy.all_viewer_except_host.id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.security.id
    compress                   = true
  }

  # /data/*: published JSON; TTLs come from each object's Cache-Control.
  ordered_cache_behavior {
    path_pattern               = "/data/*"
    target_origin_id           = local.site_origin_id
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD"]
    cached_methods             = ["GET", "HEAD"]
    cache_policy_id            = aws_cloudfront_cache_policy.honor_origin.id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.security.id
    compress                   = true
  }

  # Everything else: the SPA.
  default_cache_behavior {
    target_origin_id           = local.site_origin_id
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD"]
    cached_methods             = ["GET", "HEAD"]
    cache_policy_id            = aws_cloudfront_cache_policy.honor_origin.id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.security.id
    compress                   = true

    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.spa_rewrite.arn
    }
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = !local.custom_cert
    acm_certificate_arn            = var.acm_certificate_arn
    ssl_support_method             = local.custom_cert ? "sni-only" : null
    minimum_protocol_version       = local.custom_cert ? "TLSv1.2_2021" : null
  }
}
