#!/usr/bin/env python3
"""Create/update Apify task `hiring-index-weekly` (resolved boards → fast run) + schedule Mondays 05:00 Europe/Berlin. Idempotent.
NEEDS OWNER APPROVAL before first run (recurring compute; est. a few cents per week within the Creator plan's included usage).
Run from repo root: python3 sites/hiring-index/setup_apify.py"""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import build  # noqa: E402  (reuse DACH city list for the location filter)

API = 'tools/apify-api.sh'


def api(method, path, body=None):
    out = subprocess.run([API, method, path] + ([json.dumps(body)] if body is not None else []), capture_output=True, text=True, check=True).stdout
    d = json.loads(out) if out.strip() else {}
    if 'error' in d:
        raise SystemExit(f"{method} {path}: {d['error']}")
    return d.get('data', d)


boards = [l.split('#')[0].strip() for l in (Path(__file__).parent / 'data/boards.txt').read_text().splitlines() if l.strip() and not l.startswith('#')]
locs = ['Germany', 'Deutschland', 'Austria', 'Österreich', 'Switzerland', 'Schweiz', 'Remote', 'DACH', 'Europe', 'EMEA'] + \
       sorted(set(build.CITIES) | {'Munich', 'Cologne', 'Vienna', 'Zurich', 'Nuremberg', 'Frankfurt', 'Geneva'})
name = 'hiring-index-weekly'
body = {'actId': 'goldfoot~ats-jobs-feed', 'name': name, 'input': {'companies': sorted(set(boards)), 'locations': locs, 'includeDescription': False},
        'options': {'memoryMbytes': 1024, 'timeoutSecs': 3600}}
tasks = {t['name']: t for t in api('GET', '/v2/actor-tasks?limit=1000')['items']}
t = api('PUT', f"/v2/actor-tasks/{tasks[name]['id']}", {k: v for k, v in body.items() if k != 'actId'}) if name in tasks else api('POST', '/v2/actor-tasks', body)
print('task', t['id'], len(body['input']['companies']), 'boards')
schedules = {s['name']: s for s in api('GET', '/v2/schedules?limit=1000')['items']}
sched = {'name': name, 'cronExpression': '0 5 * * 1', 'timezone': 'Europe/Berlin', 'isEnabled': True, 'isExclusive': True,
         'actions': [{'type': 'RUN_ACTOR_TASK', 'actorTaskId': t['id']}]}
s = api('PUT', f"/v2/schedules/{schedules[name]['id']}", sched) if name in schedules else api('POST', '/v2/schedules', sched)
print('schedule', s['name'], s['cronExpression'], 'next:', s.get('nextRunAt'))
