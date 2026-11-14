#!/usr/bin/env python3
"""AI-written weekly market analysis → content/analysen/<YYYY>-W<ww>.json (rendered by build.py at /analysen/<week>/).

Claude writes the article from data/weekly/<week>.json only. Guardrails before anything is saved:
  - every number in the text must match a value in the facts file (exact, or that value rounded),
  - internal links must point to pages that exist,
  - one retry with the list of problems; if it still fails, nothing is written and the build goes on without a new article.

Needs ANTHROPIC_API_KEY (GitHub secret). Without it the script exits 0 and does nothing.
Usage: python3 write_article.py [--week 2026-W46] [--force]
"""
import argparse
import datetime as dt
import json
import os
import re
import sys

import build as B

MODEL = "claude-opus-5-5"
OUT = B.ROOT / "content" / "analysen"

SYSTEM = """Du bist Datenjournalist für wer-stellt-ein.de, eine Website, die jede Woche offene Stellen direkt von den Karriereseiten von Arbeitgebern in Deutschland, Österreich und der Schweiz zählt.

Du schreibst die wöchentliche Arbeitsmarkt-Analyse auf Deutsch. Leser: Personaler, Vertrieb/Agenturen, Jobsuchende, Journalisten. Ton: sachlich, präzise, gut lesbar, kein Marketing-Sprech, keine Superlative ohne Beleg.

Harte Regeln:
1. Verwende ausschließlich Zahlen, die wörtlich im Fakten-JSON stehen (deutsche Schreibweise erlaubt: 37.260, 10,3 %). Du darfst eine Zahl aus dem JSON runden (z. B. 37.260 → rund 37.000; 10,3 % → rund 10 %), aber keine neuen Zahlen berechnen (keine eigenen Summen, Differenzen, Verhältnisse oder Prozente). Brauchst du einen Vergleich, formuliere ihn qualitativ („fast doppelt so viele“ nur, wenn offensichtlich).
2. Keine Behauptungen über Ursachen als Tatsache. Deutungen klar als Einordnung kennzeichnen („Das deutet darauf hin …“, „Eine mögliche Erklärung …“).
3. Erwähne, wo nötig, die Grenzen der Daten (z. B. nur Arbeitgeber mit unterstützten Bewerbermanagementsystemen; erste Woche ohne Vorwochenvergleich, wenn previousWeek null ist).
4. Nenne Arbeitgeber nur mit Zahlen aus dem JSON, ohne Wertung über das Unternehmen.
5. Verlinke 4–8 passende interne Seiten mit Markdown-Links, ausschließlich aus der Liste ALLOWED_LINKS.
6. Format: Markdown mit 3–5 Zwischenüberschriften (##), kurzen Absätzen, höchstens einer Aufzählungsliste. Keine H1 (der Titel wird separat gesetzt). 600–900 Wörter.
7. Schließe mit einem kurzen Abschnitt „## Methodik“ (2–3 Sätze: Datenquelle, Stichtag dataDate, Hinweis, dass der Text automatisch mit KI aus den Indexdaten erstellt wurde).

Titel: max. 60 Zeichen, enthält die Kalenderwoche (z. B. „KW 46“) und die wichtigste Erkenntnis. Description: max. 155 Zeichen."""

SCHEMA = {"type": "object", "additionalProperties": False, "required": ["title", "description", "body_markdown"],
          "properties": {"title": {"type": "string"}, "description": {"type": "string"}, "body_markdown": {"type": "string"}}}

NUM_RE = re.compile(r"(?<![\w/.-])\d{1,3}(?:\.\d{3})+(?:,\d+)?|(?<![\w/.-])\d+(?:,\d+)?")
LINK_RE = re.compile(r"\]\((/[^)\s]*)\)")


