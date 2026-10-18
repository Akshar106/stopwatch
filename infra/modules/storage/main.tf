# Storage: three private S3 buckets per environment.
#
#   lake       private data lake (state, events, raw samples, schedules, curated Parquet, reports, backups)
#   site       SPA + published JSON; readable only by this environment's CloudFront distribution (OAC)
#   artifacts  Lambda deployment zips. jobs.zip is > 50 MB, over Lambda's direct-upload limit, so
#              packages go through S3. Keys are content-addressed (lambda/<pkg>/<sha256>.zip).
#
# Cost notes (docs/04 §10.1): SSE-S3 rather than SSE-KMS (a customer-managed key is $1/month, the
# entire budget); no access logging or replication; lifecycle rules keep the lake under a few GB.

locals {
  buckets = {
    lake      = "${var.name_prefix}-lake${var.bucket_suffix}"
    site      = "${var.name_prefix}-site${var.bucket_suffix}"
    artifacts = "${var.name_prefix}-artifacts${var.bucket_suffix}"
  }
}

resource "aws_s3_bucket" "this" {
  #checkov:skip=CKV_AWS_18:Server access logs need a second bucket and add cost; CloudFront/Lambda metrics and CloudTrail event history cover investigations.
  #checkov:skip=CKV_AWS_144:Cross-region replication doubles storage cost. Curated data is rebuildable; Postgres has its own pg_dump backups (docs/05 §10.5).
  #checkov:skip=CKV_AWS_145:SSE-S3 instead of SSE-KMS: a customer-managed KMS key costs $1/month, the whole cost budget.
  #checkov:skip=CKV2_AWS_62:No S3 event notifications are needed; every job is schedule-driven.
  for_each = local.buckets

  bucket        = each.value
  force_destroy = var.force_destroy
  tags          = { Name = each.value, role = each.key }
}

resource "aws_s3_bucket_ownership_controls" "this" {
  for_each = local.buckets

  bucket = aws_s3_bucket.this[each.key].id
  rule {
    object_ownership = "BucketOwnerEnforced" # ACLs disabled; access is policy-only
  }
}

resource "aws_s3_bucket_public_access_block" "this" {
  for_each = local.buckets

  bucket                  = aws_s3_bucket.this[each.key].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "this" {
  for_each = local.buckets

  bucket = aws_s3_bucket.this[each.key].id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "this" {
  for_each = local.buckets

  bucket = aws_s3_bucket.this[each.key].id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# --- Lifecycle -------------------------------------------------------------------------------------

resource "aws_s3_bucket_lifecycle_configuration" "lake" {
  bucket = aws_s3_bucket.this["lake"].id

  rule {
    id     = "expire-events"
    status = "Enabled"
    filter {
      prefix = "events/"
    }
    expiration {
      days = var.lake_retention_days.events
    }
  }

  rule {
    id     = "expire-raw"
    status = "Enabled"
    filter {
      prefix = "raw/"
    }
    expiration {
      days = var.lake_retention_days.raw
    }
  }

  rule {
    id     = "expire-backups"
    status = "Enabled"
    filter {
      prefix = "backups/"
    }
    expiration {
      days = var.lake_retention_days.backups
    }
  }

  # The ingest state object is overwritten every minute (43k versions/month). Keeping those for the
  # full window below would cost more than everything else combined, so state history is one day.
  # When rules overlap, S3 applies the earliest expiration.
  rule {
    id     = "state-history-1d"
    status = "Enabled"
    filter {
      prefix = "state/"
    }
    noncurrent_version_expiration {
      noncurrent_days = 1
    }
  }

  rule {
    id     = "noncurrent-versions"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration {
      noncurrent_days = var.noncurrent_version_retention_days
    }
    expiration {
      expired_object_delete_marker = true
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "site" {
  bucket = aws_s3_bucket.this["site"].id

  # health/{agency}.json is rewritten every 5 minutes; its history has no value after a day.
  rule {
    id     = "health-history-1d"
    status = "Enabled"
    filter {
      prefix = "data/v1/health/"
    }
    noncurrent_version_expiration {
      noncurrent_days = 1
    }
  }

  # Previous versions of index.html and manifest.json are the rollback path (docs/04 §10).
  rule {
    id     = "noncurrent-versions"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration {
      noncurrent_days = var.noncurrent_version_retention_days
    }
    expiration {
      expired_object_delete_marker = true
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "artifacts" {
  bucket = aws_s3_bucket.this["artifacts"].id

  rule {
    id     = "expire-packages"
    status = "Enabled"
    filter {}
    expiration {
      days = var.artifact_retention_days
    }
    noncurrent_version_expiration {
      noncurrent_days = 7
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
}

# --- Bucket policies -------------------------------------------------------------------------------

data "aws_iam_policy_document" "tls_only" {
  for_each = local.buckets

  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.this[each.key].arn, "${aws_s3_bucket.this[each.key].arn}/*"]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

data "aws_iam_policy_document" "site" {
  source_policy_documents = [data.aws_iam_policy_document.tls_only["site"].json]

  # Only this environment's distribution may read, and only through OAC (SigV4-signed by CloudFront).
  statement {
    sid       = "AllowCloudFrontRead"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.this["site"].arn}/*"]

    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [var.site_distribution_arn]
    }
  }

  # ListBucket lets S3 answer 404 (not 403) for a missing key, so the SPA and the smoke test can tell
  # "not published yet" from "access misconfigured". CloudFront never forwards list requests: the
  # cache policy drops query strings, so no listing is exposed to viewers.
  statement {
    sid       = "AllowCloudFrontNotFound"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.this["site"].arn]

    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [var.site_distribution_arn]
    }
  }
}

resource "aws_s3_bucket_policy" "this" {
  for_each = local.buckets

  bucket = aws_s3_bucket.this[each.key].id
  policy = each.key == "site" ? data.aws_iam_policy_document.site.json : data.aws_iam_policy_document.tls_only[each.key].json

  # A bucket policy that grants a service principal is "public" until BPA is in place.
  depends_on = [aws_s3_bucket_public_access_block.this]
}
