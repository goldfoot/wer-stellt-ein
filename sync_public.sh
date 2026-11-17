#!/bin/sh
# Sync sites/hiring-index → public repo goldfoot/wer-stellt-ein (noreply author). Run from sites/hiring-index.
# Code only: snapshots, weekly facts and articles are written in the public repo (CI + "articles auto") and never synced from here.
set -e
S=$(mktemp -d)
git clone -q git@github.com:goldfoot/wer-stellt-ein.git "$S/repo"
rsync -a --delete --exclude data/snapshots --exclude data/weekly --exclude content/analysen --exclude .git --exclude dist --exclude data/jobs-latest.json --exclude __pycache__ ./ "$S/repo/"
cd "$S/repo"
git add -A
if git diff --cached --quiet; then echo "no changes"; else
  git -c user.name=goldfoot -c user.email="6959808+goldfoot@users.noreply.github.com" commit -qm "${1:-Update generator/data}"
  git push -q && echo pushed
fi
rm -rf "$S"
