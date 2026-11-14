#!/usr/bin/env python3
"""Static site generator for the DACH Tech Hiring Index ("Wer stellt ein?").

Input:  data/jobs-latest.json  (items from the Apify Actor goldfoot/ats-jobs-feed)
        data/snapshots/*.json.gz (compact weekly snapshots, for trends)
        site.json (domain, contact, flags)
Output: dist/  (plain HTML + CSS + sitemap, deployable anywhere)

No third-party dependencies. Usage: python3 build.py [--snapshot]
"""
import datetime as dt
import gzip
import html
import json
import re
import shutil
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).parent
DATA = ROOT / "data"
DIST = ROOT / "dist"
CFG = json.loads((ROOT / "site.json").read_text())
BASE = CFG["baseUrl"].rstrip("/")

# ---------------------------------------------------------------- classification
CITIES = {  # canonical name -> (country code, regex)
    "Berlin": ("DE", r"berlin"), "München": ("DE", r"m(ü|ue|u)nchen|munich"), "Hamburg": ("DE", r"hamburg"),
    "Frankfurt am Main": ("DE", r"frankfurt"), "Köln": ("DE", r"k(ö|oe)ln|cologne"), "Stuttgart": ("DE", r"stuttgart"),
    "Düsseldorf": ("DE", r"d(ü|ue|u)sseldorf"), "Leipzig": ("DE", r"leipzig"), "Dresden": ("DE", r"dresden"),
    "Hannover": ("DE", r"hann?over"), "Nürnberg": ("DE", r"n(ü|ue|u)rnberg|nuremberg"), "Karlsruhe": ("DE", r"karlsruhe"),
    "Bonn": ("DE", r"\bbonn\b"), "Mannheim": ("DE", r"mannheim"), "Heidelberg": ("DE", r"heidelberg"), "Essen": ("DE", r"\bessen\b"),
    "Dortmund": ("DE", r"dortmund"), "Bremen": ("DE", r"bremen"), "Münster": ("DE", r"m(ü|ue)nster\b"), "Freiburg": ("DE", r"freiburg"),
    "Aachen": ("DE", r"aachen"), "Potsdam": ("DE", r"potsdam"), "Regensburg": ("DE", r"regensburg"), "Ingolstadt": ("DE", r"ingolstadt"),
    "Wolfsburg": ("DE", r"wolfsburg"), "Erlangen": ("DE", r"erlangen"), "Darmstadt": ("DE", r"darmstadt"), "Walldorf": ("DE", r"walldorf"),
    "Wien": ("AT", r"\bwien\b|vienna"), "Graz": ("AT", r"\bgraz\b"), "Linz": ("AT", r"\blinz\b"), "Salzburg": ("AT", r"salzburg"),
    "Innsbruck": ("AT", r"innsbruck"), "Zürich": ("CH", r"z(ü|ue|u)rich"), "Basel": ("CH", r"\bbasel\b"), "Bern": ("CH", r"\bbern\b"),
    "Genf": ("CH", r"geneva|gen[eè]ve|\bgenf\b"), "Lausanne": ("CH", r"lausanne"), "Luzern": ("CH", r"lu[cz]ern"), "Zug": ("CH", r"\bzug\b"),
    "St. Gallen": ("CH", r"st\.? ?gallen"),
}
CITY_RE = [(c, cc, re.compile(rx, re.I)) for c, (cc, rx) in CITIES.items()]
COUNTRY_RE = {"DE": re.compile(r"(?i:germany|deutschland)|\bDEU?\b"), "AT": re.compile(r"(?i:austria|österreich)|\bAUT\b|\bAT\b"),
              "CH": re.compile(r"(?i:switzerland|schweiz|suisse)|\bCHE?\b")}
COUNTRY_NAME = {"DE": "Deutschland", "AT": "Österreich", "CH": "Schweiz"}
REMOTE_ONLY = re.compile(r"\b(remote|anywhere|worldwide|dach|europe|europa|emea|eu|cet|home ?office|mobile arbeit|hybrid|full[- ]?time|\(?[a-z]{2}\)?)\b|[|,;/()\-–\s]+", re.I)

