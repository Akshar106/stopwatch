# ADR-010: Run all Lambda functions outside a VPC

- **Status:** Accepted, 2026-10-18
- **Deciders:** project author
- **Related:** [04 §4](../04-architecture.md#4-containers-and-deployment-aws-us-east-1), [05 §3, §8](../05-security-reliability.md#8-secrets-management), [06 §4](../06-quality-operations.md#4-infrastructure-as-code-terraform), [ADR-004](0004-neon-free-postgres-over-rds.md), RB-6

## Context

Every Stopwatch function needs the public internet or public AWS endpoints:

- `ingest-tick` and `schedule-import` fetch `cdn.mbta.com`.
- `api` calls Google's token and JWKS endpoints, and Neon over TLS.
- `notify` calls browser push services; Ask calls an LLM API.
- All functions call S3, SSM and CloudWatch.

A Lambda attached to a VPC has no internet access unless its subnets route through a **NAT gateway** (≈ $32/month per AZ for the hourly charge alone, before data processing) or through **interface VPC endpoints** (each billed hourly per AZ, and they do not reach MBTA, Google or Neon at all). Either option is roughly 60× the whole planned bill of ≈ $0.55/month ([04 §10.1](../04-architecture.md#101-cost-estimate-prod-steady-state-after-any-credits)).

There is no database inside AWS to protect with network isolation: Neon is a hosted service reached over the internet ([ADR-004](0004-neon-free-postgres-over-rds.md)). Neon's IP allow-list cannot be used because Lambda egress IPs are not fixed.

## Decision

- All functions run **without VPC configuration**.
- Compensating controls, so that credentials and TLS carry the protection a private network would otherwise add:
  - **TLS everywhere:** Neon with `sslmode=verify-full`; S3 bucket policies deny non-TLS (`aws:SecureTransport`); CloudFront TLSv1.2_2021.
  - **Scoped database credentials:** the runtime uses `stopwatch_app` (DML only; insert/select on `audit_log`); `stopwatch_owner` is used only by migrations and `maintenance`. `ingest-tick` and `notify` hold no owner credentials, and `ingest-tick` holds no database credentials at all.
  - **Secrets in SSM SecureString** under `/stopwatch/{env}/`, loaded at cold start, never in Terraform state, never logged; gitleaks in pre-commit and CI.
  - **Least-privilege IAM** per function ([contracts §1](../contracts.md#iam-least-privilege)); reserved concurrency on every function.
  - **Egress is fixed by configuration:** feed URLs come from `platform/agencies.py`, never from user input; no cross-host redirects; byte caps and timeouts on every fetch.
  - **Edge trust instead of network trust for the API:** the `api` function accepts only requests carrying CloudFront's `X-Origin-Verify` secret, and takes the client IP only from `CloudFront-Viewer-Address` ([ADR-005](0005-api-gateway-http-api-over-function-urls.md)).
  - **Rotation runbook** for every secret (RB-6).
- The IaC scanner's "Lambda not in a VPC" finding (Checkov `CKV_AWS_117`) is suppressed **inline with a reference to this ADR**, not globally.

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| **VPC + NAT gateway** | ≈ $32/month minimum; breaks the budget by two orders of magnitude for isolation of a database that is not in the VPC anyway. |
| **VPC + interface endpoints only** (S3 gateway endpoint is free; SSM, Logs, Lambda endpoints are hourly) | Several dollars a month per endpoint per AZ and still no route to MBTA, Google, Neon or push services. |
| **NAT instance** (a small EC2 doing NAT) | Cheaper than a NAT gateway but always on, a patching burden, and a single point of failure for ingestion. |
| **Neon private networking (PrivateLink)** | Available only on paid Neon plans and still requires a VPC with endpoints. |

## Consequences

**Positive**

- Saves ≈ $32+/month and keeps the bill near $0.55.
- No ENI cold-start overhead, no subnet/IP exhaustion, simpler Terraform.
- Fewer moving parts in the ingest path, which carries the main SLO.

**Negative**

- **No network-level isolation of database access.** Anyone holding a valid Neon connection string can connect from anywhere; protection rests on credential secrecy, TLS and role scoping. A leaked `database_url` is a SEV-2 handled by RB-6.
- Egress cannot be restricted by security groups; an exploited function could reach arbitrary hosts. IAM scoping limits what it could do with AWS, not where it could send data.
- Security reviewers and scanners will flag the decision; the inline justification and this ADR must stay current.

## Revisit when

- Stopwatch stores more sensitive data than saved commutes (for example precise locations or payment data).
- The database moves into AWS (RDS/Aurora) or Neon private networking becomes affordable.
- The budget grows to the point where ≈ $32/month for a NAT gateway is acceptable.
