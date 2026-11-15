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
REMOTE_ONLY = re.compile(r"\b(remote|anywhere|worldwide|dach|europe|europa|emea|eu|cet|home ?office|mobile arbeit|hybrid|full[- ]?time|\(?(?:de|at|ch|eu|dach)\)?)\b|[|,;/()\-–\s]+", re.I)

CATEGORIES = [  # (slug, label, tech?, regex) — first match wins
    ("sales", "Sales & Business Development", False, r"\bsales\b|vertrieb|account (executive|manager)|business development|\bsdr\b|\bbdr\b|key account"),
    ("people", "HR & Recruiting", False, r"recruit|talent acquisition|\bhr\b|people (partner|operations)|personalreferent"),
    ("finance-legal", "Finanzen & Recht", False, r"einkauf|procurement|buyer|purchas|financ|finanz|accounting|buchhalt|controll|\btax\b|steuer|legal|counsel|jurist"),
    ("devops-sre-platform", "DevOps, SRE & Platform", True, r"devops|\bsre\b|site reliability|platform engineer|cloud engineer|infrastructure|kubernetes|systems? engineer"),
    ("security", "IT-Security", True, r"(?:it|cyber|information|informations|application|cloud|network|netzwerk|product|app|sap|firmware|data|offensive|ot)[- ]?(?:security|sicherheit)|informationssicherheit|it-sicherheit|cybersecurity|security (?:engineer|architect|analyst|consultant|operations|researcher|specialist|officer|manager|lead|expert)|pentest|penetration|\bsoc\b|ciso|\biam\b|zero trust|incident response|\bisms\b"),
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
    ("healthcare", "Gesundheit & Pflege", False, r"pflege|krankenschwester|gesundheits|\bmfa\b|medizinische[rn]? fachangestellte|zahnmedizin|\bzfa\b|arzt|ärztin|physiotherap|ergotherap|apothe|therapeut|klinik|praxis"),
    ("education-social", "Bildung & Soziales", False, r"erzieher|pädagog|sozialarbeit|heilerzieh|kita\b|lehrer|lehrkraft|dozent|ausbilder|betreuer"),
    ("retail", "Handel & Verkauf", False, r"verkäufer|verkauf\b|filial|kassierer|einzelhandel|store manager|markt|retail"),
    ("logistics", "Logistik, Lager & Fahrer", False, r"lager|logistik|logistic|warehouse|kommission|fahrer|zusteller|kurier|disponent|spedition|versand"),
    ("hospitality", "Gastronomie & Hotellerie", False, r"\bkoch\b|köchin|küche|gastronom|restaurant|hotel|rezeption|servicekraft|kellner|housekeeping"),
    ("trades", "Handwerk & Technik", False, r"elektriker|elektroniker|mechaniker|mechatroniker|monteur|installateur|schlosser|schweißer|tischler|maler|handwerk|servicetechniker|kfz|haustechnik|hausmeister|anlagenführer|produktionsmitarbeiter|cnc"),
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
                     "domain": j.get("input"), "track": "ausbildung" if AUSBILDUNG_RE.search(j["title"]) else "werkstudent" if STUDENT_JOB_RE.search(j["title"]) else None, **c})
    return jobs


AUSBILDUNG_RE = re.compile(r"ausbildung|azubi|auszubildende|duales studium|dualer student|duale[rs]? studi|apprentice", re.I)
STUDENT_JOB_RE = re.compile(r"werkstudent|working student|praktik|internship|\bintern\b|abschlussarbeit|thesis|masterarbeit|bachelorarbeit", re.I)
CITY_COUNTRY = {}


def load_index_jobs():
    """Jobs from the DACH Jobs API index (data/index-latest.json, written by fetch.py --index): already DACH-filtered and classified."""
    idx = json.loads((DATA / "index-latest.json").read_text())
    jobs = []
    cc = defaultdict(Counter)
    for j in idx["jobs"]:
        name = j["company"].strip()
        for c in j["cities"]:
            for k in j["countries"]:
                cc[c][k] += 1
        level = {"student": "junior"}.get(j["seniority"], j["seniority"])
        title = j["title"].strip()
        jobs.append({"uid": j["id"], "company": slugify(name), "companyName": name, "title": title, "url": j.get("url"),
                     "ats": j.get("ats"), "location": j.get("location") or "", "postedAt": (j.get("postedAt") or "")[:10] or None,
                     "firstSeen": (j.get("firstSeenAt") or "")[:10] or None, "department": j.get("department"),
                     "salaryText": j.get("salaryText"), "salaryMin": j.get("salaryMin"), "salaryMax": j.get("salaryMax"),
                     "salaryCurrency": j.get("salaryCurrency"), "salaryInterval": j.get("salaryInterval"), "domain": j.get("companyWebsite"),
                     "cities": j["cities"], "countries": j["countries"], "remote": j.get("workplace") == "remote", "hybrid": j.get("workplace") == "hybrid",
                     "cat": j["category"], "level": level,
                     "track": "ausbildung" if AUSBILDUNG_RE.search(title) else "werkstudent" if STUDENT_JOB_RE.search(title) else None})
    CITY_COUNTRY.update({c: k.most_common(1)[0][0] for c, k in cc.items()})
    return jobs, idx["updatedAt"][:10]


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


MONTHS = ["Jan.", "Feb.", "März", "Apr.", "Mai", "Juni", "Juli", "Aug.", "Sept.", "Okt.", "Nov.", "Dez."]


def month_label(d):
    y, m, _ = d.split("-")
    return f"{MONTHS[int(m) - 1]} {y}"


def fit_title(*variants, limit=60):
    """First variant that fits Google's ~60-char title width; else the shortest, cut at a word."""
    for v in variants:
        if len(v) <= limit:
            return v
    v = min(variants, key=len)
    return v if len(v) <= limit else v[:limit - 1].rsplit(" ", 1)[0] + "…"


def fit_desc(s, limit=155):
    return s if len(s) <= limit else s[:limit - 1].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def delta(cur, prev):
    if prev is None:
        return ""
    d = cur - prev
    if d == 0:
        return '<span class="d0">±0</span>'
    return f'<span class="{"up" if d > 0 else "down"}">{"+" if d > 0 else "−"}{n(abs(d))}</span>'


