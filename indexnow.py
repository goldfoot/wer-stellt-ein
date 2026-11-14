#!/usr/bin/env python3
"""After deploy: submit all sitemap URLs to IndexNow (Bing, Yandex, Seznam, Naver). Key file is written by build.py."""
import json, re, urllib.request
from pathlib import Path

cfg = json.loads((Path(__file__).parent / "site.json").read_text())
site, key = cfg["baseUrl"].rstrip("/"), cfg.get("indexNowKey")
if not key:
    raise SystemExit("no indexNowKey in site.json")
urls = re.findall(r"<loc>([^<]+)</loc>", urllib.request.urlopen(f"{site}/sitemap.xml", timeout=60).read().decode())
body = json.dumps({"host": site.split("//")[1], "key": key, "keyLocation": f"{site}/{key}.txt", "urlList": urls[:10000]}).encode()
req = urllib.request.Request("https://api.indexnow.org/indexnow", data=body, headers={"Content-Type": "application/json; charset=utf-8"})
with urllib.request.urlopen(req, timeout=60) as r:
    print("IndexNow", r.status, len(urls), "urls")
