#!/usr/bin/env python3
"""Collect the trust signals the index publishes for every template (#685).

    python3 scripts/stars.py                 # live: GitHub GraphQL, writes stars.json
    python3 scripts/stars.py --fixture F     # offline: read a recorded API snapshot
    python3 scripts/stars.py --dry-run       # print, don't write, never create anything

A star is an upvote (↑) on the template's discussion. Each template gets one
discussion (opened by this script, marked with `<!-- faucet-template: <id> -->`
so the link survives title edits). GitHub counts one upvote per account and
reports only the total, which is the star count. Alongside stars this records open issues
labelled `template:<id>` and each publisher's GitHub account age.

The output, stars.json, is merged into index.json by scripts/index.py.
Needs GITHUB_TOKEN with discussions:write and issues:write (the workflow's).
"""

import argparse
import datetime as dt
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

REPO_OWNER, REPO_NAME = os.environ.get("GITHUB_REPOSITORY", "faucet-hq/template-hub").split("/", 1)
CATEGORY = os.environ.get("STAR_CATEGORY", "Templates")
MARKER = re.compile(r"<!--\s*faucet-template:\s*([A-Za-z0-9_./-]+)\s*-->")
LABEL_PREFIX = "template:"
LABEL_MAX = 50  # GitHub's label-name limit


# ── pure logic (unit-tested in scripts/test_stars.py) ───────────────────────


def marker_id(body):
    m = MARKER.search(body or "")
    return m.group(1) if m else None


def days_between(earlier_iso, now):
    t = dt.datetime.fromisoformat(earlier_iso.replace("Z", "+00:00"))
    return (now - t).days


def stars_from(discussion):
    """A template's stars are its discussion's upvotes. GitHub allows one per
    account and reports only the total; the bot that opens the thread does not
    upvote it."""
    return max(0, discussion.get("upvotes") or 0)


def namespace(template_id):
    return template_id.split("/", 1)[0] if "/" in template_id else None


def label_for(template_id):
    label = LABEL_PREFIX + template_id
    return label if len(label) <= LABEL_MAX else None


def discussion_body(entry, kind):
    tid = entry["id"]
    return (
        f"**{tid}**: {entry.get('description') or 'a ' + kind + ' template'}\n\n"
        f"**Upvote** (↑) this discussion to star the template. Stars help people choose between "
        f"templates for the same system, and appear on the hub page and in `faucet hub list`.\n\n"
        f"Questions and feedback welcome below. Bugs: open an issue labelled `{LABEL_PREFIX}{tid}`.\n\n"
        f"Source: [`{entry.get('file', '')}`](../blob/main/{entry.get('file', '')})\n\n"
        f"<!-- faucet-template: {tid} -->\n"
    )


def collect(index, snapshot, now):
    """Build stars.json from index.json + an API snapshot (live or recorded).

    snapshot = {
      "discussions": {id: {"url": str, "upvotes": int}},
      "open_issues": {id: int},
      "accounts": {login: createdAt},
    }
    """
    out = {}
    for kind in ("sources", "sinks"):
        for e in index.get(kind, []):
            tid = e.get("id") or e.get("name")
            if not tid:
                continue
            d = snapshot.get("discussions", {}).get(tid)
            ns = namespace(tid)
            rec = {}
            if d:
                rec["stars"] = stars_from(d)
                rec["star_url"] = d.get("url")
            if tid in snapshot.get("open_issues", {}):
                rec["open_issues"] = snapshot["open_issues"][tid]
            created = snapshot.get("accounts", {}).get(ns) if ns else None
            if created:
                rec["publisher_account_age_days"] = days_between(created, now)
            out[tid] = rec
    # No timestamp: the file changes only when a signal does, so the hourly
    # job commits only then.
    return {"templates": out}


# ── GitHub I/O ──────────────────────────────────────────────────────────────


