output "lake_bucket_name" {
  description = "Private data-lake bucket (LAKE_URL = s3://<this>)."
  value       = aws_s3_bucket.this["lake"].bucket
}

output "lake_bucket_arn" {
  description = "ARN of the data-lake bucket."
  value       = aws_s3_bucket.this["lake"].arn
}

output "site_bucket_name" {
  description = "SPA + published-data bucket (SITE_URL = s3://<this>), served by CloudFront."
  value       = aws_s3_bucket.this["site"].bucket
}

output "site_bucket_arn" {
  description = "ARN of the site bucket."
  value       = aws_s3_bucket.this["site"].arn
}

output "site_bucket_regional_domain_name" {
  description = "Regional endpoint of the site bucket, used as the CloudFront S3 origin."
  value       = aws_s3_bucket.this["site"].bucket_regional_domain_name
}

output "artifacts_bucket_name" {
  description = "Bucket holding Lambda deployment packages."
  value       = aws_s3_bucket.this["artifacts"].bucket
}

output "artifacts_bucket_arn" {
  description = "ARN of the artifacts bucket."
  value       = aws_s3_bucket.this["artifacts"].arn
}