CATEGORIES = [  # (slug, label, tech?, regex) — first match wins
    ("sales", "Sales & Business Development", False, r"\bsales\b|vertrieb|account (executive|manager)|business development|\bsdr\b|\bbdr\b|key account"),
    ("people", "HR & Recruiting", False, r"recruit|talent acquisition|\bhr\b|people (partner|operations)|personalreferent"),
    ("finance-legal", "Finanzen & Recht", False, r"einkauf|procurement|buyer|purchas|financ|finanz|accounting|buchhalt|controll|\btax\b|steuer|legal|counsel|jurist"),
    ("devops-sre-platform", "DevOps, SRE & Platform", True, r"devops|\bsre\b|site reliability|platform engineer|cloud engineer|infrastructure|kubernetes|systems? engineer"),
    ("security", "IT-Security", True, r"secur|sicherheit|pentest|\bsoc\b|ciso|iam\b"),
    ("data-ai", "Data, KI & Machine Learning", True, r"\bdata\b|daten|machine learning|\bml\b|\bai\b|\bki\b|analytics engineer|scientist|\bllm|deep learning|computer vision|nlp|bi developer|business intelligence"),
    ("mobile", "Mobile (iOS/Android)", True, r"\bios\b|android|mobile|flutter|react native"),
    ("frontend", "Frontend", True, r"front.?end|\bui engineer|react\b|angular|vue"),
    ("backend-fullstack", "Backend & Fullstack", True, r"back.?end|full.?stack|forward deployed|solutions? engineer|software (engineer|developer|entwickler)|softwareentwickl|developer|entwickler|\bengineer\b.*(java|python|go|golang|php|ruby|node|\.net|c#|kotlin|scala|rust|c\+\+)|programmier"),
    ("qa-testing", "QA & Testing", True, r"\bqa\b|quality assurance|\btest|tester"),
    ("engineering-management", "Engineering Management", True, r"engineering manager|head of engineering|\bcto\b|vp engineering|tech lead|team lead.*(engineer|develop)|director.*engineering"),
    ("product", "Produktmanagement", True, r"product (manager|owner|lead|director)|produktmanag|product ops|\bpm\b"),
    ("design", "UX/UI Design", True, r"design|\bux\b|user research"),
    ("it-support", "IT & Support", True, r"\bit[- ](support|admin|specialist|manager|engineer)|helpdesk|service desk|systemadmin|workplace"),
    ("hardware-embedded", "Hardware & Embedded", True, r"embedded|firmware|hardware|electr|elektr|fpga|robot|avionic|mechatron"),
    ("sales", "Sales & Business Development", False, r"sales|vertrieb|account (executive|manager)|business development|\bsdr\b|\bbdr\b|partnership"),
    ("marketing", "Marketing & Growth", False, r"marketing|growth|seo|content|brand|communications|kommunikation|\bpr\b"),
    ("customer", "Customer Success & Support", False, r"customer|kunden|support|onboarding|success"),
    ("finance-legal", "Finanzen & Recht", False, r"financ|finanz|accounting|buchhalt|controll|tax|steuer|legal|recht|compliance|counsel|audit"),
    ("people", "HR & Recruiting", False, r"recruit|talent|\bhr\b|people|personal"),
    ("engineering-other", "Ingenieurwesen & sonstige Technik", True, r"engineer|ingenieur|konstrukt|\bcad\b|entwicklung|technik|techniker|scientist|forsch|research|r&d"),
    ("operations", "Operations & Sonstiges", False, r"."),
]
CAT_RE = [(s, l, t, re.compile(rx, re.I)) for s, l, t, rx in CATEGORIES]
CAT_UNIQUE = list({s: (s, l, t, rx) for s, l, t, rx in reversed(CATEGORIES)}.values())[::-1]
CAT_LABEL = {s: l for s, l, _, _ in CATEGORIES}
TECH = {s for s, _, t, _ in CATEGORIES if t}
ATS_LABEL = {"greenhouse": "Greenhouse", "lever": "Lever", "ashby": "Ashby", "workable": "Workable", "smartrecruiters": "SmartRecruiters",
             "recruitee": "Recruitee", "personio": "Personio", "rippling": "Rippling", "breezy": "Breezy HR", "teamtailor": "Teamtailor"}
SENIOR_RE = re.compile(r"senior|\bsr\.?\b|lead|staff|principal|head|director|\bvp\b|chief", re.I)
JUNIOR_RE = re.compile(r"junior|\bjr\.?\b|werkstudent|working student|intern|praktik|trainee|graduate|azubi|ausbildung|einsteiger", re.I)


def slugify(s):
    s = unicodedata.normalize("NFKD", s.replace("ß", "ss").replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
                              .replace("Ä", "Ae").replace("Ö", "Oe").replace("Ü", "Ue"))
    s = re.sub(r"[^\w\s-]", "", s.encode("ascii", "ignore").decode()).strip().lower()
    return re.sub(r"[\s_-]+", "-", s)[:60] or "x"


def classify(job):
    loc = " | ".join(filter(None, [job.get("location"), *(job.get("locations") or []), job.get("city"), job.get("region"),
                                    job.get("country"), job.get("countryCode")]))
    cities, countries = [], set()
    for c, cc, rx in CITY_RE:
        if rx.search(loc):
            cities.append(c)
            countries.add(cc)
    for cc, rx in COUNTRY_RE.items():
        if rx.search(loc):
            countries.add(cc)
    remote = job.get("workplaceType") == "remote"
    # Remote jobs without any DACH place count only if the location names no other place at all ("Remote - Europe", "Remote (DACH)").
    if not countries and not ((remote or job.get("isRemote")) and loc and not REMOTE_ONLY.sub("", loc).strip()):
        return None  # not a DACH job
    title = job.get("title") or ""
    cat = next(s for s, _, _, rx in CAT_RE if rx.search(title))
    level = "senior" if SENIOR_RE.search(title) else "junior" if JUNIOR_RE.search(title) else "mid"
    return {"cities": cities, "countries": sorted(countries), "remote": remote, "hybrid": job.get("workplaceType") == "hybrid",
            "cat": cat, "level": level}


def company_key(job):
    name = (job.get("companyName") or job.get("companySlug") or job.get("input") or "?").strip()
    name = re.sub(r"\s+(GmbH & Co\.? KG|SE & Co\.? KG|GmbH|AG|SE|KG|Inc\.?|Ltd\.?|LLC|N\.V\.|B\.V\.)$", "", name)
    name = re.sub(r"\s+(Operations|Group|Holding)$", lambda m: m.group(0) if m.group(1) == "Group" else "", name)
    return slugify(name), name


