#!/usr/bin/env python3
"""Generate index.json: the catalog's machine-readable index plus per-template
version history (#682).

    faucet hub matrix --hub . --format json     → sources, sinks, matrix (owner, official, id)
    git log (main)                              → versions: v1, v2, v3 … per template
    <stem>.faucet.yaml sidecar                  → which version is `stable`

A version is one accepted change to a template's *meaning*: commits that only
touch comments or whitespace are folded into the previous version (the same
normalisation faucet's sync planner uses). Authors never write a version
number.
"""
import hashlib
import json
import os
import re
import subprocess
import sys

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)


def run(*args, check=True):
    return subprocess.run(args, check=check, capture_output=True, text=True).stdout


def canonical_hash(text):
    """sha256 of the parsed document re-emitted canonically (comments/whitespace ignored)."""
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError:
        return hashlib.sha256(text.encode()).hexdigest()
    return hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def versions_for(path):
    """Oldest-first list of {version, commit, date, pr} — one per body change."""
    log = run("git", "log", "--reverse", "--format=%H%x1f%cI%x1f%s", "--", path).strip()
    out, last = [], None
    for line in filter(None, log.split("\n")):
        sha, date, subject = line.split("\x1f", 2)
        body = run("git", "show", f"{sha}:{path}", check=False)
        if not body:
            continue  # deleted in this commit
        h = canonical_hash(body)
        if h == last:
            continue
        last = h
        pr = re.search(r"\(#(\d+)\)\s*$", subject)
        out.append({
            "version": len(out) + 1,
            "commit": sha,
            "date": date,
            "pr": int(pr.group(1)) if pr else None,
        })
    return out


def sidecar_for(path):
    stem, _ = os.path.splitext(path)
    for ext in (".faucet.yaml", ".faucet.yml", ".faucet.json"):
        p = stem + ext
        if os.path.isfile(p):
            with open(p) as f:
                return yaml.safe_load(f) or {}
    return {}


def stable_for(versions, sidecar):
    newest = len(versions)
    if not newest:
        return None
    explicit = sidecar.get("stable")
    if isinstance(explicit, int) and 1 <= explicit <= newest:
        return explicit
    if sidecar.get("launch") is False:
        return max(1, newest - 1)
    return newest


def enrich(entries):
    for e in entries:
        path = e.get("file")
        if not path or not os.path.isfile(path):
            continue
        vs = versions_for(path)
        e["versions"] = vs
        e["newest"] = len(vs) or None
        e["stable"] = stable_for(vs, sidecar_for(path))


def main():
    base = json.loads(run("faucet", "hub", "matrix", "--hub", ".", "--format", "json"))
    enrich(base.get("sources", []))
    enrich(base.get("sinks", []))
    base["commit"] = run("git", "rev-parse", "HEAD").strip()
    base["generated_by"] = "scripts/index.py"
    out = json.dumps(base, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    target = sys.argv[1] if len(sys.argv) > 1 else "index.json"
    with open(target, "w") as f:
        f.write(out)
    print(f"wrote {target}: {len(base.get('sources', []))} sources, {len(base.get('sinks', []))} sinks @ {base['commit'][:7]}")


if __name__ == "__main__":
    main()