def fact_numbers(obj, acc=None):
    acc = set() if acc is None else acc
    if isinstance(obj, bool):
        return acc
    if isinstance(obj, (int, float)):
        acc.add(float(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            fact_numbers(v, acc)
    elif isinstance(obj, list):
        for v in obj:
            fact_numbers(v, acc)
    elif isinstance(obj, str):
        for m in re.findall(r"\d+(?:\.\d+)?", obj):
            acc.add(float(m))
    return acc


def parse_de(s):
    return float(s.replace(".", "").replace(",", "."))


def allowed_value(x, facts_nums, week):
    if x <= 12 or x in (2025, 2026, 2027) or x == week:
        return True
    for f in facts_nums:
        f = abs(f)
        if x == f:
            return True
        for nd in (0, -1, -2, -3):  # rounding: 10.3→10, 37260→37300/37000/40000
            if round(f, nd) == x:
                return True
        if f >= 10000 and x == round(f / 1000) or f >= 1000 and abs(x * 1000 - f) < 1000 and x < 1000:  # "37 Tsd."
            return True
    return False


def check(article, facts, allowed_links):
    probs = []
    nums = fact_numbers(facts)
    week = int(facts["week"].split("W")[1])
    text = article["title"] + "\n" + article["description"] + "\n" + LINK_RE.sub("]()", article["body_markdown"])
    bad = sorted({m for m in NUM_RE.findall(text) if not allowed_value(parse_de(m), nums, week)})
    if bad:
        probs.append("Zahlen, die nicht im Fakten-JSON stehen (auch nicht gerundet): " + ", ".join(bad))
    links = LINK_RE.findall(article["body_markdown"])
    badl = sorted({lnk for lnk in links if lnk not in allowed_links})
    if badl:
        probs.append("Nicht erlaubte Links: " + ", ".join(badl))
    if len(links) < 3:
        probs.append("Zu wenige interne Links (mindestens 3 aus ALLOWED_LINKS).")
    if len(article["title"]) > 60:
        probs.append(f"Titel zu lang ({len(article['title'])} > 60 Zeichen).")
    if len(article["description"]) > 160:
        probs.append(f"Description zu lang ({len(article['description'])} > 155 Zeichen).")
    words = len(article["body_markdown"].split())
    if not 450 <= words <= 1200:
        probs.append(f"Länge {words} Wörter, Ziel 600–900.")
    if re.search(r"^# ", article["body_markdown"], re.M):
        probs.append("Keine H1 im Text verwenden.")
    return probs


def allowed_links_for(facts):
    links = {"/", "/jobs/", "/staedte/", "/unternehmen/", "/ausbildung/", "/werkstudent/", "/methodik/", "/hiring-signale/", "/analysen/"}
    links |= {f"/jobs/{c['slug']}/" for c in facts["categories"] if c["jobs"] >= B.MIN_COMBO_JOBS}
    links |= {f"/staedte/{B.slugify(c['city'])}/" for c in facts["topCities"]}
    links |= {f"/ausbildung/{B.slugify(c['city'])}/" for c in facts["topCities"][:8]}
    links |= {f"/werkstudent/{B.slugify(c['city'])}/" for c in facts["topCities"][:8]}
    links |= {f"/unternehmen/{B.slugify(e['employer'])}/" for e in facts["topEmployers"] + facts["topTechEmployers"]}
    return links


def generate(facts, allowed_links, feedback=None):
    import anthropic  # only needed in CI

    client = anthropic.Anthropic()
    user = (f"FAKTEN-JSON (einzige erlaubte Datenquelle):\n```json\n{json.dumps(facts, ensure_ascii=False, indent=1)}\n```\n\n"
            f"ALLOWED_LINKS:\n" + "\n".join(sorted(allowed_links)) + "\n\nSchreibe die Analyse für " + facts["week"].replace("-W", ", KW ") + ".")
    messages = [{"role": "user", "content": user}]
    if feedback:
        messages += [{"role": "assistant", "content": json.dumps(feedback["article"], ensure_ascii=False)},
                     {"role": "user", "content": "Bitte korrigieren und vollständig neu ausgeben. Probleme:\n- " + "\n- ".join(feedback["problems"])}]
    resp = client.beta.messages.create(
        model=MODEL, max_tokens=16000, system=SYSTEM, messages=messages,
        output_config={"effort": "high", "format": {"type": "json_schema", "schema": SCHEMA}},
        betas=["server-side-fallback-2026-07-01"], fallbacks="default",
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError(f"refused: {resp.stop_details}")
    if resp.stop_reason == "max_tokens":
        raise RuntimeError("hit max_tokens")
    text = next(b.text for b in resp.content if b.type == "text")
    print(f"  {resp.model}: {resp.usage.input_tokens} in / {resp.usage.output_tokens} out tokens", file=sys.stderr)
    return json.loads(text), resp.model


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--week")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set: skipping article")
        return
    files = sorted((B.DATA / "weekly").glob("*.json"))
    path = B.DATA / "weekly" / f"{a.week}.json" if a.week else files[-1]
    facts = json.loads(path.read_text())
    out = OUT / f"{facts['week']}.json"
    if out.exists() and not a.force:
        print(f"{out.name} exists: skipping")
        return
    links = allowed_links_for(facts)
    feedback = None
    for attempt in (1, 2):
        art, model = generate(facts, links, feedback)
        probs = check(art, facts, links)
        if not probs:
            break
        print(f"  attempt {attempt}: " + " | ".join(probs), file=sys.stderr)
        feedback = {"article": art, "problems": probs}
    else:
        print("article failed the fact check twice: not published", file=sys.stderr)
        sys.exit(1)
    OUT.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"week": facts["week"], "dataDate": facts["dataDate"], "title": art["title"], "description": art["description"],
                               "body": art["body_markdown"], "model": model, "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                               "facts": f"data/weekly/{path.name}"}, ensure_ascii=False, indent=1))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
