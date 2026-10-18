# Remote state in the bootstrap bucket. S3-native locking (use_lockfile) writes
# staging/terraform.tfstate.tflock next to the state, so no DynamoDB table is needed (Terraform >= 1.10).
#
# The bucket name is a placeholder: `make` and CI pass the real one with
#   terraform init -backend-config="bucket=$TF_STATE_BUCKET"
# (from `terraform -chdir=infra/bootstrap output -raw state_bucket_name`).
terraform {
  backend "s3" {
    bucket       = "stopwatch-tfstate-REPLACE-ME"
    key          = "staging/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}
