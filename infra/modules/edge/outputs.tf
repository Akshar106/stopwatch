output "distribution_id" {
  description = "CloudFront distribution id (for invalidations)."
  value       = aws_cloudfront_distribution.this.id
}

output "distribution_arn" {
  description = "Distribution ARN (the only principal the site bucket policy trusts)."
  value       = aws_cloudfront_distribution.this.arn
}

output "domain_name" {
  description = "The distribution's *.cloudfront.net domain."
  value       = aws_cloudfront_distribution.this.domain_name
}

output "public_base_url" {
  description = "https:// base URL users see: the first custom alias if any, else the cloudfront.net domain."
  value       = "https://${length(var.aliases) > 0 ? var.aliases[0] : aws_cloudfront_distribution.this.domain_name}"
}
