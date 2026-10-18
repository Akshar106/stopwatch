"""Normalize scraped job postings into one list of dicts and pickle-free JSON."""
import glob, html, json, os, re, sys

RAW = sys.argv[1]
OUT = sys.argv[2]

def strip(s):
    s = html.unescape(s or "")
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()

STATES = set("AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC".split())
US_CITIES = ["san francisco", "new york", "nyc", "seattle", "austin", "chicago", "boston", "denver", "atlanta",
             "los angeles", "mountain view", "palo alto", "sunnyvale", "menlo park", "bellevue", "redmond",
             "washington", "pittsburgh", "raleigh", "portland", "san jose", "san mateo", "salt lake", "miami",
             "dallas", "houston", "philadelphia", "minneapolis", "detroit", "columbus", "san diego", "irvine",
             "santa clara", "cambridge, ma", "kirkland", "boulder", "nashville", "phoenix", "arlington", "herndon",
             "reston", "jersey city", "foster city", "redwood city", "emeryville", "oakland", "brooklyn", "ann arbor"]
NON_US = ["canada", "toronto", "vancouver", "london", "dublin", "india", "bengaluru", "bangalore", "hyderabad",
          "singapore", "sydney", "tokyo", "berlin", "amsterdam", "paris", "mexico", "brazil", "são paulo",
          "sao paulo", "poland", "warsaw", "tel aviv", "israel", "uk", "united kingdom", "ireland", "germany",
          "spain", "madrid", "barcelona", "australia", "japan", "korea", "seoul", "lisbon", "portugal", "zurich",
          "switzerland", "netherlands", "france", "philippines", "costa rica", "argentina", "colombia", "chile",
          "estonia", "romania", "serbia", "denmark", "sweden", "stockholm", "copenhagen", "pune", "chennai",
          "noida", "gurgaon", "manila", "montreal", "ontario", "edinburgh", "belfast", "krakow", "kraków"]

def is_us(loc):
    l = (loc or "").lower()
    if re.search(r"\b(united states|usa|u\.s\.|us)\b", l) or "us-" in l or "us -" in l:
        return True
    for c in US_CITIES:
        if c in l:
            return True
    for m in re.finditer(r",\s*([A-Z]{2})\b", loc or ""):
        if m.group(1) in STATES:
            return True
    return False

def non_us_only(loc):
    l = (loc or "").lower()
    return any(re.search(r"\b" + re.escape(n) + r"\b", l) for n in NON_US) and not is_us(loc)

recs = []
for f in glob.glob(os.path.join(RAW, "gh_*.json")):
    d = json.load(open(f))
    if "jobs" not in d:
        continue
    for j in d["jobs"]:
        offices = " | ".join(o.get("name", "") for o in (j.get("offices") or []))
        loc = (j.get("location") or {}).get("name", "")
        recs.append(dict(src="greenhouse", company=j.get("company_name") or os.path.basename(f)[3:-5],
                         title=j["title"].strip(), loc=loc + (" | " + offices if offices else ""),
                         url=j["absolute_url"], posted=(j.get("first_published") or j.get("updated_at") or "")[:10],
                         text=strip(j.get("content")), us=is_us(loc) or is_us(offices)))

for f in glob.glob(os.path.join(RAW, "ash_*.json")):
    d = json.load(open(f))
    for j in d.get("jobs", []):
        if not j.get("isListed", True):
            continue
        addr = ((j.get("address") or {}).get("postalAddress") or {})
        locs = [j.get("location", "")] + [s.get("location", "") for s in (j.get("secondaryLocations") or [])]
        countries = [addr.get("addressCountry", "")] + [((s.get("address") or {}).get("postalAddress") or {}).get("addressCountry", "") for s in (j.get("secondaryLocations") or [])]
        us = any(c in ("USA", "United States", "US") for c in countries) or any(is_us(l) for l in locs)
        recs.append(dict(src="ashby", company=os.path.basename(f)[4:-5].title(), title=j["title"].strip(),
                         loc=" | ".join(locs), url=j["jobUrl"], posted=(j.get("publishedAt") or "")[:10],
                         text=j.get("descriptionPlain") or strip(j.get("descriptionHtml")), us=us,
                         etype=j.get("employmentType")))

for f in glob.glob(os.path.join(RAW, "lev_*.json")):
    d = json.load(open(f))
    if not isinstance(d, list):
        continue
    import datetime
    for j in d:
        lists = " ".join(x.get("text", "") + " " + strip(x.get("content")) for x in j.get("lists", []))
        text = " ".join([j.get("descriptionPlain", ""), lists, j.get("additionalPlain", "")])
        loc = (j.get("categories") or {}).get("location", "")
        posted = datetime.datetime.utcfromtimestamp(int(j["createdAt"]) / 1000).strftime("%Y-%m-%d") if j.get("createdAt") else ""
        recs.append(dict(src="lever", company=os.path.basename(f)[4:-5].title(), title=j["text"].strip(), loc=loc,
                         url=j["hostedUrl"], posted=posted, text=re.sub(r"\s+", " ", text),
                         us=(j.get("country") == "US") or is_us(loc)))

seen = set()
for f in glob.glob(os.path.join(RAW, "amzn", "p_*.json")):
    d = json.load(open(f))
    for j in d.get("jobs", []):
        if j["id"] in seen:
            continue
        seen.add(j["id"])
        text = " ".join([strip(j.get("description")), "BASIC QUALIFICATIONS " + strip(j.get("basic_qualifications")),
                         "PREFERRED QUALIFICATIONS " + strip(j.get("preferred_qualifications"))])
        recs.append(dict(src="amazon.jobs", company="Amazon" if (j.get("company_name") or "").startswith("Amazon") else f"Amazon ({j.get('company_name')})",
                         title=j["title"].strip(), loc=j.get("normalized_location") or j.get("location", ""),
                         url="https://www.amazon.jobs" + j["job_path"], posted=j.get("posted_date", ""), text=text,
                         us=j.get("country_code") == "USA", basic=strip(j.get("basic_qualifications"))))

json.dump(recs, open(OUT, "w"))
print(len(recs), "records;", sum(r["us"] for r in recs), "US")