def gql(query, **variables):
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        sys.exit("GITHUB_TOKEN is required (or pass --fixture)")
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={"Authorization": f"bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        payload = json.load(r)
    if payload.get("errors"):
        raise RuntimeError(json.dumps(payload["errors"]))
    return payload["data"]


def rest(method, path, body=None):
    req = urllib.request.Request(
        f"https://api.github.com{path}",
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Authorization": f"bearer {os.environ['GITHUB_TOKEN']}",
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def repo_meta():
    d = gql(
        """query($o:String!,$n:String!){repository(owner:$o,name:$n){id hasDiscussionsEnabled
           discussionCategories(first:50){nodes{id name}}}}""",
        o=REPO_OWNER, n=REPO_NAME,
    )["repository"]
    if not d["hasDiscussionsEnabled"]:
        sys.exit(f"Discussions are disabled on {REPO_OWNER}/{REPO_NAME}")
    cats = {c["name"]: c["id"] for c in d["discussionCategories"]["nodes"]}
    if CATEGORY not in cats:
        print(f"::warning::no '{CATEGORY}' discussion category, so no star threads are opened. "
              f"Create '{CATEGORY}' (Announcement format) under the repository's Discussions → categories.")
    return d["id"], cats.get(CATEGORY)


def all_discussions():
    """{template id: {id, url, body, upvotes}} for every marked discussion."""
    found, after = {}, None
    while True:
        d = gql(
            """query($o:String!,$n:String!,$a:String){repository(owner:$o,name:$n){
                 discussions(first:50,after:$a){pageInfo{hasNextPage endCursor}
                   nodes{id url body upvoteCount}}}}""",
            o=REPO_OWNER, n=REPO_NAME, a=after,
        )["repository"]["discussions"]
        for node in d["nodes"]:
            tid = marker_id(node["body"])
            if tid and tid not in found:
                found[tid] = {
                    "id": node["id"],
                    "url": node["url"],
                    "body": node["body"],
                    "upvotes": node["upvoteCount"],
                }
        if not d["pageInfo"]["hasNextPage"]:
            return found
        after = d["pageInfo"]["endCursor"]


def create_discussion(repo_id, category_id, entry, kind):
    d = gql(
        """mutation($r:ID!,$c:ID!,$t:String!,$b:String!){createDiscussion(input:{
             repositoryId:$r,categoryId:$c,title:$t,body:$b}){discussion{url}}}""",
        r=repo_id, c=category_id, t=f"⭐ {entry['id']}", b=discussion_body(entry, kind),
    )
    return {"url": d["createDiscussion"]["discussion"]["url"], "upvotes": 0}


def update_body(discussion_id, body):
    gql(
        """mutation($d:ID!,$b:String!){updateDiscussion(input:{discussionId:$d,body:$b}){discussion{id}}}""",
        d=discussion_id, b=body,
    )


def open_issues(template_id):
    label = label_for(template_id)
    if not label:
        return None
    if rest("GET", f"/repos/{REPO_OWNER}/{REPO_NAME}/labels/{urllib.parse.quote(label, safe='')}") == 404:
        rest("POST", f"/repos/{REPO_OWNER}/{REPO_NAME}/labels",
             {"name": label, "color": "c5def5", "description": f"Issues about the {template_id} template"})
        return 0
    d = gql(
        """query($o:String!,$n:String!,$l:[String!]){repository(owner:$o,name:$n){
             issues(labels:$l,states:OPEN){totalCount}}}""",
        o=REPO_OWNER, n=REPO_NAME, l=[label],
    )
    return d["repository"]["issues"]["totalCount"]


def account_created(login):
    d = gql("query($l:String!){repositoryOwner(login:$l){... on User{createdAt} ... on Organization{createdAt}}}", l=login)
    owner = d.get("repositoryOwner") or {}
    return owner.get("createdAt")


def live_snapshot(index, dry_run):
    repo_id, category_id = repo_meta()
    discussions = all_discussions()
    for kind, label in (("sources", "source"), ("sinks", "sink")):
        for e in index.get(kind, []):
            tid = e.get("id")
            if tid and tid in discussions:
                want = discussion_body(e, label)
                if discussions[tid].get("body") != want and discussions[tid].get("id"):
                    if dry_run:
                        print(f"would refresh the body of {discussions[tid]['url']}")
                    else:
                        update_body(discussions[tid]["id"], want)
                        print(f"refreshed {discussions[tid]['url']}")
                continue
            if tid and tid not in discussions:
                if category_id is None:
                    continue
                if dry_run:
                    print(f"would open a discussion for {tid}")
                    continue
                discussions[tid] = create_discussion(repo_id, category_id, e, label)
                print(f"opened {discussions[tid]['url']} for {tid}")
    ids = [e["id"] for k in ("sources", "sinks") for e in index.get(k, []) if e.get("id")]
    issues = {} if dry_run else {tid: n for tid in ids if (n := open_issues(tid)) is not None}
    accounts = {ns: c for ns in sorted({namespace(t) for t in ids} - {None}) if (c := account_created(ns))}
    return {"discussions": discussions, "open_issues": issues, "accounts": accounts}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixture", help="recorded API snapshot (JSON) instead of live GitHub")
    ap.add_argument("--index", default="index.json")
    ap.add_argument("--out", default="stars.json")
    ap.add_argument("--now", help="ISO timestamp to evaluate account ages against (tests)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    now = dt.datetime.fromisoformat(a.now.replace("Z", "+00:00")) if a.now else dt.datetime.now(dt.timezone.utc)
    with open(a.index) as f:
        index = json.load(f)
    if a.fixture:
        with open(a.fixture) as f:
            snapshot = json.load(f)
    else:
        snapshot = live_snapshot(index, a.dry_run)
    result = collect(index, snapshot, now)
    text = json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if a.dry_run:
        print(text)
    else:
        with open(a.out, "w") as f:
            f.write(text)
        print(f"wrote {a.out}: {len(result['templates'])} templates")
    return result


if __name__ == "__main__":
    main()
