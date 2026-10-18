# Stopwatch (working name)

**Stop-level transit reliability for riders.** Stopwatch captures the MBTA's real-time feed every minute, infers when each bus and train actually arrived, and shows how reliable *your* stop is at *your* time. It runs 24/7 on a scale-to-zero AWS pipeline for under $1/month.

> **Status (2026-10-18):** planning and design complete; implementation not started. This README will become the project landing page at launch (see [docs/08 §1](docs/08-portfolio-kit.md)).

## Planning documents

| # | Doc | What it covers |
|---|---|---|
| 01 | [Market research](docs/01-market-research.md) | 91 US early-career SWE postings from 18 companies + 12 big-tech postings; demand matrix; conclusions |
| 02 | [Concept selection](docs/02-concept-selection.md) | 7 concepts scored; why the transit tracker won; $0-when-idle cost model |
| 03 | [Product spec](docs/03-product-spec.md) | Problem, users, workflows, user stories, metric definitions, success metrics, MVP and non-goals |
| 04 | [Architecture](docs/04-architecture.md) | Stack and justifications, diagrams, schema, inference algorithm, APIs, jobs, deployment, cost, scaling, decision log |
| 05 | [Security & reliability](docs/05-security-reliability.md) | Threat model, auth, OWASP mapping, privacy, rate limits, secrets, audit, SLOs, failure handling, backups, performance goals |
| 06 | [Quality & operations](docs/06-quality-operations.md) | Testing, CI/CD, Docker, Terraform, migrations, environments, scanning, monitoring, alarms, runbooks |
| 07 | [Repository & roadmap](docs/07-repo-and-roadmap.md) | Repo layout, MoSCoW scope, 16-week roadmap in hours, checkpoints, risks |
| 08 | [Portfolio kit](docs/08-portfolio-kit.md) | Docs to ship, résumé bullets, pitch, interview Q&A, tradeoffs, credibility checklist |

Research data and reproducible scripts: [`research/`](research/README.md).

## Stack at a glance

Python 3.13 · FastAPI · DuckDB · PostgreSQL (Neon) · React + TypeScript (Vite) · AWS Lambda, S3, EventBridge Scheduler, API Gateway, CloudFront · Terraform · GitHub Actions.
