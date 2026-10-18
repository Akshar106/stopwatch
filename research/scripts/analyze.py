"""Keyword prevalence across early-career postings, weighted equally per company."""
import collections, csv, json, re, statistics, sys

rows = json.load(open(sys.argv[1]))
CSV_OUT = sys.argv[2]

TERMS = {
    "Languages": {
        "Python": r"\bpython\b", "Java": r"\bjava\b(?!\s*script)", "Go": r"(?-i:golang|(?:Python|Java|C\+\+|Rust|TypeScript|Ruby|Scala|Kotlin|C#)[^.]{0,40}\bGo\b|\bGo\b[^.]{0,40}(?:Python|Java|C\+\+|Rust|TypeScript|Ruby|Scala|Kotlin))",
        "TypeScript": r"\btypescript\b", "JavaScript": r"\bjavascript\b|\bjs\b", "C++": r"c\+\+",
        "C#/.NET": r"\bc#|\.net\b", "Rust": r"\brust\b", "Kotlin": r"\bkotlin\b", "Scala": r"\bscala\b",
        "Ruby": r"\bruby\b", "SQL": r"\bsql\b", "Swift": r"\bswift\b",
    },
    "Frameworks": {
        "React": r"\breact\b", "Node.js": r"\bnode(\.js|js)?\b", "Spring": r"\bspring\b", "Django/Flask/FastAPI": r"\b(django|flask|fastapi)\b",
        "Rails": r"\brails\b", "GraphQL": r"\bgraphql\b", "gRPC": r"\bgrpc\b", "Next.js": r"\bnext\.?js\b",
    },
    "Databases & data": {
        "SQL / relational": r"\bsql\b|relational|postgres|mysql", "PostgreSQL": r"postgres", "MySQL": r"mysql",
        "NoSQL": r"\bnosql\b|dynamodb|mongodb|cassandra", "Redis/caching": r"\bredis\b|\bcach(e|ing)\b",
        "Kafka/queues/streaming": r"\bkafka\b|message queue|\bqueues?\b|\bstreaming\b|\bsqs\b|pub/?sub",
        "Spark/data pipelines": r"\bspark\b|data pipeline|\betl\b",
    },
    "Cloud & infra": {
        "AWS": r"\baws\b|amazon web services", "GCP": r"\bgcp\b|google cloud", "Azure": r"\bazure\b",
        "Kubernetes": r"kubernetes|\bk8s\b", "Docker/containers": r"docker|container", "Terraform/IaC": r"terraform|infrastructure[- ]as[- ]code|\biac\b|cloudformation|\bcdk\b",
        "Cloud (any)": r"\bcloud\b",
    },
    "APIs & architecture": {
        "APIs": r"\bapis?\b", "REST": r"\brest(ful)?\b", "Microservices": r"micro-?services?", "Distributed systems": r"distributed (systems?|computing)",
        "Scalability": r"scal(able|ability|e\b|ing)", "System design/architecture": r"system design|architect(ure|ing)|design (and|&) (build|implement)",
        "Reliability/availability": r"reliab|availability|fault[- ]toleran|resilien", "Performance/latency": r"performance|latency|throughput",
    },
    "Testing & quality": {
        "Testing (any)": r"\btest(s|ing|able)?\b", "Unit/integration tests": r"unit test|integration test|end-to-end|e2e",
        "Code quality/maintainability": r"code quality|maintainab|clean code|best practices|readab",
    },
    "Security & privacy": {
        "Security (any)": r"\bsecur(e|ity)\b", "Privacy/compliance": r"privacy|compliance|regulat|gdpr|pci|sox|fedramp",
        "Auth/identity": r"authenticat|authoriz|oauth|identity|access control",
    },
    "DevOps & delivery": {
        "CI/CD": r"ci/cd|continuous (integration|delivery|deployment)", "Deploy/operate in production": r"production|deploy|operat(e|ing|ional)",
        "On-call": r"on[- ]call", "Git/version control": r"\bgit\b|version control|github",
    },
    "Observability": {
        "Monitoring/observability": r"monitor|observab|telemetry|logging|metrics|alert|tracing|datadog|prometheus|grafana",
        "Debugging/troubleshooting": r"debug|troubleshoot|root cause|incident",
    },
    "Fundamentals": {
        "CS fundamentals (DS&A)": r"data structures|algorithm|computer science fundamental|cs fundamental",
        "CS degree or equivalent": r"(bachelor|b\.?s\.?|degree).{0,80}(computer science|engineering|technical field)|equivalent (practical )?experience",
        "OOP/design patterns": r"object[- ]oriented|design patterns|\boop\b",
    },
    "Collaboration & product": {
        "Cross-functional collaboration": r"cross[- ]functional|collaborat|partner with|work closely",
        "Communication": r"communicat",
        "Code review": r"code review",
        "Design docs/technical specs": r"design doc|technical (spec|design)|rfc",
        "Ownership/end-to-end": r"ownership|end[- ]to[- ]end|own (the|features|projects)",
        "Product/user focus": r"customer|user experience|users?\b|product sense|product[- ]minded",
        "Agile/scrum": r"\bagile\b|scrum|sprint",
        "Learning/growth mindset": r"learn quickly|eager to learn|curious|curiosity|growth mindset|fast learner",
    },
    "AI": {
        "AI/ML/LLM (any)": r"\bai\b|machine learning|\bml\b|\bllms?\b|generative|genai|large language model",
        "LLMs/agents specifically": r"\bllms?\b|large language model|\bagents?\b|agentic|\brag\b|prompt",
        "AI coding tools": r"ai[- ](assisted|powered) (coding|development)|copilot|cursor|claude code|ai (coding )?tools|coding (assistants?|agents?)|ai[- ]native",
    },
}