def page(path, title, desc, body, crumbs=(), jsonld=None):
    url = f"{BASE}{path}"
    desc = fit_desc(desc)
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
<nav><a href="/jobs/">Bereiche</a><a href="/staedte/">Städte</a><a href="/unternehmen/">Unternehmen</a><a href="/ausbildung/">Ausbildung</a><a href="/werkstudent/">Werkstudent</a><a href="/analysen/">Analysen</a><a href="/hiring-signale/" class="cta-link">Hiring-Signale</a></nav></div></header>
<main class="wrap">{crumb_html}{body}</main>
<footer><div class="wrap"><p>Daten: öffentliche Karriereseiten von {n(STATS["companies"])} Unternehmen, Stand {fmt_date(STATS["date"])}. Wöchentlich aktualisiert. <a href="/methodik/">Methodik</a> · <a href="/daten/">Daten-Download</a> · <a href="/impressum/">Impressum</a> · <a href="/datenschutz/">Datenschutz</a></p>
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
        cname = f'<a href="/unternehmen/{j["company"]}/">{e(j["companyName"])}</a>' if j["company"] in PAGE_COS else e(j["companyName"])
        comp = f'<td>{cname}</td>' if show_company else ""
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
<p><a class="btn" href="/hiring-signale/">Beispiel-Liste ansehen</a> <a class="btn ghost" href="{CFG.get("indexActorUrl", CFG["actorUrl"])}" rel="noopener">Alle Stellen per API durchsuchen</a></p></aside>"""


# ---------------------------------------------------------------- pages
SITEMAP = []
STATS = {}
USED_TITLES = set()
IS_NEW = [lambda j: False]


def new_note(js):
    k = sum(1 for j in js if IS_NEW[0](j))
    return f" Neu in den letzten 7 Tagen: <b>{n(k)}</b>." if k else ""
REGION_PAGE = {}
PAGE_COS = set()  # companies that get their own page (enough jobs to not be thin)
MIN_COMPANY_JOBS = 3
MIN_COMBO_JOBS = 5


def pct_of(js, pred):
    return 100 * sum(1 for j in js if pred(j)) / len(js) if js else 0.0


def has_salary(j):
    return bool(j.get("salaryMin") or j.get("salaryMax"))


def vs(x, base):
    """'deutlich mehr als', 'etwa so viel wie' … relative to a DACH average (both in %)."""
    if base <= 0:
        return ""
    r = x / base
    return ("mehr als doppelt so hoch wie" if r >= 2 else "deutlich höher als" if r >= 1.3 else "etwas höher als" if r >= 1.08
            else "etwa so hoch wie" if r > 0.92 else "etwas niedriger als" if r > 0.77 else "deutlich niedriger als" if r > 0.5 else "weniger als halb so hoch wie")


def insights(items):
    items = [i for i in items if i]
    html_ = f'<ul class="insights">{"".join(f"<li>{i}</li>" for i in items)}</ul>' if items else ""
    return re.sub(r"(\d)\.(\d+) %", r"\1,\2 %", html_)  # German decimal comma


def salary_summary(jobs):
    eur = [j for j in jobs if j["salaryMin"] and j["salaryCurrency"] in ("EUR", "CHF") and (j["salaryInterval"] or "").upper().find("YEAR") >= 0]
    if len(eur) < 3:
        return None
    lo = sorted(j["salaryMin"] for j in eur)
    hi = sorted(j["salaryMax"] or j["salaryMin"] for j in eur)
    med = lambda a: a[len(a) // 2]  # noqa: E731
    return len(eur), med(lo), med(hi)


def build(jobs, snaps, data_date=None):
    for _ in range(5):  # rmtree on thousands of dirs can race with macOS indexing; retry
        if not DIST.exists():
            break
        shutil.rmtree(DIST, ignore_errors=True)
    DIST.mkdir()
    shutil.copy(ROOT / "static" / "style.css", DIST / "style.css")
    shutil.copy(ROOT / "static" / "favicon.svg", DIST / "favicon.svg")
    prev = snaps[-2][1] if len(snaps) >= 2 else None
    if prev is not None and len(prev) < 0.5 * len(jobs):
        prev = None  # previous snapshot came from the smaller tech-only crawl → no meaningful weekly deltas yet
    prev_by = lambda keyfn: Counter(k for j in prev for k in keyfn(j)) if prev else None  # noqa: E731

    tech = [j for j in jobs if j["cat"] in TECH]
    by_company = defaultdict(list)
    for j in jobs:
        by_company[j["company"]].append(j)
    PAGE_COS.clear()
    PAGE_COS.update(c for c, js in by_company.items() if len(js) >= MIN_COMPANY_JOBS)
    date = data_date or (snaps[-1][0] if snaps else TODAY.isoformat())
    STATS.update(date=date, companies=len(by_company), jobs=len(jobs), tech=len(tech), month=month_label(date))
    mon = STATS["month"]
    names = {c: js[0]["companyName"] for c, js in by_company.items()}
    co_link = lambda k: f"/unternehmen/{k}/" if k in PAGE_COS else None  # noqa: E731
    tech_by_company = Counter(j["company"] for j in tech)
    prev_tech_company = prev_by(lambda j: [j["company"]] if j["cat"] in TECH else []) if prev else None
    prev_tech_total = sum(1 for j in prev if j["cat"] in TECH) if prev else None
    city_count = Counter(c for j in jobs for c in j["cities"])
    city_tech = Counter(c for j in tech for c in j["cities"])
    cities_with_page = [c for c, v in city_count.most_common() if v >= MIN_COMBO_JOBS]
    city_slug = {c: slugify(c) for c in city_count}
    country_of = lambda c: CITY_COUNTRY.get(c) or CITIES.get(c, ("DE", ""))[0]  # noqa: E731
    ats_companies = defaultdict(set)
    for j in jobs:
        if j["ats"]:
            ats_companies[j["ats"]].add(j["company"])
    week_ago = (dt.date.fromisoformat(date) - dt.timedelta(days=7)).isoformat()
    is_new = lambda j: (j.get("firstSeen") or j["postedAt"] or "") >= week_ago if prev is not None else (j["postedAt"] or "") >= week_ago  # noqa: E731
    IS_NEW[0] = is_new
    new_week = [j for j in jobs if is_new(j)]
    sector_count = Counter(j["cat"] for j in jobs)
    BASE_REMOTE, BASE_SAL = pct_of(jobs, lambda j: j["remote"]), pct_of(jobs, has_salary)
    BASE_TRACK = pct_of(jobs, lambda j: j["track"])
    cat_city = Counter((j["cat"], c) for j in jobs for c in j["cities"])

    # ---- home
    top_rows = "".join(
        f'<tr><td>{i + 1}</td><td><a href="/unternehmen/{c}/">{e(names[c])}</a></td><td class="r">{n(len(by_company[c]))}</td><td class="r">{n(tech_by_company.get(c, 0))}</td></tr>'
        for i, (c, _) in enumerate(Counter({c: len(js) for c, js in by_company.items()}).most_common(25)))
    tech_rows = "".join(
        f'<tr><td>{i + 1}</td><td><a href="/unternehmen/{c}/">{e(names[c])}</a></td><td class="r">{n(v)}</td>'
        f'<td class="r">{delta(v, prev_tech_company.get(c, 0)) if prev_tech_company is not None else ""}</td></tr>'
        for i, (c, v) in enumerate(tech_by_company.most_common(15)))
    trainee = sum(1 for j in jobs if j["track"])
    body = f"""<section class="hero"><h1>Wer stellt ein? Offene Stellen in DACH, direkt von den Karriereseiten</h1>