# ---------------------------------------------------------------- data
def load_jobs():
    raw = json.loads((DATA / "jobs-latest.json").read_text())
    jobs, seen = [], set()
    for j in raw:
        uid = j.get("uid") or j.get("url")
        if not uid or uid in seen or not j.get("title"):
            continue
        seen.add(uid)
        c = classify(j)
        if not c:
            continue
        slug, name = company_key(j)
        jobs.append({"uid": uid, "company": slug, "companyName": name, "title": j["title"].strip(), "url": j.get("url"),
                     "ats": j.get("ats"), "location": j.get("location") or ", ".join(j.get("locations") or []),
                     "postedAt": (j.get("postedAt") or "")[:10] or None, "department": j.get("department"),
                     "salaryText": j.get("salaryText"), "salaryMin": j.get("salaryMin"), "salaryMax": j.get("salaryMax"),
                     "salaryCurrency": j.get("salaryCurrency"), "salaryInterval": j.get("salaryInterval"),
                     "domain": j.get("input"), **c})
    return jobs


def load_snapshots():
    snaps = []
    for p in sorted((DATA / "snapshots").glob("*.json.gz")):
        snaps.append((p.name[:10], json.loads(gzip.decompress(p.read_bytes()))))
    return snaps


def write_snapshot(jobs, day):
    (DATA / "snapshots").mkdir(parents=True, exist_ok=True)
    compact = [{k: j[k] for k in ("uid", "company", "cat", "cities", "countries", "remote", "postedAt")} for j in jobs]
    (DATA / "snapshots" / f"{day}.json.gz").write_bytes(gzip.compress(json.dumps(compact, separators=(",", ":")).encode()))


# ---------------------------------------------------------------- html helpers
e = html.escape
TODAY = dt.date.today()


def fmt_date(d):
    if not d:
        return "–"
    y, m, dd = d.split("-")
    return f"{dd}.{m}.{y}"


def n(x):
    return f"{x:,}".replace(",", ".")


def delta(cur, prev):
    if prev is None:
        return ""
    d = cur - prev
    if d == 0:
        return '<span class="d0">±0</span>'
    return f'<span class="{"up" if d > 0 else "down"}">{"+" if d > 0 else "−"}{n(abs(d))}</span>'


def page(path, title, desc, body, crumbs=(), jsonld=None):
    url = f"{BASE}{path}"
    crumb_html = ""
    if crumbs:
        parts = ['<a href="/">Start</a>'] + [f'<a href="{h}">{e(t)}</a>' if h else f"<span>{e(t)}</span>" for t, h in crumbs]
        crumb_html = f'<nav class="crumbs">{" › ".join(parts)}</nav>'
        bl = {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "name": t, "item": f"{BASE}{h or path}"} for i, (t, h) in enumerate([("Start", "/"), *crumbs])]}
        jsonld = [*(jsonld or []), bl]
    ld = "".join(f'<script type="application/ld+json">{json.dumps(x, ensure_ascii=False)}</script>' for x in (jsonld or []))
    robots = '<meta name="robots" content="noindex">' if CFG.get("noindex") else ""
    doc = f"""<!DOCTYPE html>
<html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title><meta name="description" content="{e(desc)}"><link rel="canonical" href="{url}">{robots}
<meta property="og:title" content="{e(title)}"><meta property="og:description" content="{e(desc)}"><meta property="og:url" content="{url}"><meta property="og:type" content="website">
<link rel="stylesheet" href="/style.css"><link rel="icon" href="/favicon.svg" type="image/svg+xml">{ld}</head>
<body><header class="top"><div class="wrap"><a class="brand" href="/">{e(CFG["brand"])}</a>
<nav><a href="/jobs/">Bereiche</a><a href="/staedte/">Städte</a><a href="/unternehmen/">Unternehmen</a><a href="/ats/">ATS</a><a href="/hiring-signale/" class="cta-link">Hiring-Signale</a></nav></div></header>
<main class="wrap">{crumb_html}{body}</main>
<footer><div class="wrap"><p>Daten: öffentliche Karriereseiten von {n(STATS["companies"])} Unternehmen, Stand {fmt_date(STATS["date"])}. Wöchentlich aktualisiert. <a href="/methodik/">Methodik</a> · <a href="/impressum/">Impressum</a> · <a href="/datenschutz/">Datenschutz</a></p>
<p>Alle Stellen verlinken direkt auf die Karriereseite des Unternehmens. Keine Gewähr für Vollständigkeit.</p></div></footer></body></html>"""
    out = DIST / path.strip("/") / "index.html" if path.endswith("/") else DIST / path
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(doc)
    if not CFG.get("noindex") and path not in ("/impressum/", "/datenschutz/"):
        SITEMAP.append(url)


def bar_rows(counter, total, label_fn, link_fn=None, limit=12):
    rows = []
    for k, v in counter.most_common(limit):
        lbl = e(label_fn(k))
        if link_fn and link_fn(k):
            lbl = f'<a href="{link_fn(k)}">{lbl}</a>'
        pct = 100 * v / max(total, 1)
        rows.append(f'<div class="bar"><span class="bl">{lbl}</span><span class="bt"><i style="width:{pct:.1f}%"></i></span><span class="bv">{n(v)}</span></div>')
    return '<div class="bars">' + "".join(rows) + "</div>"