def company(r):
    return r["company"].split(" (")[0]

by_co = collections.defaultdict(list)
for r in rows:
    by_co[company(r)].append(r)

BOILER = re.compile(r"equal (employment )?opportunit|\beeo\b|pay transparency|privacy (notice|policy)|reasonable accommodation|"
                     r"benefits (include|package)|our benefits|compensation (range|and benefits)|the (expected|annual) (base )?(salary|pay)|"
                     r"applicant privacy|e-verify|use of ai in|ai disclaimer", re.I)

def core(text):
    cut = len(text)
    for m in BOILER.finditer(text):
        if m.start() > 0.35 * len(text):
            cut = min(cut, m.start())
    return text[:cut]

hits = {}
for r in rows:
    txt = r["title"] + " " + core(r["text"])
    hits[id(r)] = {(cat, k) for cat, terms in TERMS.items() for k, p in terms.items() if re.search(p, txt, re.I)}

def shares(subset_rows):
    co = collections.defaultdict(list)
    for r in subset_rows:
        co[company(r)].append(r)
    res = {}
    for cat, terms in TERMS.items():
        for k in terms:
            per_co = [sum((cat, k) in hits[id(r)] for r in rs) / len(rs) for rs in co.values()]
            post = sum((cat, k) in hits[id(r)] for r in subset_rows) / len(subset_rows)
            any_co = sum(any((cat, k) in hits[id(r)] for r in rs) for rs in co.values())
            res[(cat, k)] = (statistics.mean(per_co), post, any_co, len(co))
    return res

tier_a = [r for r in rows if r["tier"] == "A"]
s_all, s_a = shares(rows), shares(tier_a)
print(f"Sample: {len(rows)} postings / {len(by_co)} companies (tier A: {len(tier_a)} postings / {len({company(r) for r in tier_a})} cos)")
print(f"{'category':26s}{'term':32s}{'co-wtd':>7s}{'posts':>7s}{'#cos':>6s} | {'A co-wtd':>8s}{'A #cos':>7s}")
for (cat, k), (cw, p, n, N) in s_all.items():
    a = s_a[(cat, k)]
    print(f"{cat[:25]:26s}{k[:31]:32s}{cw:7.0%}{p:7.0%}{n:4d}/{N} | {a[0]:8.0%}{a[2]:4d}/{a[3]}")

# Pay ranges (US base) where stated
pay = []
for r in rows:
    m = re.search(r"\$\s?(\d{2,3})[,.]?(\d{3})?\s*(k|K)?\s*(?:-|–|—|to)\s*\$?\s?(\d{2,3})[,.]?(\d{3})?\s*(k|K)?", r["text"])
    if m:
        lo = int(m.group(1)) * (1000 if (m.group(3) or not m.group(2)) else 1) if not m.group(2) else int(m.group(1) + m.group(2))
        hi = int(m.group(4)) * 1000 if not m.group(5) else int(m.group(4) + m.group(5))
        if 60000 <= lo <= 300000 and lo < hi <= 400000:
            pay.append((company(r), r["tier"], lo, hi))
if pay:
    print("\nStated base pay (n=%d): median low %s, median high %s" % (len(pay), statistics.median(p[2] for p in pay), statistics.median(p[3] for p in pay)))
    print("Tier A pay:", [(c, lo, hi) for c, t, lo, hi in pay if t == "A"])

with open(CSV_OUT, "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["company", "tier", "title", "location", "posted", "min_years_stated", "url"])
    for r in sorted(rows, key=lambda r: (r["tier"], company(r), r["title"])):
        w.writerow([company(r), r["tier"], r["title"], r["loc"][:80], r["posted"], r["min_years"], r["url"]])
