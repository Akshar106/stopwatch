# Security policy

Stopwatch stores a small amount of personal data, including saved commutes that can reveal where and when someone travels. Reports that help protect it are very welcome.

## Reporting a vulnerability

**Please report privately. Do not open a public issue, discussion or pull request for a security problem.**

- Preferred: GitHub **private vulnerability reporting** on this repository (*Security* tab → *Report a vulnerability*).
- Alternatively, email **[security contact email — to be added before launch]**.

Please include:

- What the issue is and what an attacker could do with it.
- Steps to reproduce (URLs, requests, payloads), and the environment you tested.
- Any account IDs you used (your own or demo accounts only), and the time of testing in UTC, so we can find it in our logs.

What to expect (this is a one-person project, so these are best-effort targets):

| Step | Target |
|---|---|
| Acknowledge your report | within 3 business days |
| Initial assessment and severity | within 7 days |
| Fix for high or critical issues | within 30 days, sooner where possible |
| Tell you when it is fixed, and credit you in the changelog if you wish | on release |

If personal data was exposed, affected users are notified as described in the [privacy policy](docs/privacy.md).

## Scope

**In scope**

- The production web app and API (`/api/v1/*`) and the published data (`/data/v1/*`).
- The code in this repository: backend, frontend, infrastructure (Terraform) and CI/CD workflows.
- Examples: access to another user's commutes or account (IDOR/BOLA), authentication or session flaws, CSRF, XSS, injection, SSRF through feed handling, secrets in the repository or its history, misconfigured S3/CloudFront/IAM, reaching the API without going through CloudFront (the `X-Origin-Verify` check) or spoofing the client IP used for rate limits, ways to drive up our AWS bill substantially with little effort.

**Out of scope**

- The MBTA's feeds and APIs, Google sign-in, AWS, Neon, and other third-party services themselves (report to them directly).
- Denial of service by volume, load testing or automated scanning against production at more than a few requests per second.
- Social engineering, phishing, or physical attacks.
- Reports from automated tools without a demonstrated impact (for example, missing headers that do not lead to an exploit, or software version banners).
- The accuracy of published reliability estimates (please use the data-quality issue template instead).

## Testing guidelines (safe harbor)

We will not pursue or support legal action against good-faith research that follows these rules:

- Use **demo accounts** or your own account; never access, modify or delete other people's data. If you reach someone else's data by accident, stop, don't keep it, and tell us.
- Keep request rates low (no more than a few requests per second) and do not degrade the service for others.
- Do not exfiltrate secrets or use them; reporting that you could is enough.
- Give us a reasonable time to fix the issue before disclosing it publicly; we'll agree on a date with you.

## Supported versions

Only the **currently deployed version** (the latest commit on `main`) is supported. Stopwatch is pre-1.0 and has no long-term support branches; fixes are deployed to production rather than backported.

| Version | Supported |
|---|---|
| `main` / production | Yes |
| Older commits and tags | No |

## How we handle security internally

The threat model, controls and their tests are in [docs/05-security-reliability.md](docs/05-security-reliability.md). Incident handling for leaked secrets or compromised accounts is in [runbook RB-6](docs/runbooks/RB-6-secret-leak.md).