<p class="lead">Jede Woche lesen wir die Karriereseiten von {n(len(by_company))} Arbeitgebern in Deutschland, Österreich und der Schweiz aus: vom Tech-Startup über Kliniken und Handwerksbetriebe bis zum Konzern. Ohne Jobbörsen-Dubletten, ohne Personalvermittler, jede Stelle mit Link zur Originalausschreibung.</p>
{stat_tiles([(n(len(jobs)), "offene Stellen"), (n(len(by_company)), "Arbeitgeber"), (n(len(tech)) + " " + delta(len(tech), prev_tech_total), "davon Tech-Stellen"), (n(trainee), "Ausbildung, Werkstudent, Praktikum")])}
<p class="muted">Stand: {fmt_date(date)}</p></section>
{latest_article_teaser()}
<div class="grid2"><section><h2>Wer sucht gerade die meisten Leute?</h2>
<table class="rank"><thead><tr><th>#</th><th>Arbeitgeber</th><th class="r">Stellen</th><th class="r">davon Tech</th></tr></thead><tbody>{top_rows}</tbody></table>
<p><a href="/unternehmen/">Alle Arbeitgeber →</a></p></section>
<section><h2>Stellen nach Bereich</h2>{bar_rows(sector_count, len(jobs), CAT_LABEL.get, lambda k: f"/jobs/{k}/", 14)}
<h2>Stellen nach Stadt</h2>{bar_rows(city_count, len(jobs), str, lambda k: f"/staedte/{city_slug[k]}/" if k in cities_with_page else None, 10)}
<p><a href="/ausbildung/">Ausbildungsplätze →</a> · <a href="/werkstudent/">Werkstudenten-Jobs &amp; Praktika →</a></p></section></div>
<div class="grid2"><section><h2>Tech: wer sucht die meisten Tech-Leute?</h2>
<table class="rank"><thead><tr><th>#</th><th>Unternehmen</th><th class="r">Tech-Stellen</th><th class="r">Δ Woche</th></tr></thead><tbody>{tech_rows}</tbody></table></section>
<section><h2>Tech-Bereiche</h2>{bar_rows(Counter(j["cat"] for j in tech), len(tech), CAT_LABEL.get, lambda k: f"/jobs/{k}/")}</section></div>
<section><h2>Neu diese Woche</h2>{job_table(new_week, limit=30) if new_week else '<p class="muted">Noch keine Daten.</p>'}</section>
{cta()}"""
    page("/", fit_title(f"Wer stellt ein? {n(len(jobs))} offene Stellen in DACH ({mon})", f"Wer stellt ein? {n(len(jobs))} offene Stellen in DACH"),
         f"{n(len(jobs))} offene Stellen von {n(len(by_company))} Arbeitgebern in Deutschland, Österreich und der Schweiz, direkt von den Karriereseiten. Wöchentlich aktualisiert.",
         body, jsonld=[{"@context": "https://schema.org", "@type": "Dataset", "name": "Wer stellt ein? DACH-Stellenindex",
                        "description": "Wöchentliche Zählung offener Stellen von Arbeitgebern in Deutschland, Österreich und der Schweiz aus öffentlichen Karriereseiten.",
                        "url": BASE + "/", "dateModified": date, "spatialCoverage": "DACH", "isAccessibleForFree": True,
                        "creator": {"@type": "Organization", "name": CFG["brand"]}}])

    # ---- companies
    rows = []
    for c, js in sorted(by_company.items(), key=lambda kv: -len(kv[1])):
        t = sum(1 for j in js if j["cat"] in TECH)
        nm = f'<a href="/unternehmen/{c}/">{e(names[c])}</a>' if c in PAGE_COS else e(names[c])
        rows.append(f'<tr><td>{nm}</td><td class="r">{n(len(js))}</td><td class="r">{n(t)}</td><td>{e(CAT_LABEL.get(Counter(j["cat"] for j in js).most_common(1)[0][0], ""))}</td></tr>')
        if c in PAGE_COS:
            company_page(c, js, prev, city_slug, cities_with_page)
    page("/unternehmen/", fit_title(f"Welche Firmen stellen ein? {n(len(by_company))} Arbeitgeber in DACH"),
         f"{n(len(by_company))} Arbeitgeber in Deutschland, Österreich und der Schweiz mit offenen Stellen, sortiert nach Anzahl. Wöchentlich aktualisiert.",
         f'<h1>Arbeitgeber, die gerade einstellen</h1><p class="lead">{n(len(by_company))} Arbeitgeber mit offenen Stellen in DACH, Stand {fmt_date(date)}. '
         f'Unternehmen mit mindestens {MIN_COMPANY_JOBS} Stellen haben eine eigene Seite mit Bereichen, Standorten und allen Ausschreibungen.</p>'
         f'<input class="filter" placeholder="Arbeitgeber filtern …" oninput="for(const r of document.querySelectorAll(\'tbody tr\'))r.hidden=!r.textContent.toLowerCase().includes(this.value.toLowerCase())">'
         f'<div class="tw"><table class="rank"><thead><tr><th>Arbeitgeber</th><th class="r">Stellen</th><th class="r">davon Tech</th><th>Größter Bereich</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>',
         crumbs=[("Unternehmen", None)])

    # ---- categories (+ category x city)
    cat_links = []
    for slug, label, is_tech, _ in CAT_UNIQUE:
        js = [j for j in jobs if j["cat"] == slug]
        if not js:
            continue
        ccity = Counter(c for j in js for c in j["cities"])
        comp = Counter(j["company"] for j in js)
        cat_links.append(f'<tr><td><a href="/jobs/{slug}/">{e(label)}</a></td><td class="r">{n(len(js))}</td><td class="r">{n(len(comp))}</td><td>{"Tech" if is_tech else ""}</td></tr>')
        sub = []
        for city, cnt in ccity.most_common():
            if cnt < MIN_COMBO_JOBS:
                continue
            sub.append(f'<a class="chip" href="/jobs/{slug}/{city_slug[city]}/">{e(city)} ({cnt})</a>')
            cj = [j for j in js if city in j["cities"]]
            ccomp = Counter(j["company"] for j in cj)
            share = 100 * cnt / max(city_count[city], 1)
            page(f"/jobs/{slug}/{city_slug[city]}/",
                 fit_title(f"{label} Jobs {city}: {n(cnt)} offene Stellen ({mon})", f"{label} Jobs {city}: {n(cnt)} offene Stellen", f"{label} Jobs {city}: {n(cnt)} Stellen"),
                 f"{n(cnt)} offene Stellen im Bereich {label} in {city} bei {n(len(ccomp))} Arbeitgebern, direkt von den Karriereseiten. Stand {fmt_date(date)}.",
                 f'<h1>{e(label)} in {e(city)}</h1><p class="lead">{n(cnt)} offene Stellen bei {n(len(ccomp))} Arbeitgebern, Stand {fmt_date(date)}. '
                 f'Das sind {share:.0f} % aller {n(city_count[city])} Stellen in {e(city)}. Am meisten sucht {e(names[ccomp.most_common(1)[0][0]])} ({ccomp.most_common(1)[0][1]}).{new_note(cj)}</p>'
                 + insights([
                     f"{e(city)} liegt bei {e(label)} auf <b>Platz {[c for c, _ in ccity.most_common()].index(city) + 1}</b> von {len(ccity)} Städten; hier sind {100 * cnt / len(js):.1f} % aller {e(label)}-Stellen im Index.",
                     f"Der Anteil an {e(label)} unter allen Stellen in {e(city)} ({share:.0f} %) ist {vs(share, 100 * len(js) / len(jobs))} im DACH-Schnitt ({100 * len(js) / len(jobs):.0f} %)." if len(js) >= 50 else "",
                     f"{pct_of(cj, has_salary):.0f} % dieser Stellen nennen ein Gehalt ({e(label)} insgesamt: {pct_of(js, has_salary):.0f} %)." if cnt >= 10 else "",
                     f"{len([c for c, v in ccomp.items() if v >= 3])} Arbeitgeber suchen hier gleich mehrere Leute (3+ Stellen)." if any(v >= 3 for v in ccomp.values()) else "",
                 ]) + f'<h2>Arbeitgeber</h2>{bar_rows(ccomp, cnt, names.get, co_link, 15)}<h2>Alle Stellen</h2>{job_table(cj)}{cta(label + "-Rollen in " + city)}',
                 crumbs=[("Bereiche", "/jobs/"), (label, f"/jobs/{slug}/"), (city, None)])
        sal = salary_summary(js)
        sal_html = f'<p>Gehaltsangaben: {n(sal[0])} Stellen nennen ein Gehalt, Median-Spanne <b>{n(sal[1])} – {n(sal[2])}</b> pro Jahr.</p>' if sal else ""
        lvl = Counter(j["level"] for j in js)
        page(f"/jobs/{slug}/", fit_title(f"{label} Jobs in DACH: {n(len(js))} offene Stellen ({mon})", f"{label} Jobs: {n(len(js))} offene Stellen in DACH", f"{label} Jobs: {n(len(js))} Stellen"),
             f"Wer stellt im Bereich {label} ein? {n(len(js))} offene Stellen bei {n(len(comp))} Arbeitgebern in Deutschland, Österreich und der Schweiz.",
             f'<h1>{e(label)}: wer stellt ein?</h1><p class="lead">{n(len(js))} offene Stellen bei {n(len(comp))} Arbeitgebern in DACH '
             f'{delta(len(js), sum(1 for j in prev if j["cat"] == slug) if prev else None)}. '
             f'Senior/Leitung: {100 * lvl["senior"] / len(js):.0f} %, Junior/Einstieg/Ausbildung: {100 * lvl["junior"] / len(js):.0f} %, Remote: {100 * sum(j["remote"] for j in js) / len(js):.0f} %.{new_note(js)}</p>{sal_html}'
             + insights([
                 (lambda lq: f"Besonders stark vertreten in <b>{e(lq[0])}</b>: dort sind {lq[1]:.0f} % aller Stellen aus diesem Bereich, im DACH-Schnitt {100 * len(js) / len(jobs):.0f} %." if lq else "")(
                     max(((c, 100 * v / city_count[c]) for c, v in ccity.items() if v >= 10 and city_count[c] >= 100), key=lambda x: x[1], default=None)),
                 f"Der Remote-Anteil ({pct_of(js, lambda j: j['remote']):.1f} %) ist {vs(pct_of(js, lambda j: j['remote']), BASE_REMOTE)} über alle Bereiche ({BASE_REMOTE:.1f} %)." if len(js) >= 30 else "",
                 f"Gehaltsangabe bei {pct_of(js, has_salary):.0f} % der Stellen: Der Anteil ist {vs(pct_of(js, has_salary), BASE_SAL)} im Schnitt aller Bereiche ({BASE_SAL:.0f} %)." if len(js) >= 30 else "",
                 f"Die 10 größten Arbeitgeber stellen {100 * sum(v for _, v in comp.most_common(10)) / len(js):.0f} % der Stellen; insgesamt suchen {n(len(comp))} Arbeitgeber." if len(comp) > 10 else "",
             ]) + f'<div class="chips">{"".join(sub)}</div><div class="grid2"><section><h2>Top-Arbeitgeber</h2>{bar_rows(comp, len(js), names.get, co_link, 15)}</section>'
             f'<section><h2>Städte</h2>{bar_rows(ccity, len(js), str, lambda k: f"/staedte/{city_slug[k]}/" if k in cities_with_page else None, 12)}</section></div>'
             f'<h2>Neueste Stellen</h2>{job_table(js, limit=100)}{cta(label + "-Rollen")}',
             crumbs=[("Bereiche", "/jobs/"), (label, None)])
    page("/jobs/", fit_title(f"Jobs nach Bereich: {n(len(jobs))} offene Stellen in DACH"),
         "Offene Stellen nach Bereich: Gesundheit & Pflege, Handwerk, Handel, Logistik, Vertrieb, IT, Data & KI, Engineering und mehr.",
         f'<h1>Offene Stellen nach Bereich</h1><p class="lead">{n(len(jobs))} offene Stellen bei {n(len(by_company))} Arbeitgebern in DACH, automatisch nach Stellentitel einem Bereich zugeordnet. '
         f'Größter Bereich: {e(CAT_LABEL[sector_count.most_common(1)[0][0]])}. {n(len(tech))} Stellen ({100 * len(tech) / len(jobs):.0f} %) sind Tech-Stellen.</p>'
         f'<div class="tw"><table class="rank"><thead><tr><th>Bereich</th><th class="r">Stellen</th><th class="r">Arbeitgeber</th><th></th></tr></thead><tbody>{"".join(cat_links)}</tbody></table></div>',
         crumbs=[("Bereiche", None)])

    # ---- cities
    city_links = []
    for city in cities_with_page:
        js = [j for j in jobs if city in j["cities"]]
        t = [j for j in js if j["cat"] in TECH]
        comp = Counter(j["company"] for j in js)
        cc = country_of(city)
        rank = cities_with_page.index(city) + 1
        city_links.append(f'<tr><td><a href="/staedte/{city_slug[city]}/">{e(city)}</a></td><td>{COUNTRY_NAME[cc]}</td><td class="r">{n(len(js))}</td><td class="r">{n(len(t))}</td></tr>')
        top_cat = Counter(j["cat"] for j in js).most_common(1)[0]
        page(f"/staedte/{city_slug[city]}/", fit_title(f"Jobs in {city}: {n(len(js))} offene Stellen ({mon})", f"Jobs in {city}: {n(len(js))} offene Stellen", f"Jobs {city}: {n(len(js))} Stellen"),
             f"Wer stellt in {city} ein? {n(len(js))} offene Stellen bei {n(len(comp))} Arbeitgebern, davon {n(len(t))} Tech-Stellen. Direkt von den Karriereseiten, wöchentlich aktualisiert.",
             f'<h1>Wer stellt in {e(city)} ein?</h1><p class="lead">{n(len(js))} offene Stellen bei {n(len(comp))} Arbeitgebern ({COUNTRY_NAME[cc]}), Platz {rank} unter {len(cities_with_page)} Städten im Index. '
             f'Größter Bereich: {e(CAT_LABEL[top_cat[0]])} ({n(top_cat[1])}). Tech-Stellen: {n(len(t))}. Am meisten sucht {e(names[comp.most_common(1)[0][0]])} ({comp.most_common(1)[0][1]}).{new_note(js)}</p>'
             + insights([
                 (lambda lq: f"Überdurchschnittlich gesucht: <b>{e(CAT_LABEL[lq[0]])}</b> mit {lq[1]:.0f} % der Stellen in {e(city)} (DACH-Schnitt: {lq[2]:.0f} %)." if lq else "")(
                     max(((k, 100 * cat_city[(k, city)] / len(js), 100 * v / len(jobs)) for k, v in sector_count.items() if k != "operations" and cat_city[(k, city)] >= max(10, 0.02 * len(js))),
                         key=lambda x: x[1] / max(x[2], 0.1), default=None)) if len(js) >= 50 else "",
                 f"Gehaltsangabe bei {pct_of(js, has_salary):.0f} % der Stellen: Der Anteil ist {vs(pct_of(js, has_salary), BASE_SAL)} im DACH-Schnitt ({BASE_SAL:.0f} %)." if len(js) >= 30 else "",
                 f"Remote ausgeschrieben: {pct_of(js, lambda j: j['remote']):.1f} % ({vs(pct_of(js, lambda j: j['remote']), BASE_REMOTE)} der Schnitt von {BASE_REMOTE:.1f} %)." if len(js) >= 30 else "",
                 f"{n(sum(1 for j in js if j['track']))} Ausbildungs-, Werkstudenten- oder Praktikumsplätze ({pct_of(js, lambda j: j['track']):.0f} %, DACH: {BASE_TRACK:.0f} %)." if any(j["track"] for j in js) else "",
             ]) + f'<div class="grid2"><section><h2>Arbeitgeber mit den meisten Stellen</h2>{bar_rows(comp, len(js), names.get, co_link, 15)}</section>'
             f'<section><h2>Bereiche</h2>{bar_rows(Counter(j["cat"] for j in js), len(js), CAT_LABEL.get, lambda k: f"/jobs/{k}/{city_slug[city]}/" if (DIST / "jobs" / k / city_slug[city]).exists() else None, 14)}</section></div>'
             f'<h2>Neueste Stellen in {e(city)}</h2>{job_table(js, limit=100)}{cta("Rollen in " + city)}',
             crumbs=[("Städte", "/staedte/"), (city, None)])
    page("/staedte/", fit_title(f"Jobs nach Stadt: {len(cities_with_page)} Städte in DACH"), "Offene Stellen nach Stadt in Deutschland, Österreich und der Schweiz: Berlin, München, Hamburg, Wien, Zürich und mehr.",
         f'<h1>Offene Stellen nach Stadt</h1><p class="lead">{len(cities_with_page)} Städte mit mindestens {MIN_COMBO_JOBS} offenen Stellen. Stellen ohne erkennbare Stadt (nur Region oder Remote) zählen nur in den Bereichen. Übersicht nach <a href="/regionen/">Bundesland und Kanton</a>.</p>'
         f'<div class="tw"><table class="rank"><thead><tr><th>Stadt</th><th>Land</th><th class="r">Stellen</th><th class="r">davon Tech</th></tr></thead><tbody>{"".join(city_links)}</tbody></table></div>',
         crumbs=[("Städte", None)])

    # ---- regions (Bundesländer, Kantone)
    from regions import region_of, REGION_COUNTRY
    reg_jobs = defaultdict(list)
    for j in jobs:
        for r in {region_of(c, country_of(c)) for c in j["cities"]} - {None}:
            reg_jobs[r].append(j)
    reg_links = defaultdict(list)
    REGION_PAGE.clear()
    for r, js in sorted(reg_jobs.items(), key=lambda kv: -len(kv[1])):
        rc = Counter(c for j in js for c in j["cities"] if region_of(c, country_of(c)) == r)
        if len(js) < 20 or rc.most_common(1)[0][1] >= 0.9 * len(js):
            # city-states and regions dominated by one city: the city page already covers it
            only = rc.most_common(1)[0][0]
            if only in cities_with_page:
                reg_links[REGION_COUNTRY[r]].append(f'<li><a href="/staedte/{city_slug[only]}/">{e(r)}</a> <span class="muted">{n(len(js))} Stellen</span></li>')
            continue
        rslug = slugify(r)
        REGION_PAGE[r] = rslug
        reg_links[REGION_COUNTRY[r]].append(f'<li><a href="/regionen/{rslug}/">{e(r)}</a> <span class="muted">{n(len(js))} Stellen</span></li>')
        comp = Counter(j["company"] for j in js)
        rsec = Counter(j["cat"] for j in js)
        city_chips = "".join(f'<a class="chip" href="/staedte/{city_slug[c]}/">{e(c)} ({v})</a>' if c in cities_with_page else f'<span class="chip">{e(c)} ({v})</span>' for c, v in rc.most_common())
        lq = max(((k, 100 * v / len(js), 100 * sector_count[k] / len(jobs)) for k, v in rsec.items() if k != "operations" and v >= max(10, 0.02 * len(js))),
                 key=lambda x: x[1] / max(x[2], 0.1), default=None)
        page(f"/regionen/{rslug}/", fit_title(f"Jobs in {r}: {n(len(js))} offene Stellen ({mon})", f"Jobs in {r}: {n(len(js))} offene Stellen", f"Jobs {r}: {n(len(js))} Stellen"),
             f"Wer stellt in {r} ein? {n(len(js))} offene Stellen bei {n(len(comp))} Arbeitgebern in {len(rc)} Städten, direkt von den Karriereseiten. Stand {fmt_date(date)}.",
             f'<h1>Wer stellt in {e(r)} ein?</h1><p class="lead">{n(len(js))} offene Stellen bei {n(len(comp))} Arbeitgebern in {len(rc)} Städten ({COUNTRY_NAME[REGION_COUNTRY[r]]}), Stand {fmt_date(date)}. '
             f'Die meisten Stellen hat {e(rc.most_common(1)[0][0])} ({n(rc.most_common(1)[0][1])}).{new_note(js)}</p>'
             + insights([
                 f"Überdurchschnittlich gesucht: <b>{e(CAT_LABEL[lq[0]])}</b> mit {lq[1]:.0f} % der Stellen (DACH-Schnitt: {lq[2]:.0f} %)." if lq else "",
                 f"Gehaltsangabe bei {pct_of(js, has_salary):.0f} % der Stellen: Der Anteil ist {vs(pct_of(js, has_salary), BASE_SAL)} im DACH-Schnitt ({BASE_SAL:.0f} %)." if len(js) >= 30 else "",
                 f"Remote ausgeschrieben: {pct_of(js, lambda j: j['remote']):.1f} % ({vs(pct_of(js, lambda j: j['remote']), BASE_REMOTE)} der Schnitt von {BASE_REMOTE:.1f} %)." if len(js) >= 30 else "",
                 f"{n(sum(1 for j in js if j['track']))} Ausbildungs-, Werkstudenten- oder Praktikumsplätze." if any(j["track"] for j in js) else "",
             ])
             + f'<h2>Städte</h2><div class="chips">{city_chips}</div>'
             f'<div class="grid2"><section><h2>Arbeitgeber mit den meisten Stellen</h2>{bar_rows(comp, len(js), names.get, co_link, 15)}</section>'
             f'<section><h2>Bereiche</h2>{bar_rows(rsec, len(js), CAT_LABEL.get, lambda k: f"/jobs/{k}/", 14)}</section></div>'
             f'<h2>Neueste Stellen in {e(r)}</h2>{job_table(js, limit=100)}{cta("Rollen in " + r)}',
             crumbs=[("Regionen", "/regionen/"), (r, None)])
    page("/regionen/", fit_title("Jobs nach Bundesland und Kanton: offene Stellen in DACH"),
         "Offene Stellen nach Bundesland (Deutschland, Österreich) und Kanton (Schweiz), direkt von den Karriereseiten der Arbeitgeber. Wöchentlich aktualisiert.",
         '<h1>Offene Stellen nach Bundesland und Kanton</h1><p class="lead">Gezählt werden Stellen mit erkennbarer Stadt. Stadtstaaten und Regionen mit einer dominierenden Stadt verlinken direkt auf die Stadtseite.</p>'
         + "".join(f'<h2>{COUNTRY_NAME[cc]}</h2><ul class="cols">{"".join(reg_links[cc])}</ul>' for cc in ("DE", "AT", "CH") if reg_links[cc]),
         crumbs=[("Regionen", None)])

    # ---- Ausbildung / Werkstudent hubs
    for track, label, plural, intro in (
        ("ausbildung", "Ausbildung", "Ausbildungsplätze", "Ausbildungsplätze und duale Studiengänge"),
        ("werkstudent", "Werkstudent", "Werkstudenten-Jobs & Praktika", "Werkstudentenstellen, Praktika und Abschlussarbeiten"),
    ):
        tj = [j for j in jobs if j["track"] == track]
        if not tj:
            continue
        tcity = Counter(c for j in tj for c in j["cities"])
        tcomp = Counter(j["company"] for j in tj)
        tcat = Counter(j["cat"] for j in tj)
        chips = []
        for city, cnt in tcity.most_common():
            if cnt < MIN_COMBO_JOBS:
                continue
            chips.append(f'<a class="chip" href="/{track}/{city_slug[city]}/">{e(city)} ({cnt})</a>')
            cj = [j for j in tj if city in j["cities"]]
            ccomp = Counter(j["company"] for j in cj)
            t_title = (f"Ausbildung {city}: {n(cnt)} freie Ausbildungsplätze", f"Ausbildung {city}: {n(cnt)} Plätze") if track == "ausbildung" else \
                      (f"Werkstudent Jobs {city}: {n(cnt)} offene Stellen", f"Werkstudent {city}: {n(cnt)} Stellen")
            page(f"/{track}/{city_slug[city]}/", fit_title(f"{t_title[0]} ({mon})", *t_title),
                 f"{n(cnt)} {intro} in {city} bei {n(len(ccomp))} Arbeitgebern, direkt von den Karriereseiten. Stand {fmt_date(date)}, wöchentlich aktualisiert.",
                 f'<h1>{e(plural)} in {e(city)}</h1><p class="lead">{n(cnt)} {e(intro)} bei {n(len(ccomp))} Arbeitgebern in {e(city)}, Stand {fmt_date(date)}. '
                 f'Die meisten bietet {e(names[ccomp.most_common(1)[0][0]])} ({ccomp.most_common(1)[0][1]}).{new_note(cj)}</p>'
                 f'<div class="grid2"><section><h2>Arbeitgeber</h2>{bar_rows(ccomp, cnt, names.get, co_link, 15)}</section>'
                 f'<section><h2>Bereiche</h2>{bar_rows(Counter(j["cat"] for j in cj), cnt, CAT_LABEL.get, None, 10)}</section></div>'
                 f'<h2>Alle Stellen</h2>{job_table(cj)}',
                 crumbs=[(label, f"/{track}/"), (city, None)])
        page(f"/{track}/", fit_title(f"{plural}: {n(len(tj))} offene Stellen in DACH ({mon})", f"{plural}: {n(len(tj))} offene Stellen", f"{label}: {n(len(tj))} offene Stellen"),
             f"{n(len(tj))} {intro} bei {n(len(tcomp))} Arbeitgebern in Deutschland, Österreich und der Schweiz. Nach Stadt und Bereich, direkt von den Karriereseiten.",
             f'<h1>{e(plural)} in DACH</h1><p class="lead">{n(len(tj))} {e(intro)} bei {n(len(tcomp))} Arbeitgebern, Stand {fmt_date(date)}. '
             f'Häufigster Bereich: {e(CAT_LABEL[tcat.most_common(1)[0][0]])}. Städte mit den meisten Angeboten: {", ".join(e(c) for c, _ in tcity.most_common(3))}.</p>'
             f'<div class="chips">{"".join(chips)}</div><div class="grid2"><section><h2>Arbeitgeber</h2>{bar_rows(tcomp, len(tj), names.get, co_link, 15)}</section>'
             f'<section><h2>Bereiche</h2>{bar_rows(tcat, len(tj), CAT_LABEL.get, None, 12)}</section></div>'
             f'<h2>Neueste Angebote</h2>{job_table(tj, limit=100)}',
             crumbs=[(label, None)])

    # ---- ATS
    ats_links = []
    total_cos = len(by_company)
    for a, cos in sorted(ats_companies.items(), key=lambda kv: -len(kv[1])):
        lbl = ATS_LABEL.get(a, a)
        ats_links.append(f'<li><a href="/ats/{a}/">{e(lbl)}</a> <span class="muted">{n(len(cos))} Arbeitgeber</span></li>')
        ats_jobs = sum(len(by_company[c]) for c in cos)
        lis = "".join(f'<li>{"<a href=" + chr(34) + "/unternehmen/" + c + "/" + chr(34) + ">" + e(names[c]) + "</a>" if c in PAGE_COS else e(names[c])} <span class="muted">{n(len(by_company[c]))} Stellen</span></li>' for c in sorted(cos, key=lambda c: names[c].lower()))
        page(f"/ats/{a}/", fit_title(f"Wer nutzt {lbl}? {n(len(cos))} Arbeitgeber in DACH", f"{lbl}: {n(len(cos))} Arbeitgeber in DACH"),
             f"{n(len(cos))} Arbeitgeber in Deutschland, Österreich und der Schweiz nutzen {lbl} als Bewerbermanagementsystem (ATS). Liste mit offenen Stellen.",
             f'<h1>Arbeitgeber, die {e(lbl)} nutzen</h1><p class="lead">{n(len(cos))} von {n(total_cos)} Arbeitgebern im Index ({100 * len(cos) / total_cos:.0f} %) veröffentlichen ihre Stellen über {e(lbl)}, zusammen {n(ats_jobs)} offene Stellen '
             f'(im Schnitt {ats_jobs / len(cos):.0f} pro Arbeitgeber). Die Liste zeigt alle Arbeitgeber mit aktuell offenen Stellen.</p><ul class="cols">{lis}</ul>'
             f'<p class="muted">Für Entwickler: <a href="https://github.com/goldfoot/career-site-jobs-api">So liest man {e(lbl)}-Stellen per API aus</a>.</p>',
             crumbs=[("ATS", "/ats/"), (lbl, None)])
    page("/ats/", fit_title("Bewerbermanagementsysteme (ATS) in DACH: Marktanteile"),
         "Welche ATS nutzen Arbeitgeber in DACH? softgarden, Personio, SmartRecruiters, Greenhouse und mehr, gezählt aus Karriereseiten.",
         f'<h1>Welches Bewerbermanagementsystem nutzen Arbeitgeber in DACH?</h1><p class="lead">Gezählt über {n(total_cos)} Arbeitgeber mit offenen Stellen, Stand {fmt_date(date)}. '
         f'Workday, SAP SuccessFactors und andere Systeme ohne offenen Stellen-Feed sind nicht enthalten, deshalb fehlen viele Großkonzerne.</p>'
         f'{bar_rows(Counter({a: len(c) for a, c in ats_companies.items()}), total_cos, lambda a: ATS_LABEL.get(a, a), lambda a: f"/ats/{a}/", 20)}<ul class="cols">{"".join(ats_links)}</ul>',
         crumbs=[("ATS", None)])

    analysen_pages()
    daten_pages(jobs, by_company, names, date)
    static_pages()
    (DIST / "404.html").write_text((DIST / "index.html").read_text().replace("<title>", "<title>Seite nicht gefunden · ", 1)
                                   .replace('<main class="wrap">', '<main class="wrap"><h1>Diese Seite gibt es nicht (mehr)</h1><p class="lead">Vielleicht ist die Stelle besetzt oder das Unternehmen sucht gerade niemanden. Hier die aktuelle Übersicht:</p>', 1)
                                   .replace('<link rel="canonical"', '<meta name="robots" content="noindex"><link rel="canonical"', 1))
    if CFG.get("indexNowKey"):
        (DIST / f'{CFG["indexNowKey"]}.txt').write_text(CFG["indexNowKey"])
    (DIST / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                                      + "".join(f"<url><loc>{u}</loc><lastmod>{date}</lastmod></url>" for u in SITEMAP) + "</urlset>\n")
    (DIST / "robots.txt").write_text(("User-agent: *\nDisallow: /\n" if CFG.get("noindex") else "User-agent: *\nAllow: /\n") + f"Sitemap: {BASE}/sitemap.xml\n")
    if CFG.get("cname"):
        (DIST / "CNAME").write_text(CFG["cname"] + "\n")
    (DIST / ".nojekyll").write_text("")
    print(f"built {len(SITEMAP)} pages · {n(len(jobs))} jobs · {n(len(tech))} tech · {len(by_company)} companies ({len(PAGE_COS)} with page)")


def company_page(c, js, prev, city_slug, cities_with_page=()):
    name = js[0]["companyName"]
    t = [j for j in js if j["cat"] in TECH]
    cats = Counter(j["cat"] for j in js)
    cities = Counter(ci for j in js for ci in j["cities"])
    remote = sum(j["remote"] for j in js)
    ats = ATS_LABEL.get(js[0]["ats"], js[0]["ats"] or "unbekannt")
    newest = max((j["postedAt"] for j in js if j["postedAt"]), default=None)
    prev_n = sum(1 for j in prev if j["company"] == c) if prev else None
    sal = salary_summary(js)
    city_link = lambda k: f'<a href="/staedte/{city_slug[k]}/">{e(k)}</a>' if k in cities_with_page else e(k)  # noqa: E731
    facts = [f"{e(name)} hat aktuell <b>{n(len(js))} offene Stellen</b> in DACH {delta(len(js), prev_n)}" + (f", davon {n(len(t))} im Tech-Bereich." if t else ".")]
    trainee = sum(1 for j in js if j.get("track"))
    if cats:
        top = ", ".join(f"{e(CAT_LABEL[k])} ({v})" for k, v in cats.most_common(3))
        facts.append(f"Die meisten Stellen entfallen auf {top}.")
    if cities:
        facts.append("Standorte: " + ", ".join(f"{city_link(k)} ({v})" for k, v in cities.most_common(5)) + ".")
    if trainee:
        facts.append(f"Ausbildung, Werkstudent oder Praktikum: {n(trainee)} Angebote.")
    facts.append(f"Remote ausgeschrieben: {n(remote)} Stellen ({100 * remote / len(js):.0f} %).")
    if sal:
        facts.append(f"{n(sal[0])} Stellen nennen ein Gehalt (Median-Spanne {n(sal[1])} – {n(sal[2])} pro Jahr).")
    if new_note(js):
        facts.append(new_note(js).strip())
    facts.append(f'Bewerbermanagement: <a href="/ats/{js[0]["ats"]}/">{e(ats)}</a>. Neueste Ausschreibung: {fmt_date(newest)}.')
    mon = STATS["month"]
    top_city = cities.most_common(1)[0][0] if cities else None
    # Long names: keep start and end (branches of one organisation often differ only at the end).
    title = None
    for tn in ([name] if len(name) <= 40 else [f"{name[:22].rstrip()}…{name[-16:].lstrip()}", f"{name[:40].rstrip()}…"]):
        title = fit_title(f"{tn} Jobs: {n(len(js))} offene Stellen ({mon})", f"{tn} Jobs: {n(len(js))} offene Stellen", f"{tn} Jobs: {n(len(js))} Stellen")
        if title not in USED_TITLES:
            break
    USED_TITLES.add(title)
    page(f"/unternehmen/{c}/", title,
         f"Stellt {name} ein? {n(len(js))} offene Stellen" + (f", vor allem in {top_city}" if top_city else "") + f": {', '.join(CAT_LABEL[k] for k, _ in cats.most_common(2))}. Direkt von der Karriereseite, wöchentlich aktualisiert.",
         f'<h1>Stellt {e(name)} ein?</h1><p class="lead">{" ".join(facts)}</p>'
         f'<div class="grid2"><section><h2>Bereiche</h2>{bar_rows(cats, len(js), CAT_LABEL.get, lambda k: f"/jobs/{k}/")}</section>'
         f'<section><h2>Standorte</h2>{bar_rows(cities, len(js), str, lambda k: f"/staedte/{city_slug[k]}/" if k in cities_with_page else None, 8) if cities else "<p class=muted>Keine Stadt angegeben.</p>"}</section></div>'
         f'<h2>Alle offenen Stellen bei {e(name)}</h2>{job_table(js, show_company=False)}{cta()}',
         crumbs=[("Unternehmen", "/unternehmen/"), (name, None)],
         jsonld=[{"@context": "https://schema.org", "@type": "Organization", "name": name, **({"url": "https://" + js[0]["domain"]} if js[0].get("domain") and "." in js[0]["domain"] and "/" not in js[0]["domain"] and ":" not in js[0]["domain"] else {})}])


def md_to_html(md):
    """Minimal Markdown for AI-written articles: ## headings, paragraphs, - lists, **bold**, *italic*, [text](/internal/ or https://) links. Everything else escaped."""
    def inline(t):
        t = e(t, quote=False)
        t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
        t = re.sub(r"(?<![*\w])\*(?!\s)(.+?)(?<!\s)\*(?![*\w])", r"<i>\1</i>", t)
        return re.sub(r"\[([^\]]+)\]\(((?:/|https://)[^)\s\"]*)\)", r'<a href="\2">\1</a>', t)
    out, para, items = [], [], []
    def flush():
        if para:
            out.append(f"<p>{inline(' '.join(para))}</p>"); para.clear()
        if items:
            out.append("<ul>" + "".join(f"<li>{inline(i)}</li>" for i in items) + "</ul>"); items.clear()
    for line in md.splitlines():
        s_ = line.strip()
        if not s_:
            flush()
        elif s_.startswith("#"):
            flush(); lvl = min(max(len(s_) - len(s_.lstrip("#")), 2), 3)
            out.append(f"<h{lvl}>{inline(s_.lstrip('#').strip())}</h{lvl}>")
        elif re.match(r"[-*] ", s_):
            if para:
                flush()
            items.append(s_[2:])
        else:
            if items:
                flush()
            para.append(s_)
    flush()
    return "\n".join(out)


