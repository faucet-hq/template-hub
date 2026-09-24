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


def _day(iso):
    return iso[:10] if isinstance(iso, str) and len(iso) >= 10 else None


def apply_trust(index, stars):
    """Attach each entry's `trust` block (#685) from its own history, the
    matrix, and stars.json (scripts/stars.py). Pure: index in, index out."""
    recorded = (stars or {}).get("templates", {})
    entries = index.get("sources", []) + index.get("sinks", [])
    per_owner = {}
    for e in entries:
        if e.get("owner"):
            per_owner[e["owner"]] = per_owner.get(e["owner"], 0) + 1
    compatible = {}
    for c in index.get("matrix", []):
        if c.get("compatible"):
            compatible[c.get("source")] = compatible.get(c.get("source"), 0) + 1
    for kind in ("sources", "sinks"):
        for e in index.get(kind, []):
            tid = e.get("id") or e.get("name")
            rec = recorded.get(tid, {})
            t = {}
            for k in ("stars", "star_url", "open_issues"):
                if rec.get(k) is not None:
                    t[k] = rec[k]
            vs = e.get("versions") or []
            if vs:
                t["updated"] = _day(vs[-1].get("date"))
                st = e.get("stable")
                if isinstance(st, int) and 1 <= st <= len(vs):
                    t["stable_since"] = _day(vs[st - 1].get("date"))
            if kind == "sources":
                t["compatible_sinks"] = compatible.get(tid, 0)
            pub = {}
            if e.get("owner"):
                pub["templates"] = per_owner.get(e["owner"], 0)
            if rec.get("publisher_account_age_days") is not None:
                pub["account_age_days"] = rec["publisher_account_age_days"]
            if pub:
                t["publisher"] = pub
            t = {k: v for k, v in t.items() if v is not None}
            if t:
                e["trust"] = t
            else:
                e.pop("trust", None)
    return index


def load_stars(path="stars.json"):
    if not os.path.isfile(path):
        return {}
    with open(path) as f:
        return json.load(f)


def write(index, target):
    out = json.dumps(index, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    with open(target, "w") as f:
        f.write(out)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    target = args[0] if args else "index.json"
    if "--trust-only" in sys.argv:
        # Refresh only the trust blocks of an existing index (the stars job):
        # no faucet binary, no history walk.
        with open(target) as f:
            base = json.load(f)
        write(apply_trust(base, load_stars()), target)
        print(f"refreshed trust in {target}")
        return
    base = json.loads(run("faucet", "hub", "matrix", "--hub", ".", "--format", "json"))
    enrich(base.get("sources", []))
    enrich(base.get("sinks", []))
    apply_trust(base, load_stars())
    base["commit"] = run("git", "rev-parse", "HEAD").strip()
    base["generated_by"] = "scripts/index.py"
    write(base, target)
    print(f"wrote {target}: {len(base.get('sources', []))} sources, {len(base.get('sinks', []))} sinks @ {base['commit'][:7]}")


if __name__ == "__main__":
    main()
