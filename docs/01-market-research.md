# 01 — Early-Career SWE Market Research (US, Mid-to-Big Tech)

*Phase 1 output · snapshot taken 2026-10-18 · raw data and scripts in [`research/`](../research)*

## TL;DR

- **Early-career roles are scarce.** Across 35 company job boards (6,716 US postings), only **91 postings at 18 companies** are early-career software engineering roles, and only **28 postings at 9 companies** are explicitly titled new grad / early career. 17 of the 35 boards had none. The bar is high, and a standout project is one of the few levers a candidate controls.
- **Postings ask for judgment more than tool lists.** The near-universal signals are product/user focus, cross-functional collaboration, end-to-end ownership, shipping to production, and scalability/reliability (16–17 of 18 companies). Specific infrastructure tools are rare at entry level: of the 9 companies with explicit new-grad postings, 0 mention Docker, 1 mentions Kubernetes and 1 mentions CI/CD.
- **AI has become a default expectation.** 15/18 companies mention AI/ML/LLMs. 11/18 now mention AI coding tools. Stripe and Pinterest require using AI to move faster *while validating its output*, and Amazon and Notion list AI-assisted development as a plus.
- **Personal projects count as experience.** Stripe, Roblox, Pinterest and Amazon explicitly accept side or personal projects as relevant experience in their new-grad postings.
- **The language picture is clear.** Python is the most-requested language (16/18), then TypeScript/JavaScript (11/18), React (10/18), and Java and Go (10/18 each). Relational SQL/Postgres is named far more often than NoSQL. In the separate 12-posting big-tech check, Python (10/12) and Java (8/12) lead and TypeScript doesn't appear at all, so TS/React mainly helps for full-stack roles at mid-size companies.
- **Generic new-grad openings at the very largest companies were scarce** on the snapshot day. Google, Meta, Uber and Netflix had no BS/MS new-grad SWE postings up. Microsoft (IC2), Salesforce, NVIDIA and Amazon did.

## Method

**Sources** (all public, read 2026-10-18):