def daten_pages(jobs, by_company, names, date):
    """Free open-data download (CC BY 4.0): aggregates only. Deliberately NOT included (paid products): job-level data,
    per-company breakdowns by sector/region, per-company 'new this week'."""
    import csv, io
    out = DIST / "daten"
    out.mkdir(parents=True, exist_ok=True)
    y, w, _ = dt.date.fromisoformat(date).isocalendar()
    wk = f"{y}-KW{w:02d}"

    def write(name, header, rows):
        b = io.StringIO()
        c = csv.writer(b, delimiter=";")
        c.writerow(header)
        c.writerows(rows)
        data = "\ufeff" + b.getvalue()  # BOM so Excel opens umlauts correctly
        (out / f"{name}.csv").write_text(data)

    cs = Counter((c, j["cat"]) for j in jobs for c in j["cities"])
    city_total = Counter(c for j in jobs for c in j["cities"])
    rows = sorted(((c, CITY_COUNTRY.get(c, ""), CAT_LABEL[k], v) for (c, k), v in cs.items() if city_total[c] >= MIN_COMBO_JOBS),
                  key=lambda r: (-city_total[r[0]], r[0], -r[3]))
    write("stellen-nach-stadt-und-bereich", ["stadt", "land", "bereich", "offene_stellen"], rows)
    sec = Counter(j["cat"] for j in jobs)
    write("stellen-nach-bereich", ["bereich", "offene_stellen", "anteil_prozent", "remote_prozent", "mit_gehaltsangabe_prozent"],
          [(CAT_LABEL[k], v, round(100 * v / len(jobs), 1), round(100 * sum(j["remote"] for j in jobs if j["cat"] == k) / v, 1),
            round(100 * sum(1 for j in jobs if j["cat"] == k and (j.get("salaryMin") or j.get("salaryMax"))) / v, 1)) for k, v in sec.most_common()])
    top = sorted(by_company.items(), key=lambda kv: -len(kv[1]))[:50]
    write("top-50-arbeitgeber", ["rang", "arbeitgeber", "offene_stellen"], [(i + 1, names[c], len(js)) for i, (c, js) in enumerate(top)])
    # weekly time series from the facts files (grows every week)
    series = []
    for f in sorted((DATA / "weekly").glob("*.json")):
        x = json.loads(f.read_text())
        t = x["totals"]
        series.append((x["week"], x["dataDate"], t["jobs"], t["employers"], t["techJobs"], t["salaryPct"], t["remotePct"], t["ausbildung"], t["werkstudentPraktikum"]))
    write("zeitreihe-gesamt", ["woche", "stichtag", "offene_stellen", "arbeitgeber", "tech_stellen", "mit_gehaltsangabe_prozent", "remote_prozent", "ausbildung", "werkstudent_praktikum"], series)
    files = [("stellen-nach-stadt-und-bereich", "Offene Stellen je Stadt und Bereich (Städte ab 5 Stellen)", len(rows)),
             ("stellen-nach-bereich", "Offene Stellen je Bereich mit Remote- und Gehaltsangabe-Anteil", len(sec)),
             ("top-50-arbeitgeber", "Die 50 Arbeitgeber mit den meisten offenen Stellen", len(top)),
             ("zeitreihe-gesamt", "Wöchentliche Kennzahlen seit Start des Index", len(series))]
    # upsell: what the totals don't show (number of companies per city × sector, without naming them)
    cos = defaultdict(set)
    week_ago = (dt.date.fromisoformat(date) - dt.timedelta(days=7)).isoformat()
    new_cos = defaultdict(set)
    for j in jobs:
        for c in j["cities"]:
            cos[(c, j["cat"])].add(j["company"])
            if (j.get("firstSeen") or j["postedAt"] or "") >= week_ago:
                new_cos[(c, j["cat"])].add(j["company"])
    picks = [k for k, _ in sorted(((k, len(v)) for k, v in cos.items() if k[1] not in ("operations",)), key=lambda x: -x[1])][:4]
    teaser = "".join(f"<li><b>{n(len(cos[k]))} Arbeitgeber</b> in {e(k[0])} suchen gerade Leute für <b>{e(CAT_LABEL[k[1]])}</b>"
                     + (f", {n(len(new_cos[k]))} davon mit neuen Stellen in den letzten 7 Tagen" if 0 < len(new_cos[k]) < len(cos[k]) else "") + ".</li>" for k in picks)
    import urllib.parse as up
    mail = CFG["contactHref"] + "?" + up.urlencode({"subject": "Kostenlose Beispiel-Liste Hiring-Signale",
        "body": "Hallo,\n\nich hätte gern eine kostenlose Beispiel-Liste.\n\nGesuchte Rollen (z. B. DevOps, Vertrieb, Pflege):\nRegion:\nWofür (z. B. Vertrieb, Recruiting, Marktanalyse):\n\nViele Grüße"}, quote_via=up.quote)
    upsell = f"""<div class="cta"><h2>Was die Summen nicht zeigen: welche Unternehmen</h2>
<p>Die Downloads zeigen, wie viel gesucht wird. Für Vertrieb, Recruiting und Personaldienstleister zählt, <b>wer</b> gerade sucht. Zum Beispiel diese Woche:</p><ul>{teaser}</ul>
<p>Welche Unternehmen das sind, mit Link zu jeder Stelle und gefiltert auf Ihre Zielrollen und Regionen, liefern wir jeden Montag als <a href="/hiring-signale/">Hiring-Signale</a>-Liste (CSV/Excel).</p>
<p><a class="btn" href="{e(mail)}">Kostenlose Beispiel-Liste anfordern</a></p>
<p class="muted">Selbst abfragen: einzelne Stellen mit Filtern und „nur neue Stellen“-Modus über die <a href="{CFG.get("indexActorUrl", CFG["actorUrl"])}">DACH Jobs API</a> (Abrechnung pro Stelle).</p></div>"""
    lis = "".join(f'<tr><td><a href="/daten/{f}.csv" download>{f}.csv</a></td><td>{e(d)}</td><td class="r">{n(k)}</td></tr>' for f, d, k in files)
    body = f"""<h1>Arbeitsmarktdaten zum Download</h1>
<p class="lead">Kostenlose Wochendaten zum Stellenmarkt in Deutschland, Österreich und der Schweiz: offene Stellen je Stadt, Bereich und Arbeitgeber, ausgezählt aus den Karriereseiten von {n(len(by_company))} Arbeitgebern. Stand {fmt_date(date)} ({wk}).</p>
<div class="tw"><table class="rank"><thead><tr><th>Datei (CSV, Semikolon, UTF-8)</th><th>Inhalt</th><th class="r">Zeilen</th></tr></thead><tbody>{lis}</tbody></table></div>
<p class="muted">Die Dateien werden jeden Montag aktualisiert. Die Entwicklung über die Wochen steht in <code>zeitreihe-gesamt.csv</code>.</p>
<h2>Lizenz und Zitierweise</h2>
<p>Die Daten stehen unter <a href="https://creativecommons.org/licenses/by/4.0/deed.de">CC BY 4.0</a>: Sie dürfen sie frei nutzen, auch kommerziell, wenn Sie die Quelle nennen. Bitte so: <b>„Quelle: wer-stellt-ein.de, Stand {fmt_date(date)}“</b> mit Link auf <a href="/">wer-stellt-ein.de</a>.</p>
<h2>Was die Zahlen bedeuten</h2>
<ul><li>Gezählt werden offene Stellen, die Arbeitgeber über ihre Bewerbermanagementsysteme veröffentlichen (u. a. softgarden, Personio, SmartRecruiters). Arbeitgeber mit Workday oder SAP SuccessFactors fehlen, darunter viele Konzerne.</li>
<li>Eine Stelle mit mehreren Standorten zählt in jeder Stadt. Bereiche werden automatisch am Stellentitel erkannt. Details: <a href="/methodik/">Methodik</a>.</li></ul>
{upsell}"""
    page("/daten/", fit_title("Arbeitsmarktdaten DACH: offene Stellen als CSV-Download"),
         f"Kostenlose Wochendaten: offene Stellen je Stadt, Bereich und Arbeitgeber in Deutschland, Österreich und der Schweiz als CSV (CC BY 4.0). Stand {fmt_date(date)}.",
         body, crumbs=[("Daten-Download", None)],
         jsonld=[{"@context": "https://schema.org", "@type": "Dataset", "name": "Offene Stellen in DACH nach Stadt, Bereich und Arbeitgeber",
                  "description": "Wöchentliche Zählung offener Stellen aus öffentlichen Karriereseiten von Arbeitgebern in Deutschland, Österreich und der Schweiz.",
                  "url": BASE + "/daten/", "license": "https://creativecommons.org/licenses/by/4.0/", "isAccessibleForFree": True,
                  "dateModified": date, "temporalCoverage": f"{series[0][1] if series else date}/{date}", "spatialCoverage": "Deutschland, Österreich, Schweiz",
                  "creator": {"@type": "Organization", "name": CFG["brand"], "url": BASE + "/"},
                  "distribution": [{"@type": "DataDownload", "encodingFormat": "text/csv", "contentUrl": f"{BASE}/daten/{f}.csv", "name": d} for f, d, _ in files]}])


