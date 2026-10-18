# One-time account bootstrap (`make bootstrap GITHUB_REPO=owner/repo`). Never destroyed by `make down`.
#
#   1. The Terraform state bucket used by infra/envs/* (S3 backend with native lockfile, so no
#      DynamoDB lock table is needed).
#   2. The GitHub OIDC provider, per-environment deploy roles and permissions boundaries, and the
#      nightly-backup role (modules/github_oidc). They live here, not in the env roots, so that
#      destroying an environment can never delete the role that is performing the destroy.
#
# This root keeps its own state locally (terraform.tfstate in this directory, git-ignored): it is a
# chicken-and-egg root that creates the remote backend. Losing that file is recoverable with
# `terraform import`. Optionally move it into the bucket afterwards: add a backend "s3" block with
# key = "bootstrap/terraform.tfstate" and run `terraform init -migrate-state`.

terraform {
  required_version = ">= 1.11"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      project = "stopwatch"
      env     = "shared"
      owner   = var.owner
      ttl     = "none"
    }
  }
}

data "aws_caller_identity" "current" {}

locals {
  state_bucket_name = coalesce(var.state_bucket_name, "stopwatch-tfstate-${data.aws_caller_identity.current.account_id}")
}

# --- Terraform state bucket ------------------------------------------------------------------------

resource "aws_s3_bucket" "state" {
  #checkov:skip=CKV_AWS_18:Access logging for a single-operator state bucket would need a second bucket; CloudTrail event history covers bucket-level changes.
  #checkov:skip=CKV_AWS_144:Cross-region replication is unnecessary: infrastructure is reproducible from git, and versioning protects against bad writes.
  #checkov:skip=CKV_AWS_145:SSE-S3 instead of SSE-KMS: a customer-managed key costs $1/month, the whole budget.
  #checkov:skip=CKV2_AWS_62:No event notifications needed for state files.
  bucket = local.state_bucket_name

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_ownership_controls" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket                  = aws_s3_bucket.state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Versioning is the undo button for a corrupted or accidentally deleted state file.
resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "state" {
  bucket = aws_s3_bucket.state.id

  rule {
    id     = "prune-old-state-versions"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration {
      noncurrent_days           = 90
      newer_noncurrent_versions = 20 # always keep the last 20 versions, however old
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
}

data "aws_iam_policy_document" "state" {
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.state.arn, "${aws_s3_bucket.state.arn}/*"]
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

resource "aws_s3_bucket_policy" "state" {
  bucket     = aws_s3_bucket.state.id
  policy     = data.aws_iam_policy_document.state.json
  depends_on = [aws_s3_bucket_public_access_block.state]
}

# --- GitHub Actions OIDC + deploy roles ------------------------------------------------------------

module "github_oidc" {
  source = "../modules/github_oidc"

  github_repo                = var.github_repo
  environments               = var.environments
  backup_environments        = var.backup_environments
  state_bucket_name          = aws_s3_bucket.state.bucket
  create_oidc_provider       = var.create_oidc_provider
  existing_oidc_provider_arn = var.existing_oidc_provider_arn
}