def job_table(jobs, show_company=True, limit=None):
    jobs = sorted(jobs, key=lambda j: j["postedAt"] or "", reverse=True)
    rows = []
    for j in jobs[:limit] if limit else jobs:
        comp = f'<td><a href="/unternehmen/{j["company"]}/">{e(j["companyName"])}</a></td>' if show_company else ""
        tags = []
        if j["remote"]:
            tags.append('<b class="t remote">Remote</b>')
        elif j["hybrid"]:
            tags.append('<b class="t hybrid">Hybrid</b>')
        if j["salaryText"]:
            tags.append(f'<b class="t sal">{e(j["salaryText"])}</b>')
        rows.append(f'<tr>{comp}<td><a href="{e(j["url"] or "#")}" rel="nofollow noopener" target="_blank">{e(j["title"])}</a> {"".join(tags)}</td>'
                    f'<td>{e(", ".join(j["cities"]) or (j["location"] or "")[:60])}</td><td class="nw">{fmt_date(j["postedAt"])}</td></tr>')
    head = ("<th>Unternehmen</th>" if show_company else "") + "<th>Stelle</th><th>Ort</th><th>Veröffentlicht</th>"
    more = f'<p class="muted">… und {n(len(jobs) - limit)} weitere.</p>' if limit and len(jobs) > limit else ""
    return f'<div class="tw"><table class="jobs"><thead><tr>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>{more}'


def stat_tiles(items):
    return '<div class="tiles">' + "".join(f'<div class="tile"><div class="tv">{v}</div><div class="tl">{e(l)}</div></div>' for v, l in items) + "</div>"


def cta(context=""):
    return f"""<aside class="cta"><h3>Hiring-Signale für Ihren Vertrieb</h3>
<p>Wer gerade {e(context) or "DevOps-, Daten- oder Security-Rollen"} ausschreibt, hat Budget und Bedarf. Wir liefern Ihnen jede Woche eine Liste der Unternehmen aus Ihrer Zielgruppe, die neue passende Stellen veröffentlicht haben, mit Link zur Ausschreibung.</p>
<p><a class="btn" href="/hiring-signale/">Beispiel-Liste ansehen</a> <a class="btn ghost" href="{CFG["actorUrl"]}" rel="noopener">Selbst abfragen (API)</a></p></aside>"""


# ---------------------------------------------------------------- pages
SITEMAP = []
STATS = {}