def latest_article_teaser():
    files = sorted((ROOT / "content" / "analysen").glob("*.json"))
    if not files:
        return ""
    a = json.loads(files[-1].read_text())
    y, w = a["week"].split("-W")
    return (f'<section class="teaser"><p class="muted">Analyse der Woche</p><h2><a href="/analysen/kw-{int(w)}-{y}/">{e(a["title"])}</a></h2>'
            f'<p>{e(a["description"])} <a href="/analysen/">Alle Analysen →</a></p></section>')


def analysen_pages():
    """Weekly AI-written market analyses from content/analysen/*.json (see write_article.py)."""
    arts = sorted((json.loads(p.read_text()) for p in (ROOT / "content" / "analysen").glob("*.json")), key=lambda a: a["week"], reverse=True)
    disclosure = ('<p class="muted ai-note">Dieser Text wurde automatisch mit KI (Claude) aus den Indexdaten der Woche erstellt. '
                  'Alle Zahlen werden vor der Veröffentlichung maschinell gegen die Daten geprüft. <a href="/methodik/">Methodik</a></p>')
    for i, a in enumerate(arts):
        y, w = a["week"].split("-W")
        slug = f"/analysen/kw-{int(w)}-{y}/"
        nav = []
        if i + 1 < len(arts):
            o = arts[i + 1]; ow = o["week"].split("-W")
            nav.append(f'<a href="/analysen/kw-{int(ow[1])}-{ow[0]}/">← KW {int(ow[1])}</a>')
        if i > 0:
            o = arts[i - 1]; ow = o["week"].split("-W")
            nav.append(f'<a href="/analysen/kw-{int(ow[1])}-{ow[0]}/">KW {int(ow[1])} →</a>')
        body = (f'<article class="prose"><p class="muted">Arbeitsmarkt-Analyse KW {int(w)}/{y} · Datenstand {fmt_date(a["dataDate"])}</p>'
                f'<h1>{e(a["title"])}</h1>{md_to_html(a["body"])}{disclosure}'
                f'<p class="pager">{" · ".join(nav)}</p></article>{cta()}')
        page(slug, a["title"], a["description"], body, crumbs=[("Analysen", "/analysen/"), (f"KW {int(w)}/{y}", None)],
             jsonld=[{"@context": "https://schema.org", "@type": "Article", "headline": a["title"], "description": a["description"],
                      "datePublished": a["dataDate"], "dateModified": a["dataDate"], "inLanguage": "de",
                      "author": {"@type": "Organization", "name": CFG["brand"]}, "publisher": {"@type": "Organization", "name": CFG["brand"]},
                      "mainEntityOfPage": BASE + slug}])
    lis = "".join(f'<li><a href="/analysen/kw-{int(a["week"].split("-W")[1])}-{a["week"][:4]}/">{e(a["title"])}</a><br><span class="muted">{e(a["description"])}</span></li>' for a in arts)
    page("/analysen/", fit_title("Arbeitsmarkt-Analysen DACH: wöchentlich aus Karriereseiten"),
         "Jede Woche eine Analyse des DACH-Stellenmarkts: welche Bereiche, Städte und Arbeitgeber gerade einstellen, wie viele Gehalt und Remote anbieten.",
         f'<h1>Arbeitsmarkt-Analysen</h1><p class="lead">Jeden Montag werten wir die offenen Stellen von {n(STATS["companies"])} Arbeitgebern in Deutschland, Österreich und der Schweiz aus: '
         f'Welche Bereiche wachsen, welche Städte und Arbeitgeber suchen am meisten, wie viele Stellen nennen ein Gehalt oder sind remote. Die Texte werden automatisch mit KI aus den Daten erstellt; jede Zahl wird gegen den Index geprüft.</p>'
         + (f'<ul class="articles">{lis}</ul>' if arts else '<p class="muted">Die erste Analyse erscheint am Montag.</p>'),
         crumbs=[("Analysen", None)])
    LATEST_ARTICLE[0] = arts[0] if arts else None


