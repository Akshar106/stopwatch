"""Select US early-career software engineering postings from the normalized set."""
import collections, hashlib, json, re, sys

recs = json.load(open(sys.argv[1]))
OUT = sys.argv[2]

SWE = re.compile(r"\b(software|backend|back-end|back end|full[- ]?stack|frontend|front-end|product engineer|"
                 r"platform engineer|infrastructure engineer|sde|developer|engineer,? (?:new grad|university|early career))\b", re.I)
NOT_SWE = re.compile(r"\b(sales|solutions? engineer|support engineer|customer|recruit|account|security analyst|"
                     r"data scientist|analyst|designer|manager|director|head of|technical writer|field engineer|"
                     r"hardware|mechanical|electrical|firmware|silicon|asic|"
                     r"embedded|sourcer|partner|marketing|legal|counsel|program manager|researcher|research scientist|"
                     r"economist|test engineer|quality assurance|qa engineer|advocate|developer relations|deployment strategist|machine learning|privacy)\b", re.I)
SENIOR = re.compile(r"\b(senior|sr\.?|staff|principal|lead|distinguished|architect|ii|iii|iv|2|3|4|5|"
                    r"tech lead|tlm|l5|l6|e5|e6|manager)\b", re.I)
INTERN = re.compile(r"\b(intern|internship|co-?op|apprentice(ship)?)\b", re.I)
EARLY_TITLE = re.compile(r"\b(new grad(uate)?|university( grad(uate)?)?|early[- ]career|entry[- ]level|junior|"
                         r"associate|graduate|campus|20(26|27)|engineer,? i\b|engineer i$|engineer 1\b|sde i\b|"
                         r"dev(elopment)? engineer i\b|emerging talent|residency|rotational)", re.I)
YEARS = re.compile(r"(\d{1,2})\s*(?:\+|or more|plus)?\s*(?:-|–|to)?\s*(?:\d{1,2})?\s*\+?\s*years?(?:'|’)?\s*(?:of\s+)?"
                   r"(?:[a-z/,\-]+\s+){0,6}?(?:experience|exp\b)", re.I)

QUAL = re.compile(r"basic qualifications|minimum (requirements|qualifications)|what you.ll need|what you need|"
                  r"what you bring|you have:|you are:|who you are|requirements|qualifications|we.re looking for|"
                  r"your background|about you|you might be a fit|what we look for", re.I)

def min_years(text):
    """Headline years requirement: first 'N years ... experience' after the qualifications header."""
    m = QUAL.search(text)
    tail = text[m.start():] if m else text
    for y in YEARS.finditer(tail):
        if int(y.group(1)) <= 20:
            return int(y.group(1))
    return None

out = []
for r in recs:
    if not r["us"]:
        continue
    t = r["title"]
    if r.get("etype") == "Intern" or INTERN.search(t):
        continue
    if not SWE.search(t) or NOT_SWE.search(t):
        continue
    early_title = bool(EARLY_TITLE.search(t))
    if re.search(r"\b(senior|sr\.?|staff|principal|lead|distinguished|phd)\b", t, re.I):
        continue
    # Microsoft-style "Software Engineer II" is not in sample; treat II+ as non-entry.
    if SENIOR.search(t) and not early_title:
        continue
    yrs = min_years(r["text"] if r["src"] != "amazon.jobs" else r.get("basic", "") or r["text"])
    if early_title:
        tier = "A"
    elif yrs is not None and yrs <= 2:
        tier = "B"
    elif r["src"] == "amazon.jobs" and yrs is None and re.fullmatch(r"(software (development|dev) engineer|sde)\s*(i\b.*|,.*|-.*)?", t, re.I):
        tier = "B"  # Amazon SDE reqs with no years requirement are entry level (SDE I)
    else:
        continue
    r = dict(r, tier=tier, min_years=yrs)
    out.append(r)

# De-duplicate near-identical requisitions (same company, title, opening text)
dedup, seen = [], set()
for r in out:
    key = (r["company"].split(" (")[0], re.sub(r"\W+", " ", r["title"].lower()).strip(),
           hashlib.md5(r["text"][:1500].encode()).hexdigest())
    if key in seen:
        continue
    seen.add(key)
    dedup.append(r)

json.dump(dedup, open(OUT, "w"))
c = collections.Counter((r["company"].split(" (")[0], r["tier"]) for r in dedup)
print(len(out), "matched;", len(dedup), "after dedup")
for (co, tier), n in sorted(c.items()):
    print(f"  {co:12s} {tier} {n}")
print("\nTier A titles:")
for r in dedup:
    if r["tier"] == "A":
        print(f"  [{r['company']}] {r['title']} | {r['loc'][:50]} | yrs={r['min_years']} | {r['posted']}")
