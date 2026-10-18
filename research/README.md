# Research data

Snapshot of public job-board data behind [`docs/01-market-research.md`](../docs/01-market-research.md), taken 2026-10-18.

| File | What it is |
|---|---|
| `early-career-sample.csv` | The 91 US early-career SWE postings analyzed (company, tier, title, location, posted date, stated min years, URL) |
| `keyword-matrix.txt` | Raw output of `analyze.py`: company-weighted and posting-level keyword shares |
| `scripts/fetch.sh` | Pulls the raw postings from Greenhouse, Ashby and Lever public APIs and amazon.jobs |
| `scripts/load.py` | Normalizes the sources into one JSON list |
| `scripts/filter.py` | US + early-career + software-engineering filter, tiers A/B, de-duplication |
| `scripts/analyze.py` | Keyword prevalence (boilerplate stripped), pay ranges, CSV export |

Reproduce (results will drift as postings change):

```bash
research/scripts/fetch.sh /tmp/jobs && cd research/scripts && python3 -I load.py /tmp/jobs /tmp/all.json && python3 -I filter.py /tmp/all.json /tmp/early.json && python3 -I analyze.py /tmp/early.json /tmp/sample.csv
```
