#!/usr/bin/env python3
"""Weekly market facts from the DACH index → data/weekly/<YYYY>-W<ww>.json.

These facts are the ONLY source the AI article writer may use (write_article.py checks every number
in the article against this file). Week-over-week deltas come from the previous week's facts file.

Usage: python3 weekly_facts.py   (after fetch.py --index)
"""
import datetime as dt
import json
from collections import Counter, defaultdict

import build as B

TOP = 10


def pct(a, b):
    return round(100 * a / b, 1) if b else 0.0


def annual_eur(j):
    """Midpoint of a published EUR salary range, annualised (monthly ×12); hourly and odd values skipped."""
    if j.get("salaryCurrency") != "EUR" or not (j.get("salaryMin") or j.get("salaryMax")):
        return None
    lo, hi = j.get("salaryMin") or j.get("salaryMax"), j.get("salaryMax") or j.get("salaryMin")
    iv = (j.get("salaryInterval") or "").lower()
    mult = 12 if "month" in iv else 1 if "year" in iv else None
    v = (lo + hi) / 2 * mult if mult else None
    return v if v and 12000 <= v <= 300000 else None


def median(xs):
    xs = sorted(xs)
    return round(xs[len(xs) // 2], -2) if xs else None


def week_id(date):
    y, w, _ = dt.date.fromisoformat(date).isocalendar()
    return f"{y}-W{w:02d}"


def compute(jobs, date):
    total = len(jobs)
    week_ago = (dt.date.fromisoformat(date) - dt.timedelta(days=7)).isoformat()
    by_co = defaultdict(list)
    for j in jobs:
        by_co[j["company"]].append(j)
    name = {c: js[0]["companyName"] for c, js in by_co.items()}
    cats = Counter(j["cat"] for j in jobs)
    cities = Counter(c for j in jobs for c in j["cities"])
    countries = Counter(k for j in jobs for k in j["countries"])
    tech = [j for j in jobs if j["cat"] in B.TECH]
    salary = [j for j in jobs if j.get("salaryMin") or j.get("salaryMax")]
    posted_week = [j for j in jobs if (j["postedAt"] or "") >= week_ago]
    seen_week = [j for j in jobs if (j.get("firstSeen") or "") >= week_ago]

    def cat_stats(js):
        n = len(js)
        sal = [v for v in map(annual_eur, (j for j in js if not j["track"])) if v]  # without Ausbildung/Werkstudent pay
        return {"jobs": n, "medianAnnualSalaryEUR": median(sal) if len(sal) >= 20 else None, "salarySampleSize": len(sal), "remotePct": pct(sum(j["remote"] for j in js), n), "salaryPct": pct(sum(1 for j in js if j.get("salaryMin") or j.get("salaryMax")), n),
                "seniorPct": pct(sum(j["level"] == "senior" for j in js), n)}

    by_cat = defaultdict(list)
    for j in jobs:
        by_cat[j["cat"]].append(j)
    city_cat = {}
    for c, _ in cities.most_common(8):
        cc = Counter(j["cat"] for j in jobs if c in j["cities"])
        city_cat[c] = [{"category": B.CAT_LABEL[k], "jobs": v} for k, v in cc.most_common(3)]
    ai_jobs = [j for j in jobs if B.re.search(r"\b(KI|AI|ML|LLM|GenAI|machine learning|künstliche intelligenz)\b", j["title"])]

    return {
        "week": week_id(date), "dataDate": date, "source": "wer-stellt-ein.de / DACH Jobs API index (public career sites)",
        "notes": "medianAnnualSalaryEUR: median midpoint of published EUR ranges (monthly x12), excluding Ausbildung/Werkstudent/Praktikum; only where >= 20 postings publish one. Pay may include part-time roles. Index covers employers using supported ATS, not the whole market.",
        "totals": {"jobs": total, "employers": len(by_co), "techJobs": len(tech), "techPct": pct(len(tech), total),
                   "postedLast7Days": len(posted_week), "firstSeenLast7Days": len(seen_week) if len(seen_week) < total else None,
                   "remotePct": pct(sum(j["remote"] for j in jobs), total), "hybridPct": pct(sum(j["hybrid"] for j in jobs), total),
                   "salaryPct": pct(len(salary), total), "aiTitleJobs": len(ai_jobs),
                   "ausbildung": sum(j["track"] == "ausbildung" for j in jobs), "werkstudentPraktikum": sum(j["track"] == "werkstudent" for j in jobs)},
        "countries": {B.COUNTRY_NAME[k]: v for k, v in countries.most_common()},
        "categories": [{"category": B.CAT_LABEL[k], "slug": k, **cat_stats(by_cat[k])} for k, _ in cats.most_common()],
        "topCities": [{"city": c, "jobs": v} for c, v in cities.most_common(15)],
        "cityTopCategories": city_cat,
        "topEmployers": [{"employer": name[c], "jobs": len(js), "topCategory": B.CAT_LABEL[Counter(j["cat"] for j in js).most_common(1)[0][0]]}
                         for c, js in sorted(by_co.items(), key=lambda kv: -len(kv[1]))[:TOP]],
        "topTechEmployers": [{"employer": name[c], "techJobs": v} for c, v in Counter(j["company"] for j in tech).most_common(TOP)],
        "mostNewPostings": [{"employer": name[c], "postedLast7Days": v} for c, v in Counter(j["company"] for j in posted_week).most_common(TOP)],
        "seniority": {k: pct(v, total) for k, v in Counter(j["level"] for j in jobs).most_common()},
        "ats": {B.ATS_LABEL.get(k, k): v for k, v in Counter(j["ats"] for j in jobs if j["ats"]).most_common(8)},
    }


def add_deltas(cur, prev):
    """Week-over-week changes, only when last week's facts exist and cover a comparable index."""
    if not prev or prev["totals"]["jobs"] < 0.5 * cur["totals"]["jobs"]:
        cur["previousWeek"] = None
        return cur
    pt, ct = prev["totals"], cur["totals"]
    pc = {c["slug"]: c["jobs"] for c in prev["categories"]}
    pcity = {c["city"]: c["jobs"] for c in prev["topCities"]}
    pemp = {e["employer"]: e["jobs"] for e in prev["topEmployers"]}
    cur["previousWeek"] = {
        "week": prev["week"],
        "jobsChange": ct["jobs"] - pt["jobs"], "jobsChangePct": pct(ct["jobs"] - pt["jobs"], pt["jobs"]),
        "employersChange": ct["employers"] - pt["employers"],
        "salaryPctChange": round(ct["salaryPct"] - pt["salaryPct"], 1), "remotePctChange": round(ct["remotePct"] - pt["remotePct"], 1),
        "categoryChanges": sorted([{"category": c["category"], "change": c["jobs"] - pc[c["slug"]], "changePct": pct(c["jobs"] - pc[c["slug"]], pc[c["slug"]])}
                                   for c in cur["categories"] if pc.get(c["slug"])], key=lambda x: -abs(x["change"]))[:8],
        "cityChanges": sorted([{"city": c["city"], "change": c["jobs"] - pcity[c["city"]]} for c in cur["topCities"] if c["city"] in pcity],
                              key=lambda x: -abs(x["change"]))[:6],
        "employerChanges": [{"employer": e["employer"], "change": e["jobs"] - pemp[e["employer"]]} for e in cur["topEmployers"] if e["employer"] in pemp],
    }
    return cur


def main():
    jobs, date = B.load_index_jobs()
    cur = compute(jobs, date)
    out = B.DATA / "weekly"
    out.mkdir(parents=True, exist_ok=True)
    older = sorted(p for p in out.glob("*.json") if p.stem < cur["week"])
    prev = json.loads(older[-1].read_text()) if older else None
    add_deltas(cur, prev)
    (out / f"{cur['week']}.json").write_text(json.dumps(cur, ensure_ascii=False, indent=1))
    print(f"facts {cur['week']}: {cur['totals']['jobs']} jobs, previous week: {prev['week'] if prev else 'none'}")


if __name__ == "__main__":
    main()