LATEST_ARTICLE = [None]


def static_pages():
    md = lambda s: s  # noqa: E731  (content is trusted, authored here)
    page("/methodik/", "Methodik: so entsteht der Stellenindex", "Datenquellen, Zählweise und Grenzen des wöchentlichen DACH-Stellenindex von wer-stellt-ein.de.", md(f"""
<h1>Methodik</h1>
<p>Der Index liest einmal pro Woche die <b>öffentlichen Stellen-Feeds</b> der Karriereseiten von {n(STATS["companies"])} Arbeitgebern aus (softgarden, Personio, SmartRecruiters, Recruitee, Greenhouse, Ashby, Teamtailor, Lever). Das sind dieselben Daten, die die Arbeitgeber selbst auf ihrer Website anzeigen. Gruppen-Karriereportale, die dieselbe Stelle mehrfach veröffentlichen, werden zusammengeführt.</p>
<ul><li><b>Nur DACH:</b> gezählt werden Stellen mit Standort in Deutschland, Österreich oder der Schweiz sowie Remote-Stellen, die DACH oder Europa einschließen.</li>
<li><b>Bereiche</b> werden automatisch anhand des Stellentitels zugeordnet (z. B. „Site Reliability Engineer“ → DevOps, SRE &amp; Platform). Einzelne Zuordnungen können falsch sein.</li>
<li><b>Tech-Stellen</b> = Engineering, DevOps, Data/KI, Security, Mobile, QA, Produkt, Design, IT, Hardware/Embedded.</li>
<li><b>Ausbildung</b> und <b>Werkstudent/Praktikum</b> werden ebenfalls am Stellentitel erkannt.</li>
<li>Eigene Seiten gibt es für Arbeitgeber ab {MIN_COMPANY_JOBS} Stellen sowie für Städte und Kombinationen ab {MIN_COMBO_JOBS} Stellen.</li>
<li><b>Δ Woche</b> vergleicht mit dem Stand der Vorwoche.</li>
<li>Unternehmen, deren Karriereseite über Workday, SuccessFactors o. ä. läuft, sind (noch) nicht enthalten.</li></ul>
<p>Es werden keine Bewerberdaten oder personenbezogenen Daten erhoben. Jede Stelle verlinkt auf die Originalausschreibung.</p>
<p>Die Daten stammen aus dem <a href="{CFG["actorUrl"]}">Career Site Jobs Scraper</a>. Den kompletten, wöchentlich aktualisierten DACH-Stellenindex (alle Branchen, mit Filtern für Stadt, Bereich, Remote und Gehalt) gibt es als <a href="{CFG.get("indexActorUrl", CFG["actorUrl"])}">DACH Jobs API</a>. Entwickler finden Beispiele unter <a href="https://github.com/goldfoot/career-site-jobs-api">github.com/goldfoot/career-site-jobs-api</a>.</p>
<p>Fehlt ein Unternehmen? <a href="{CFG["contactHref"]}">Schreiben Sie uns</a>.</p>"""), crumbs=[("Methodik", None)])
    page("/hiring-signale/", "Hiring-Signale: wöchentliche Lead-Liste für B2B-Vertrieb", "Welche Unternehmen in Ihrer Zielgruppe stellen gerade passende Rollen ein? Wöchentliche Liste als CSV.", md(f"""
<h1>Hiring-Signale für Ihren Vertrieb</h1>
<p class="lead">Ein Unternehmen, das drei DevOps-Engineers sucht, hat ein Infrastruktur-Thema. Eines, das einen „Head of Data“ sucht, baut gerade sein Datenteam auf. Für Dienstleister, Agenturen, Freelancer und SaaS-Anbieter sind das die besten Zeitpunkte für eine Kontaktaufnahme.</p>
<h2>Was Sie bekommen</h2>
<ul><li>Jeden Montag eine CSV/Excel-Liste: Unternehmen, neue passende Stellen, Standorte, Link zur Ausschreibung.</li>
<li>Gefiltert auf Ihre Rollen (z. B. DevOps, Data, Security, SAP, Salesforce) und Regionen.</li>
<li>Nur Unternehmensdaten, keine personenbezogenen Kontaktdaten.</li></ul>
<h2>Selbst machen</h2>
<p>Technisch versiert? Die <a href="{CFG.get("indexActorUrl", CFG["actorUrl"])}">DACH Jobs API</a> durchsucht alle Stellen per Stichwort, Stadt, Bereich und Seniorität, mit „nur neue Stellen“-Modus für wöchentliche Alerts. Einzelne Unternehmen live abfragen: <a href="{CFG["actorUrl"]}">Career Site Jobs Scraper</a>. Abrechnung pro gefundener Stelle.</p>
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
    data_date = None
    if (DATA / "index-latest.json").exists() and "--legacy" not in sys.argv:
        jobs, data_date = load_index_jobs()
    else:
        jobs = load_jobs()
    if "--snapshot" in sys.argv:
        write_snapshot(jobs, data_date or TODAY.isoformat())
    build(jobs, load_snapshots(), data_date)
    if "--relative" in sys.argv:
        relativize()