- Greenhouse public job-board API for 27 companies: Stripe, Airbnb, Databricks, Datadog, Cloudflare, Robinhood, Coinbase, Dropbox, Pinterest, Lyft, Figma, Discord, Reddit, Twilio, Instacart, Roblox, GitLab, MongoDB, Elastic, Okta, Affirm, Samsara, Asana, Duolingo, Brex, Squarespace, Block
- Ashby public job-board API for 6 companies: Notion, Ramp, OpenAI, Linear, Plaid, Snowflake
- Lever public postings API: Palantir
- Amazon's careers search (amazon.jobs), all 1,180 US "software development engineer" results
- Separate posting-by-posting review of Google, Meta, Microsoft, Apple, Uber, Netflix, Salesforce and NVIDIA (see [Big-tech spot check](#big-tech-spot-check))

**Filtering** (code in [`research/scripts/filter.py`](../research/scripts/filter.py)):

1. US location only. Interns and co-ops excluded.
2. Software-engineering titles only (software, backend, frontend, full-stack, platform, product engineer, SDE). Sales, solutions, support, data science, ML research, hardware and design roles excluded.
3. **Tier A:** title explicitly says new grad, early career, university grad, "Software Engineer I/1", "SDE I" or emerging talent. Senior, staff, principal, lead and PhD titles excluded.
4. **Tier B:** non-senior software engineering title whose *headline* experience requirement is 2 years or less, or an Amazon SDE posting with no years requirement (the SDE I pattern).
5. Near-duplicate requisitions collapsed (same company, title and opening text).

**Counting.** A posting "mentions" a signal when a keyword pattern matches its text *after* stripping benefits, EEO and privacy boilerplate. Results are **company-weighted**: each company counts equally, so Amazon's volume can't dominate. Posting-level shares are in [`research/keyword-matrix.txt`](../research/keyword-matrix.txt).

**Limitations (please read).**

- The sample comes from companies that use Greenhouse, Ashby or Lever, plus Amazon. That skews it toward **fintech** (Stripe, Affirm, Robinhood, Ramp, Plaid, Coinbase) and **developer and productivity tools**, and leaves the largest companies out of the counts; they're covered separately by the 12-posting big-tech check.
- Keyword matching is a proxy. "Not mentioned" does not mean "not required": new-grad postings are deliberately vague, and interviews test things postings never list.
- This is a single October 2026 snapshot during new-grad hiring season. 71% of dated postings in the sample were published in 2026. A few evergreen postings (several at Palantir) are older but still open.
- 91 postings is enough to see patterns, not to make statistical claims.

## What the postings say (observed)

Paraphrased from the requirement sections. Links are in [Sources](#sources).

- **Stripe, Software Engineer, New Grad.** Minimum: a CS degree by summer 2027 or equivalent experience. Coding experience from side projects or classwork. Internships *or* collaborative multi-person projects. Clear written communication. Ability to use AI tools to move faster while critically validating their output. Preferred: code-review experience and knowing how to update production systems safely. Stripe says it works mostly in Java, Ruby, JavaScript, Scala and Go, and that languages can be learned.
- **Notion, Software Engineer, Early Career (AI variant too).** Under two years of experience. Fundamentals in data structures, algorithms and *distributed systems*. Customer-minded and pragmatic. Keeps current with tools like Cursor and Claude Code. The AI variant adds relational databases (Postgres/MySQL), taking a prototype to a working feature, evals, guardrails, and latency/cost work.
- **OpenAI, Software Engineer, Applied Emerging Talent (2027).** 0–1 years. JavaScript, React and a backend language ("we use Python"). Some Postgres/MySQL. Talks to users, owns features end to end, optimizes for speed and scale. Interest in AI, with direct experience not required.
- **Pinterest, University Grad Software Engineer 2027.** One or more years of programming through internships, coursework, *personal projects*, open source or hackathons. Uses AI as a coding partner with judgment about accuracy and *security*. CS fundamentals. Python, Java, JS/TS, Go or C++, plus React or similar. Product sense.
- **Amazon, Software Development Engineer, 2026 (US).** Basic: one general-purpose language (Java, Python, C++, C#, Go, Rust or TypeScript), data structures, algorithms and OO design, and a STEM degree. Preferred: internships *or demonstrated project experience*, AI tools for productivity, cloud (preferably AWS), SQL and NoSQL databases, open source, version control, and debugging complex systems.
- **Robinhood, Software Engineer 1, Backend.** 6 months to 2 years of experience. Python/Django or Go. A solid understanding of relational databases and *transaction-safe design*. CS fundamentals.
- **Affirm, Software Engineer, Early Career / SWE I.** Turns a business problem into a multi-component solution with clear, *well-tested*, extensible code. Navigates a large codebase, debugs others' code and gives code-review feedback. The full-stack variant wants JS/TS plus Python or Kotlin.
- **Roblox, Software Engineer, Early Career 2027.** Degree or equivalent practical experience. Software concepts learned through coursework, internships or *personal projects*. Any of C#, Lua, Java, Go, Node.js, Ruby, Python, C++ or Swift. Comfortable with ambiguity.
- **Palantir, Software Engineer, New Grad.** Familiarity with data structures, storage systems, cloud infrastructure and front-end frameworks. Java, C++, Python or JavaScript. Communicates with users and non-technical teammates.

**Pay (where stated, US base).** New-grad base ranges ran from **$101k–$151k** (lowest) to **$130k–$180k** (highest), and most started between $128k and $145k. Across all 37 sampled postings that stated pay, the median range was **$145k–$179k**.

## Demand matrix

The **Observed** columns are measured: the share of companies mentioning a signal (company-weighted), the number of companies, and the same for the 9 companies with explicit new-grad postings. **Conclusion** is my interpretation and **Project implication** is what follows for the portfolio project.

| Area | Signal | Observed (18 cos) | Observed (new-grad, 9 cos) | Conclusion | Project implication |
|---|---|---|---|---|---|
| **Languages** | Python | 52% · 16/18 | 8/9 | Most broadly requested | Primary backend language |
| | TypeScript · JavaScript | 38% (11/18) · 34% (11/18) | 5/9 · 7/9 | Expected for anything user-facing | Frontend in TypeScript |
| | Java · Go | 28% (10/18) · 26% (10/18) | 5/9 · 6/9 | Strong second languages, especially fintech and infra (Go) | Mention as learnable; don't split the project across 3 languages |
| | C++ · C# · Rust | 17% · 7% · 4% | 4/9 · 2/9 · 1/9 | Team-specific (systems, games) | Skip |
| **Frameworks** | React | 32% · 10/18 | 4/9 | The default frontend named | React |
| | Node · Django/Flask/FastAPI | 16% · 9% | 2/9 · 1/9 | Backend frameworks rarely named; companies hire for fundamentals | Choose for fit, not for keywords |
| | GraphQL · gRPC · Spring | ≤7% | 0/9 | Rare at entry level | Exclude |
| **Databases** | SQL / relational (Postgres, MySQL) | 40% · 11/18 | 4/9 | Relational modeling and transactions are expected | PostgreSQL with real schema design |
| | NoSQL | 14% · 6/18 | 3/9 | Secondary | No separate NoSQL store |
| | Caching (Redis) · queues/streaming | 15% · 12% | 1/9 · 1/9 | Rarely required for new grads; good to *discuss* | Use only if a measured need appears |
| **Cloud & infra** | Any cloud | 35% · 11/18 | 2/9 | Helpful, rarely required | Deploy to real cloud hosting |
| | AWS · GCP · Azure | 23% · 12% · 7% | 1/9 · 0 · 0 | AWS named most | AWS if the budget allows |
| | Docker · Kubernetes · Terraform | 11% · 18% · 6% | 0/9 · 1/9 · 0/9 | Not an entry-level filter | Docker yes; small IaC as a "should"; **no Kubernetes** |
| **APIs & design** | APIs | 40% · 12/18 | 3/9 | Building and consuming APIs is core | Well-documented public HTTP API |
| | Scalability | 80% · 16/18 | 9/9 | Universal language in postings | Measured performance goals and load tests |
| | Reliability · performance | 62% · 55% | 6/9 · 4/9 | Production quality matters | SLOs, retries, idempotency |
| | System design / architecture · distributed systems | 44% · 27% | 3/9 · 4/9 | Expected to discuss; seldom to have built | Modular monolith with clear seams; write the scaling story |
| | Microservices · REST (named) | 10% · 6% | 2/9 · 1/9 | Not a selling point | Avoid microservices |
| **Testing** | Testing / unit & integration tests | 44% · 14/18 | 5/9 | Well-tested code is a stated bar | Test pyramid in CI with a coverage floor |
| | Code quality / maintainability | 41% · 11/18 | 4/9 | — | Linting, typing, reviewable PRs |
| **Security** | Security (any) | 34% · 11/18 | 4/9 | Tied to production and AI use | Real authorization boundaries and an OWASP checklist |
| | Privacy/compliance · auth/identity | 12% · 11% | 1/9 · 0/9 | Domain-specific | Privacy by design, without over-claiming compliance |
| **DevOps** | Deploy / operate in production | 75% · 17/18 | 7/9 | Very strong signal | Public deployment with real operations |
| | On-call | 12% · 9/18 | 2/9 | Mid-level roles mention it | Runbooks and alerts show readiness |
| | CI/CD · Git named | 8% · 14% | 1/9 · 2/9 | Assumed, rarely stated | GitHub Actions, small PRs |
| **Observability** | Monitoring / observability | 32% · 11/18 | 3/9 | Valued, especially infra teams | Structured logs, metrics, traces, alerts |
| | Debugging / troubleshooting | 36% · 11/18 | 3/9 | Debugging others' code is called out | Incident write-ups (postmortems) |
| **Fundamentals** | DS&A / CS fundamentals | 34% · 11/18 | 5/9 | Screened in interviews regardless | An algorithmic core in the project helps |
| | CS degree or equivalent | 41% | 8/9 | Mostly flexible ("or equivalent") | — |
| **Collaboration** | Cross-functional collaboration | 92% · 17/18 | 9/9 | Universal | Issues, PRs, design docs, changelog |
| | Product / user focus | 83% · 17/18 | 9/9 | Universal | Real users, feedback loop, metrics |
| | Ownership / end-to-end | 76% · 17/18 | 7/9 | Universal | Solo full-stack ownership is a plus here |
| | Communication | 56% · 14/18 | 6/9 | Writing matters | High-quality README, ADRs, write-ups |
| | Code review · design docs | 29% · 14% | 3/9 · 0/9 | Valued, especially at Stripe and Affirm | PR descriptions, ADRs (short design-decision records) |
| | Agile/Scrum | 9% · 2/18 | 1/9 | Rarely mentioned | Skip the ceremony; use lightweight milestones |
| **AI** | AI/ML/LLM (any) | 69% · 15/18 | 7/9 | Mainstream | Include **one** load-bearing AI feature |
| | LLMs / agents specifically | 34% · 11/18 | 3/9 | Growing, team-specific | Evals, guardrails, cost limits, fallbacks |
| | AI coding tools, used critically | 33% · 11/18 | 4/9 | A new explicit expectation | Document how AI was used and how its output was verified |

## Conclusions (interpretation)

1. **Production judgment beats tool collecting.** Entry-level postings almost never require Kubernetes, Terraform or microservices, but nearly all ask for ownership, reliability, testing and working in production. The project should *demonstrate* judgment (tradeoffs, failure handling, measured performance) and keep infrastructure small and well-justified.
2. **Real users and product sense are the differentiators.** "Product/user focus" appears at 17/18 companies. A project with even a handful of real users and a feedback loop stands out from projects built only as technical showcases.
3. **AI must be load-bearing and verified.** AI is now expected, but postings frame it in terms of *judgment*: validating outputs, security, evals, cost. A thin "chat with your data" wrapper is the wrong signal. A measured AI component with a fallback is the right one.
4. **Python + TypeScript/React + PostgreSQL** is the highest-coverage stack among the companies sampled. Python is the strongest single choice across both samples, and TypeScript/React covers the frontend expectation at mid-size companies. Java or Go can be described as a second language rather than built into the project.
5. **Writing is part of the job.** Communication, design docs and code review show up repeatedly. The repository's docs (README, ADRs, runbooks, postmortems) are part of the portfolio, not paperwork.

## Big-tech spot check

The largest companies' career sites can't be bulk-pulled, so 12 US early-career software engineering postings were read individually on 2026-10-18 (plus one Meta posting that isn't a SWE role). These are **not** included in the counts above.

| Company | Posting | Pay (base) | Notable requirements |
|---|---|---|---|
| Microsoft | [Software Engineer (IC2), Intune](https://apply.careers.microsoft.com/careers/job/1970393557038974), Cambridge MA | $85k–$168k ($111k–$184k SF/NYC) | BS or equivalent; one of C, C++, C#, Java, JS, Python; uses AI tools "with appropriate oversight"; safe releases |
| Microsoft | [Software Engineer, Microsoft Security](https://apply.careers.microsoft.com/careers/job/1970393557026652), Redmond | same | Build, test and debug backends in C#, Java or Python; DS&A; AI-assisted development while *validating its output*; secure development, telemetry, live-site, code reviews |
| Microsoft | [Software Engineer – Forward Deployed](https://apply.careers.microsoft.com/careers/job/1970393557027406), Redmond | same | Projects or internships; code reviews, automated testing, CI/CD, observability, docs, security-first development |
| Google | [SWE, Infrastructure, PhD, Early Career 2027](https://www.google.com/about/careers/applications/jobs/results/84680705375642310) | $147k–$210k + bonus | PhD; distributed systems and concurrency; testability; design docs |
| Google | [SWE, AI/ML, PhD, Early Career 2027](https://www.google.com/about/careers/applications/jobs/results/123087196289671878) | same | PhD; ML; full AI app stack (pipelines, APIs, UI); well-tested code |
| Apple | [SWE – AiDP Reliability Eng., IS&T Early Career](https://jobs.apple.com/en-us/details/200677645-0157), Austin | not shown | Python, Java or Go; an internship is a *minimum*; operating production services; distributed systems |
| Apple | [Frontend Engineer, IS&T Early Career](https://jobs.apple.com/en-us/details/200676168-0157), Austin | not shown | JS/HTML/CSS or Java/Python; CS fundamentals; AWS or GCP preferred |
| Uber | [PhD 2026 Grad SWE II (AV Labs)](https://jobs.uber.com/en/jobs/301355/), Sunnyvale | $171k–$190k | PhD; distributed systems, algorithms, scalable design |
| Salesforce | Software Engineering AMTS (College Grad), Workday req JR355250-1 | $114k–$153k | OOP; Java, Python, JS, SQL or C++; *critically reviewing LLM-generated code*; heavy on testing; telemetry |
| Salesforce | AI Labs Rotational Fellowship, Emerging Talent, req JR363678-1 | $114k–$147k | DS&A, Python, AI/ML basics; portfolio or open source preferred |
| NVIDIA | SoC Software Engineer – New College Grad 2027, req JR2026744 | $108k–$196k by level | C/C++, firmware/drivers, computer architecture |
| NVIDIA | SWE, DL Kernel Libraries – New College Grad 2027, req JR2027337 | same | PyTorch/JAX, CUDA/Triton, Python + C++ |

**Observed (out of 12):**

- **Experience:** 0 require paid experience. 2 require an internship or professional coding as a minimum (Apple, Salesforce).
- **Degree:** 8 accept "or equivalent experience". 3 are PhD-only.
- **Languages:** Python 10, Java 8, C/C++ 8, JavaScript 6, Rust 4, Go 3, C# 3, **TypeScript 0**. Most phrase it as "one of" a list.
- **Infrastructure:** a cloud provider is named in 1. Kubernetes in 1.
- **AI:** AI-assisted coding is asked for in 5 (all Microsoft and Salesforce postings). Both postings that name specific tools stress *reviewing and validating AI output*.
- **Engineering practices:** testing 6, distributed systems 5, explicit DS&A 4 (plus 2 that say only "CS fundamentals"), code review 4, design docs 4, CI/CD or safe deployment 4, security practices 3, observability 3, agile 0, explicit on-call 0.
- **Availability:** no BS/MS SWE new-grad openings were listed at **Google, Meta, Uber or Netflix** that day. Meta's university-grad SWE posting had been taken down, and Netflix's lowest SWE level required 3+ years.

**What this adds to the conclusions:**

1. Big tech is language-agnostic at entry level. Python and Java are the safest bets, and TypeScript matters mainly for full-stack roles at mid-size companies.
2. Testing, CI/CD, observability and security are described as *what you'll do on the job*, not as filters. A project that already does them credibly answers "can this person operate in our environment?"
3. "Uses AI tools, but verifies the output" now appears in writing at Microsoft, Salesforce, Stripe and Pinterest.
4. Generic new-grad openings at the very largest companies were scarce in this snapshot. That's possibly timing, but it reinforces that mid-size companies (where project deep-dives carry more weight) are a large part of the realistic target.

Access notes: Google, Apple, Microsoft (Eightfold), Netflix (Eightfold), Salesforce and NVIDIA (Workday) were read via their public site data. Meta and Uber block scripted requests and were read in a browser.

## Sources

Explicit new-grad / early-career postings (Tier A) read for this analysis:

| Company | Title | Posted | Link |
|---|---|---|---|
| Affirm | Software Engineer, Early Career (NYC) | 2026-10-06 | [greenhouse](https://job-boards.greenhouse.io/affirm/jobs/8008649003) |
| Affirm | Software Engineer, Early Career (SF) | 2026-10-06 | [greenhouse](https://job-boards.greenhouse.io/affirm/jobs/8010617003) |
| Affirm | Software Engineer I, Fullstack (Search) | 2026-10-15 | [greenhouse](https://job-boards.greenhouse.io/affirm/jobs/8017342003) |
| Amazon | Software Development Engineer – 2026 (US) | 2026-02-10 | [amazon.jobs](https://www.amazon.jobs/en/jobs/3177934/software-development-engineer-2026-us) |
| Amazon | SDE, AWS Data Services – 2026 (US) | 2026-05-07 | [amazon.jobs](https://www.amazon.jobs/en/jobs/10414316/software-development-engineer-aws-data-services-2026-us) |
| Amazon | SDE, Amazon Leo, Early Career – 2026 | 2026-08-25 | [amazon.jobs](https://www.amazon.jobs/en/jobs/10513110/software-development-engineer-amazon-leo-early-career-2026) |
| Amazon | SDE, Amazon Dedicated Cloud, Early Career – 2026 | 2026-09-04 | [amazon.jobs](https://www.amazon.jobs/en/jobs/10529546/software-development-engineer-amazon-dedicated-cloud-early-career-2026-amazon-dedicated-cloud-adc) |
| Amazon (Audible) | SDE, Early Career | 2026-09-04 | [amazon.jobs](https://www.amazon.jobs/en/jobs/10530257/software-development-engineer-early-career) |
| Amazon (Annapurna Labs) | SDE I, Early Career – 2027 | 2026-09-24 | [amazon.jobs](https://www.amazon.jobs/en/jobs/10558915/software-development-engineer-i-annapurna-labs-early-career-2027) |
| Amazon (Annapurna Labs) | SDE I – AI/ML Network Infrastructure | 2026-08-03 | [amazon.jobs](https://www.amazon.jobs/en/jobs/10490741/software-development-engineer-i-ai-ml-network-infrastructure-annapurna-labs) |
| Amazon | SDE, Robotics, Early Career – 2027 | 2026-10-01 | [amazon.jobs](https://www.amazon.jobs/en/jobs/10567489/software-development-engineer-robotics-early-career-2027) |
| Notion | Software Engineer, Early Career | 2026-07-06 | [ashby](https://jobs.ashbyhq.com/notion/297b4ece-765f-4eea-b1b8-46057cb6501f) |
| Notion | Software Engineer, Early Career (AI) | 2026-07-06 | [ashby](https://jobs.ashbyhq.com/notion/85947779-6b87-466a-98bc-30a640448c28) |
| Notion | Software Engineer, New Grad (Dec 2026) | 2026-08-14 | [ashby](https://jobs.ashbyhq.com/notion/e32799d2-8ef8-4803-8189-c72514afa816) |
| OpenAI | Software Engineer, Applied Emerging Talent (2027) | 2026-09-14 | [ashby](https://jobs.ashbyhq.com/openai/55150071-fce8-48f5-aea4-14ed78b83511) |
| Palantir | Software Engineer, New Grad | 2021-07-01 (evergreen) | [lever](https://jobs.lever.co/palantir/94984771-0704-446c-88c6-91ce748f6d92) |
| Palantir | Software Engineer, New Grad – Infrastructure | 2025-06-26 | [lever](https://jobs.lever.co/palantir/4abf26b4-795c-420a-bf22-1ab98db268b4) |
| Palantir | Software Engineer, New Grad – Production Infrastructure | 2025-08-19 | [lever](https://jobs.lever.co/palantir/15844944-fb69-4b57-9531-e988650b20c6) |
| Palantir | Software Engineer, New Grad – Defense | 2025-06-19 | [lever](https://jobs.lever.co/palantir/0a838e66-1ab0-4fc4-b4d3-4671c0352278) |
| Palantir | Forward Deployed SWE, New Grad – Commercial | 2025-06-13 | [lever](https://jobs.lever.co/palantir/2e6b0ac8-83e9-4be5-a3aa-cf319f751728) |
| Palantir | Forward Deployed SWE, New Grad – Intel, US Gov | 2026-06-15 | [lever](https://jobs.lever.co/palantir/fbca0358-083a-4222-bdbb-3bd729b48382) |
| Palantir | Forward Deployed SWE, New Grad – US Gov | 2022-06-30 | [lever](https://jobs.lever.co/palantir/cbe90327-3e6e-451c-a54c-1d3cbcef5aeb) |
| Palantir | Forward Deployed Infrastructure Eng., New Grad – US Gov | 2025-10-29 | [lever](https://jobs.lever.co/palantir/33243fb5-6907-40c7-930c-968b25d825d0) |
| Pinterest | University Grad Software Engineer 2027 (USA) | 2026-10-01 | [pinterestcareers](https://www.pinterestcareers.com/jobs/?gh_jid=7838591) |
| Robinhood | Software Engineer 1, Backend | 2025-09-27 | [greenhouse](https://boards.greenhouse.io/robinhood/jobs/7263578) |
| Roblox | [2027] Software Engineer, Early Career | 2026-08-05 | [roblox careers](https://careers.roblox.com/jobs/8072244?gh_jid=8072244) |
| Stripe | Software Engineer, New Grad | 2026-08-31 | [stripe](https://stripe.com/jobs/search?gh_jid=8128744) |
| Stripe | Software Engineer, Early Career — Immediate Start | 2026-09-17 | [stripe](https://stripe.com/jobs/search?gh_jid=8212508) |

The 63 Tier B postings (≤2 years required) are listed with links in [`research/early-career-sample.csv`](../research/early-career-sample.csv).