def salary_summary(jobs):
    eur = [j for j in jobs if j["salaryMin"] and j["salaryCurrency"] in ("EUR", "CHF") and (j["salaryInterval"] or "").upper().find("YEAR") >= 0]
    if len(eur) < 3:
        return None
    lo = sorted(j["salaryMin"] for j in eur)
    hi = sorted(j["salaryMax"] or j["salaryMin"] for j in eur)
    med = lambda a: a[len(a) // 2]  # noqa: E731
    return len(eur), med(lo), med(hi)


def build(jobs, snaps):
    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir()
    shutil.copy(ROOT / "static" / "style.css", DIST / "style.css")
    shutil.copy(ROOT / "static" / "favicon.svg", DIST / "favicon.svg")
    prev = snaps[-2][1] if len(snaps) >= 2 else None
    prev_by = lambda keyfn: Counter(k for j in prev for k in keyfn(j)) if prev else None  # noqa: E731

    tech = [j for j in jobs if j["cat"] in TECH]
    by_company = defaultdict(list)
    for j in jobs:
        by_company[j["company"]].append(j)
    STATS.update(date=snaps[-1][0] if snaps else TODAY.isoformat(), companies=len(by_company), jobs=len(jobs), tech=len(tech))
    names = {c: js[0]["companyName"] for c, js in by_company.items()}
    tech_by_company = Counter(j["company"] for j in tech)
    prev_tech_company = prev_by(lambda j: [j["company"]] if j["cat"] in TECH else []) if prev else None
    prev_tech_total = sum(1 for j in prev if j["cat"] in TECH) if prev else None
    city_tech = Counter(c for j in tech for c in j["cities"])
    cat_count = Counter(j["cat"] for j in jobs)
    ats_companies = defaultdict(set)
    for j in jobs:
        if j["ats"]:
            ats_companies[j["ats"]].add(j["company"])
    week_ago = (TODAY - dt.timedelta(days=7)).isoformat()
    new_week = [j for j in tech if (j["postedAt"] or "") >= week_ago]
    city_slug = {c: slugify(c) for c in CITIES}

    # ---- home
    top_rows = "".join(
        f'<tr><td>{i + 1}</td><td><a href="/unternehmen/{c}/">{e(names[c])}</a></td><td class="r">{n(v)}</td>'
        f'<td class="r">{delta(v, prev_tech_company.get(c, 0)) if prev_tech_company is not None else ""}</td></tr>'
        for i, (c, v) in enumerate(tech_by_company.most_common(25)))
    remote_share = 100 * sum(j["remote"] for j in tech) / max(len(tech), 1)
    body = f"""<section class="hero"><h1>Wer stellt ein? Der DACH Tech Hiring Index</h1>
<p class="lead">Jede Woche zählen wir die offenen Tech-Stellen von {n(len(by_company))} Unternehmen in Deutschland, Österreich und der Schweiz, direkt aus ihren Karriereseiten. Ohne Jobbörsen-Dubletten, ohne Personalvermittler.</p>
{stat_tiles([(n(len(tech)) + " " + delta(len(tech), prev_tech_total), "offene Tech-Stellen"), (n(len(new_week)), "neu in den letzten 7 Tagen"), (n(sum(1 for v in tech_by_company.values() if v)), "Unternehmen mit Tech-Stellen"), (f"{remote_share:.0f} %", "Remote-Anteil")])}
<p class="muted">Stand: {fmt_date(STATS["date"])}</p></section>
<div class="grid2"><section><h2>Top 25: Wer sucht die meisten Tech-Leute?</h2>
<table class="rank"><thead><tr><th>#</th><th>Unternehmen</th><th class="r">Tech-Stellen</th><th class="r">Δ Woche</th></tr></thead><tbody>{top_rows}</tbody></table>
<p><a href="/unternehmen/">Alle Unternehmen →</a></p></section>
<section><h2>Gefragteste Bereiche</h2>{bar_rows(Counter(j["cat"] for j in tech), len(tech), CAT_LABEL.get, lambda k: f"/jobs/{k}/")}
<h2>Tech-Stellen nach Stadt</h2>{bar_rows(city_tech, len(tech), str, lambda k: f"/staedte/{city_slug[k]}/", 10)}</section></div>
<section><h2>Neu diese Woche</h2>{job_table(new_week, limit=30) if new_week else '<p class="muted">Noch keine Daten.</p>'}</section>
{cta()}"""
    page("/", f"Wer stellt ein? DACH Tech Hiring Index ({fmt_date(STATS['date'])})",
         f"{n(len(tech))} offene Tech-Stellen bei {n(len(by_company))} Unternehmen in Deutschland, Österreich und der Schweiz. Wöchentlich aktualisiert, direkt aus den Karriereseiten.",
         body, jsonld=[{"@context": "https://schema.org", "@type": "Dataset", "name": "DACH Tech Hiring Index",
                        "description": "Wöchentliche Zählung offener Tech-Stellen von DACH-Unternehmen aus öffentlichen Karriereseiten.",
                        "url": BASE + "/", "dateModified": STATS["date"], "creator": {"@type": "Organization", "name": CFG["brand"]}}])

    # ---- companies
    rows = []
    for c, js in sorted(by_company.items(), key=lambda kv: -len(kv[1])):
        t = sum(1 for j in js if j["cat"] in TECH)
        rows.append(f'<tr><td><a href="/unternehmen/{c}/">{e(names[c])}</a></td><td class="r">{n(len(js))}</td><td class="r">{n(t)}</td><td>{e(ATS_LABEL.get(js[0]["ats"], js[0]["ats"] or ""))}</td></tr>')
        company_page(c, js, prev, city_slug)
    page("/unternehmen/", "Welche Unternehmen stellen gerade ein? Alle Firmen im Index",
         f"{n(len(by_company))} Unternehmen in DACH mit offenen Stellen, sortiert nach Anzahl. Wöchentlich aktualisiert.",
         f'<h1>Unternehmen, die gerade einstellen</h1><p class="lead">{n(len(by_company))} Unternehmen mit offenen Stellen in DACH, Stand {fmt_date(STATS["date"])}.</p>'
         f'<input class="filter" placeholder="Unternehmen filtern …" oninput="for(const r of document.querySelectorAll(\'tbody tr\'))r.hidden=!r.textContent.toLowerCase().includes(this.value.toLowerCase())">'
         f'<div class="tw"><table class="rank"><thead><tr><th>Unternehmen</th><th class="r">Stellen DACH</th><th class="r">davon Tech</th><th>Bewerbermanagement</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>',
         crumbs=[("Unternehmen", None)])

    # ---- categories (+ category x city)
    cat_links = []
    for slug, label, is_tech, _ in CAT_UNIQUE:
        js = [j for j in jobs if j["cat"] == slug]
        if not js:
            continue
        cat_links.append(f'<li><a href="/jobs/{slug}/">{e(label)}</a> <span class="muted">{n(len(js))}</span></li>')
        ccity = Counter(c for j in js for c in j["cities"])
        sub = []
        for city, cnt in ccity.most_common():
            if cnt < 3:
                continue
            sub.append(f'<a class="chip" href="/jobs/{slug}/{city_slug[city]}/">{e(city)} ({cnt})</a>')
            cj = [j for j in js if city in j["cities"]]
            ccomp = Counter(j["company"] for j in cj)
            page(f"/jobs/{slug}/{city_slug[city]}/", f"{label} Jobs in {city}: {n(cnt)} offene Stellen ({fmt_date(STATS['date'])})",
                 f"{n(cnt)} offene Stellen im Bereich {label} in {city} bei {n(len(ccomp))} Unternehmen, direkt von den Karriereseiten. Wöchentlich aktualisiert.",
                 f'<h1>{e(label)} in {e(city)}</h1><p class="lead">{n(cnt)} offene Stellen bei {n(len(ccomp))} Unternehmen, Stand {fmt_date(STATS["date"])}. '
                 f'Am meisten sucht {e(names[ccomp.most_common(1)[0][0]])}.</p>'
                 f'<h2>Unternehmen</h2>{bar_rows(ccomp, cnt, names.get, lambda k: f"/unternehmen/{k}/", 15)}<h2>Alle Stellen</h2>{job_table(cj)}{cta(label + "-Rollen in " + city)}',
                 crumbs=[("Bereiche", "/jobs/"), (label, f"/jobs/{slug}/"), (city, None)])
        comp = Counter(j["company"] for j in js)
        sal = salary_summary(js)
        sal_html = f'<p>Gehaltsangaben: {n(sal[0])} Stellen nennen ein Gehalt, Median-Spanne <b>{n(sal[1])} – {n(sal[2])}</b> pro Jahr.</p>' if sal else ""
        lvl = Counter(j["level"] for j in js)
        page(f"/jobs/{slug}/", f"{label} Jobs in DACH: {n(len(js))} offene Stellen ({fmt_date(STATS['date'])})",
             f"Wer stellt im Bereich {label} ein? {n(len(js))} offene Stellen bei {n(len(comp))} Unternehmen in Deutschland, Österreich und der Schweiz.",
             f'<h1>{e(label)}: wer stellt ein?</h1><p class="lead">{n(len(js))} offene Stellen bei {n(len(comp))} Unternehmen in DACH '
             f'{delta(len(js), sum(1 for j in prev if j["cat"] == slug) if prev else None)}. '
             f'Senior/Lead: {100 * lvl["senior"] / len(js):.0f} %, Junior/Einstieg: {100 * lvl["junior"] / len(js):.0f} %, Remote: {100 * sum(j["remote"] for j in js) / len(js):.0f} %.</p>{sal_html}'
             f'<div class="chips">{"".join(sub)}</div><div class="grid2"><section><h2>Top-Unternehmen</h2>{bar_rows(comp, len(js), names.get, lambda k: f"/unternehmen/{k}/", 15)}</section>'
             f'<section><h2>Städte</h2>{bar_rows(ccity, len(js), str, lambda k: f"/staedte/{city_slug[k]}/", 12)}</section></div>'
             f'<h2>Neueste Stellen</h2>{job_table(js, limit=100)}{cta(label + "-Rollen")}',
             crumbs=[("Bereiche", "/jobs/"), (label, None)])
    page("/jobs/", "Tech-Jobs in DACH nach Bereich", "Offene Stellen nach Bereich: DevOps, Data & KI, Security, Backend, Frontend, Produkt, Design und mehr.",
         f'<h1>Bereiche</h1><ul class="cols">{"".join(cat_links)}</ul>', crumbs=[("Bereiche", None)])

    # ---- cities
    city_links = []
    for city, (cc, _) in CITIES.items():
        js = [j for j in jobs if city in j["cities"]]
        if len(js) < 3:
            continue
        t = [j for j in js if j["cat"] in TECH]
        comp = Counter(j["company"] for j in t)
        city_links.append(f'<li><a href="/staedte/{city_slug[city]}/">{e(city)}</a> <span class="muted">{n(len(t))} Tech / {n(len(js))} gesamt</span></li>')
        page(f"/staedte/{city_slug[city]}/", f"Wer stellt in {city} ein? {n(len(t))} Tech-Stellen ({fmt_date(STATS['date'])})",
             f"{n(len(js))} offene Stellen in {city}, davon {n(len(t))} Tech-Stellen, bei {n(len(set(j['company'] for j in js)))} Unternehmen. Wöchentlich aktualisiert.",
             f'<h1>Wer stellt in {e(city)} ein?</h1><p class="lead">{n(len(js))} offene Stellen bei {n(len(set(j["company"] for j in js)))} Unternehmen, davon {n(len(t))} im Tech-Bereich ({COUNTRY_NAME[cc]}).</p>'
             f'<div class="grid2"><section><h2>Unternehmen mit den meisten Tech-Stellen</h2>{bar_rows(comp, len(t), names.get, lambda k: f"/unternehmen/{k}/", 15)}</section>'
             f'<section><h2>Bereiche</h2>{bar_rows(Counter(j["cat"] for j in js), len(js), CAT_LABEL.get, lambda k: f"/jobs/{k}/{city_slug[city]}/" if (DIST / "jobs" / k / city_slug[city]).exists() else None, 12)}</section></div>'
             f'<h2>Neueste Tech-Stellen in {e(city)}</h2>{job_table(t, limit=100)}{cta("Tech-Rollen in " + city)}',
             crumbs=[("Städte", "/staedte/"), (city, None)])
    page("/staedte/", "Tech-Jobs nach Stadt: Berlin, München, Hamburg, Wien, Zürich …", "Offene Tech-Stellen nach Stadt in Deutschland, Österreich und der Schweiz.",
         f'<h1>Städte</h1><ul class="cols">{"".join(city_links)}</ul>', crumbs=[("Städte", None)])

    # ---- ATS
    ats_links = []
    total_cos = len(by_company)
    for a, cos in sorted(ats_companies.items(), key=lambda kv: -len(kv[1])):
        lbl = ATS_LABEL.get(a, a)
        ats_links.append(f'<li><a href="/ats/{a}/">{e(lbl)}</a> <span class="muted">{n(len(cos))} Unternehmen</span></li>')
        lis = "".join(f'<li><a href="/unternehmen/{c}/">{e(names[c])}</a> <span class="muted">{n(len(by_company[c]))} Stellen</span></li>' for c in sorted(cos, key=lambda c: names[c].lower()))
        page(f"/ats/{a}/", f"Welche Unternehmen nutzen {lbl}? {n(len(cos))} Firmen in DACH",
             f"{n(len(cos))} Unternehmen in Deutschland, Österreich und der Schweiz nutzen {lbl} als Bewerbermanagementsystem (ATS). Liste mit offenen Stellen.",
             f'<h1>Unternehmen, die {e(lbl)} nutzen</h1><p class="lead">{n(len(cos))} von {n(total_cos)} Unternehmen im Index ({100 * len(cos) / total_cos:.0f} %) veröffentlichen ihre Stellen über {e(lbl)}.</p><ul class="cols">{lis}</ul>'
             f'<p class="muted">Für Entwickler: <a href="https://github.com/goldfoot/career-site-jobs-api">So liest man {e(lbl)}-Stellen per API aus</a>.</p>',
             crumbs=[("ATS", "/ats/"), (lbl, None)])
    page("/ats/", "Bewerbermanagementsysteme (ATS) im DACH-Tech-Markt: Marktanteile",
         "Welche ATS nutzen Tech-Unternehmen in DACH? Personio, Greenhouse, Lever, Ashby, SmartRecruiters und mehr, gezählt aus Karriereseiten.",
         f'<h1>Welches ATS nutzen DACH-Tech-Unternehmen?</h1><p class="lead">Gezählt über {n(total_cos)} Unternehmen mit offenen Stellen.</p>'
         f'{bar_rows(Counter({a: len(c) for a, c in ats_companies.items()}), total_cos, lambda a: ATS_LABEL.get(a, a), lambda a: f"/ats/{a}/", 20)}<ul class="cols">{"".join(ats_links)}</ul>',
         crumbs=[("ATS", None)])

    static_pages()
    (DIST / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                                      + "".join(f"<url><loc>{u}</loc><lastmod>{STATS['date']}</lastmod></url>" for u in SITEMAP) + "</urlset>\n")
    (DIST / "robots.txt").write_text(("User-agent: *\nDisallow: /\n" if CFG.get("noindex") else "User-agent: *\nAllow: /\n") + f"Sitemap: {BASE}/sitemap.xml\n")
    if CFG.get("cname"):
        (DIST / "CNAME").write_text(CFG["cname"] + "\n")
    (DIST / ".nojekyll").write_text("")
    print(f"built {len(SITEMAP)} pages · {n(len(jobs))} jobs · {n(len(tech))} tech · {len(by_company)} companies")


def company_page(c, js, prev, city_slug):
    name = js[0]["companyName"]
    t = [j for j in js if j["cat"] in TECH]
    cats = Counter(j["cat"] for j in js)
    cities = Counter(ci for j in js for ci in j["cities"])
    remote = sum(j["remote"] for j in js)
    ats = ATS_LABEL.get(js[0]["ats"], js[0]["ats"] or "unbekannt")
    newest = max((j["postedAt"] for j in js if j["postedAt"]), default=None)
    prev_n = sum(1 for j in prev if j["company"] == c) if prev else None
    sal = salary_summary(js)
    facts = [f"{e(name)} hat aktuell <b>{n(len(js))} offene Stellen</b> in DACH {delta(len(js), prev_n)}, davon {n(len(t))} im Tech-Bereich."]
    if cats:
        top = ", ".join(f"{e(CAT_LABEL[k])} ({v})" for k, v in cats.most_common(3))
        facts.append(f"Die meisten Stellen entfallen auf {top}.")
    if cities:
        facts.append("Standorte: " + ", ".join(f'<a href="/staedte/{city_slug[k]}/">{e(k)}</a> ({v})' for k, v in cities.most_common(5)) + ".")
    facts.append(f"Remote ausgeschrieben: {n(remote)} Stellen ({100 * remote / len(js):.0f} %).")
    if sal:
        facts.append(f"{n(sal[0])} Stellen nennen ein Gehalt (Median-Spanne {n(sal[1])} – {n(sal[2])} pro Jahr).")
    facts.append(f'Bewerbermanagement: <a href="/ats/{js[0]["ats"]}/">{e(ats)}</a>. Neueste Ausschreibung: {fmt_date(newest)}.')
    page(f"/unternehmen/{c}/", f"Stellt {name} ein? {n(len(js))} offene Stellen ({fmt_date(STATS['date'])})",
         f"{name} hat {n(len(js))} offene Stellen in Deutschland, Österreich und der Schweiz, davon {n(len(t))} Tech-Stellen. Bereiche, Standorte, Remote-Anteil. Wöchentlich aktualisiert.",
         f'<h1>Stellt {e(name)} ein?</h1><p class="lead">{" ".join(facts)}</p>'
         f'<div class="grid2"><section><h2>Bereiche</h2>{bar_rows(cats, len(js), CAT_LABEL.get, lambda k: f"/jobs/{k}/")}</section>'
         f'<section><h2>Standorte</h2>{bar_rows(cities, len(js), str, lambda k: f"/staedte/{city_slug[k]}/", 8) if cities else "<p class=muted>Nur Remote.</p>"}</section></div>'
         f'<h2>Alle offenen Stellen bei {e(name)}</h2>{job_table(js, show_company=False)}{cta()}',
         crumbs=[("Unternehmen", "/unternehmen/"), (name, None)],
         jsonld=[{"@context": "https://schema.org", "@type": "Organization", "name": name, **({"url": "https://" + js[0]["domain"]} if js[0].get("domain") and "." in js[0]["domain"] and "/" not in js[0]["domain"] and ":" not in js[0]["domain"] else {})}])


def static_pages():
    md = lambda s: s  # noqa: E731  (content is trusted, authored here)
    page("/methodik/", "Methodik: so entsteht der DACH Tech Hiring Index", "Datenquellen, Zählweise und Grenzen des DACH Tech Hiring Index.", md(f"""
<h1>Methodik</h1>
<p>Der Index liest einmal pro Woche die <b>öffentlichen Stellen-Feeds</b> der Karriereseiten von über {n(STATS["companies"])} Unternehmen aus (Greenhouse, Lever, Ashby, Personio, SmartRecruiters, Workable, Recruitee, Teamtailor, Rippling, Breezy HR). Das sind dieselben Daten, die die Unternehmen selbst auf ihrer Website anzeigen.</p>
<ul><li><b>Nur DACH:</b> gezählt werden Stellen mit Standort in Deutschland, Österreich oder der Schweiz sowie Remote-Stellen, die DACH oder Europa einschließen.</li>
<li><b>Bereiche</b> werden automatisch anhand des Stellentitels zugeordnet (z. B. „Site Reliability Engineer“ → DevOps, SRE &amp; Platform). Einzelne Zuordnungen können falsch sein.</li>
<li><b>Tech-Stellen</b> = Engineering, DevOps, Data/KI, Security, Mobile, QA, Produkt, Design, IT, Hardware/Embedded.</li>
<li><b>Δ Woche</b> vergleicht mit dem Stand der Vorwoche.</li>
<li>Unternehmen, deren Karriereseite über Workday, SuccessFactors o. ä. läuft, sind (noch) nicht enthalten.</li></ul>
<p>Es werden keine Bewerberdaten oder personenbezogenen Daten erhoben. Jede Stelle verlinkt auf die Originalausschreibung.</p>
<p>Die Daten stammen aus dem <a href="{CFG["actorUrl"]}">Career Site Jobs Scraper</a>. Entwickler finden Beispiele unter <a href="https://github.com/goldfoot/career-site-jobs-api">github.com/goldfoot/career-site-jobs-api</a>.</p>
<p>Fehlt ein Unternehmen? <a href="{CFG["contactHref"]}">Schreiben Sie uns</a>.</p>"""), crumbs=[("Methodik", None)])
    page("/hiring-signale/", "Hiring-Signale: wöchentliche Lead-Liste für B2B-Vertrieb", "Welche Unternehmen in Ihrer Zielgruppe stellen gerade passende Rollen ein? Wöchentliche Liste als CSV.", md(f"""
<h1>Hiring-Signale für Ihren Vertrieb</h1>
<p class="lead">Ein Unternehmen, das drei DevOps-Engineers sucht, hat ein Infrastruktur-Thema. Eines, das einen „Head of Data“ sucht, baut gerade sein Datenteam auf. Für Dienstleister, Agenturen, Freelancer und SaaS-Anbieter sind das die besten Zeitpunkte für eine Kontaktaufnahme.</p>
<h2>Was Sie bekommen</h2>
<ul><li>Jeden Montag eine CSV/Excel-Liste: Unternehmen, neue passende Stellen, Standorte, Link zur Ausschreibung.</li>
<li>Gefiltert auf Ihre Rollen (z. B. DevOps, Data, Security, SAP, Salesforce) und Regionen.</li>
<li>Nur Unternehmensdaten, keine personenbezogenen Kontaktdaten.</li></ul>
<h2>Selbst machen</h2>
<p>Technisch versiert? Der <a href="{CFG["actorUrl"]}">Career Site Jobs Scraper</a> liefert dieselben Daten per API, mit „nur neue Stellen“-Modus für wöchentliche Alerts. Abrechnung pro gefundener Stelle.</p>
<h2>Fertig geliefert</h2>
<p>{CFG["leadOfferText"]}</p>
<p><a class="btn" href="{CFG["contactHref"]}">Beispiel-Liste anfordern</a></p>"""), crumbs=[("Hiring-Signale", None)])
    page("/impressum/", "Impressum", "Impressum", CFG["impressumHtml"], crumbs=[("Impressum", None)])
    page("/datenschutz/", "Datenschutz", "Datenschutzerklärung", CFG["privacyHtml"], crumbs=[("Datenschutz", None)])


def relativize():
    """Preview mode: rewrite root-relative links so the site works from any base path (artifact preview, file://)."""
    for f in DIST.rglob("*.html"):
        depth = len(f.relative_to(DIST).parts) - 1
        pre = "../" * depth or "./"
        h = f.read_text()
        h = re.sub(r'(href|src)="/([^"]*)"', lambda m: f'{m.group(1)}="{pre}{m.group(2)}{"index.html" if (m.group(2) == "" or m.group(2).endswith("/")) else ""}"', h)
        f.write_text(h)


if __name__ == "__main__":
    jobs = load_jobs()
    if "--snapshot" in sys.argv:
        write_snapshot(jobs, TODAY.isoformat())
    build(jobs, load_snapshots())
    if "--relative" in sys.argv:
        relativize()
