# Infrastructure

Terraform (≥ 1.11, AWS provider) for Stopwatch on AWS us-east-1. Nothing here runs until you apply it, and every environment can be removed again with one command.

```text
bootstrap/        one-time: Terraform state bucket + GitHub OIDC deploy roles (never destroyed by `make down`)
modules/          storage, functions, scheduler, api, edge, observability, budget, secrets, github_oidc
envs/staging/     ingest schedule disabled by default; alarms/dashboards/budgets off (free tier is per account)
envs/prod/        everything on; data buckets protected (force_destroy = false)
```

Resource counts from a mocked `terraform test` apply: prod 114, staging 99, bootstrap 26.

## One-time setup

1. **Account hygiene.** Turn on MFA for root and use an admin IAM Identity Center user. Request a **Lambda concurrent-executions quota increase**: new accounts allow 10, AWS keeps 10 of them unreserved, and each environment reserves 17 across its functions (`reserve_concurrency = true`, the default). While the request is pending you can deploy with `reserve_concurrency = false`: functions run unreserved, bounded only by the account limit. Set it back to `true` and apply once the increase is approved.
2. **Bootstrap.** Run `make bootstrap GITHUB_REPO=<owner/repo> OWNER=<you>`, then `export TF_STATE_BUCKET=<output bucket>`. Newer GitHub repositories issue immutable OIDC subjects: if `gh api repos/<owner>/<repo>/actions/oidc/customization/sub` shows `"use_immutable_subject": true`, put its `sub_claim_prefix` in `infra/bootstrap/terraform.tfvars` as `github_subject_prefix`, or CI fails with "Not authorized to perform sts:AssumeRoleWithWebIdentity".
3. **Neon.** Create a free project. Create an owner role (migrations) and an app login role, and grant `stopwatch_app_role` to the app role after the first migration. Use a `staging` branch for staging.
4. **First apply.** Copy `envs/<env>/terraform.tfvars.example` to `terraform.tfvars`. It is git-ignored because it holds your email. Then run `make up ENV=staging`.
5. **Secrets.** Terraform creates SSM SecureString parameters under `/stopwatch/<env>/` with the value `unset`. Set the real values with the CLI so they never enter Terraform state:
   ```bash
   aws ssm put-parameter --overwrite --type SecureString --name /stopwatch/staging/database_url --value '<app role URL>'
   ```
   Do the same for `database_owner_url`, `session_secret`, `google_client_id`, `google_client_secret`, and optionally `vapid_public_key`, `vapid_private_key` and `groq_api_key`. `origin_verify_secret` is the one value Terraform generates itself (docs/05 §2).
6. **Migrations.** Run `make migrate-cloud ENV=staging`.
7. **Google OAuth.** Add `<public_base_url>/api/v1/auth/callback` as an authorized redirect URI.
8. **Alerts.** Confirm the SNS subscription email. Budgets alert at $1 actual and $5 forecast.

## GitHub Actions configuration

| Where | Name | Purpose |
|---|---|---|
| Repo variables | `TF_STATE_BUCKET`, `OWNER`, `STAGING_URL` | Terraform backend, tags, smoke tests |
| Repo variables | `PROD_REQUIRE_MANIFEST` (`false` until the first rollup publishes), `STAGING_HAS_DATA` | Smoke-test strictness |
| Repo secrets | `ALERT_EMAIL` | SNS subscription |
| Repo secrets | `NEON_API_KEY` (optional) | Migration rehearsal on a Neon branch |
| Environment `staging` / `prod` | `AWS_DEPLOY_ROLE_ARN` | OIDC role (no long-lived keys); add required reviewers on `prod` |
| Environment `staging` / `prod` | `TERRAFORM_TFVARS` (optional) | HCL lines CI writes to `ci.auto.tfvars`, e.g. `ingest_enabled = true`, so a push doesn't revert settings you set in a local `terraform.tfvars` |
| Environment `prod` | `NEON_PROJECT_ID`, `NEON_PARENT_BRANCH`, `NEON_DATABASE`, `NEON_OWNER_ROLE` (optional) | Migration rehearsal |
| Environment `prod-backup` | `AWS_BACKUP_ROLE_ARN`, `LAKE_BUCKET` | Nightly `pg_dump` upload |
| Repo variables | `PROD_BACKUP_ENABLED` | `true` turns on the nightly prod backup job (leave unset until prod exists) |
| Repo variables | `PROD_ENABLED` | `true` adds the approval-gated prod job to each Deploy run (leave unset until prod exists, so pushes don't queue a prod deploy) |

## Day-to-day

| Command | Does |
|---|---|
| `make plan ENV=…` | Terraform plan |
| `make up ENV=…` | Package → apply → promote Lambda aliases (+ SPA if built) |
| `make deploy-code ENV=…` | Publish new Lambda versions, move `live` aliases, upload SPA, invalidate `/index.html` |
| `make rollback FN=<function>\|all ENV=…` | Move a `live` alias back one version |
| `make rollback-site ENV=…` | Restore the previous `index.html` |
| `make publish-rollback BUILD=<id> ENV=…` | Point the data manifest at an earlier build |
| `make down ENV=…` | Destroy the environment (prod requires `ALLOW_DATA_DESTROY=1`) |

## Notes and deliberate choices

- **Lambdas outside a VPC:** no NAT gateway (≈ $32/month saved); [ADR-010](../docs/adr/0010-lambdas-outside-vpc.md).
- **Packages through an artifacts bucket:** `jobs.zip` (~58 MB) is over Lambda's 50 MB direct-upload limit. Wheels target `aarch64-manylinux_2_28`.
- **API origin:** `/api/*` uses the managed `AllViewerExceptHostHeader` origin request policy. It forwards `CloudFront-Viewer-Address` and drops `Host`, which API Gateway needs. CloudFront adds `X-Origin-Verify`.
- **Lifecycle on the lake:** `events/` 14 days, `raw/` 7 days, `backups/` 30 days. Noncurrent versions of the per-minute `state/` object expire after 1 day.
- **Checkov:** 287 passed, 0 failed; each of the 75 skips carries an inline reason.
