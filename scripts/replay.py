#!/usr/bin/env python3
"""Replay recorded API exchanges through a source template, offline.

Each `tests/<owner>/<name>/replay.yaml` holds the HTTP exchanges a template's
streams make against the real API — request shape, response body — recorded
without credentials. This script serves them from a local HTTP server, runs

    faucet run --hub . --source <owner>/<name> --sink faucet-hq/jsonl \
        --param out_dir=<tmp> --param <replay params…>

and compares every stream's written records (from the latest run that wrote
the stream, when `runs` > 1) with `tests/<owner>/<name>/expected/<stream>.jsonl`.
It fails when a request matches no recorded exchange (the template asked for
something the API was never shown to answer), when a recorded exchange is never
requested (a page the template skipped), or when a stream's records differ.

    python3 scripts/replay.py                       # every tests/*/*/replay.yaml
    python3 scripts/replay.py faucet-hq/stripe      # one template
    python3 scripts/replay.py --update faucet-hq/stripe   # rewrite expected/ from this run

replay.yaml:

    runs: 2                      # optional: run twice, so incremental streams resume from state
    overlay: overlay.yaml        # optional deployment overlay (a `state:` block reading
                                 # ${param.replay_state_dir}, a fresh directory per replay)
    params:                      # passed as --param; "{replay}" is the server's base URL
      api_key: sk_test_replay
      api_base_url: "{replay}"
    exchanges:
      - match:
          method: GET            # default GET
          path: /v1/customers
          query: { limit: "100" }          # each listed key must equal
          absent: [starting_after]         # each listed key must be missing
          headers: { authorization: Bearer sk_test_replay }   # case-insensitive names
          body: { operation: query }       # JSON subset match (POST)
          body_regex: { query: "SELECT .* WHERE SystemModstamp > .*" }   # top-level string fields, full match
          form: { grant_type: refresh_token }   # form-encoded body fields (token endpoints)
        response:
          status: 200            # default 200
          headers: { Link: '<{replay}/next>; rel="next"' }
          body: { … }            # JSON; or `text:` for a raw body (CSV)

"{replay}" is substituted in response headers and bodies too, so recorded
next-page links point back at the server. When several exchanges match a
request, the one with the most constraints wins.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.join(ROOT, "tests")


def subst(value, base):
    if isinstance(value, str):
        return value.replace("{replay}", base)
    if isinstance(value, list):
        return [subst(v, base) for v in value]
    if isinstance(value, dict):
        return {k: subst(v, base) for k, v in value.items()}
    return value


def subset(want, got):
    """`want` is contained in `got` (objects by key, arrays element-wise, scalars equal)."""
    if isinstance(want, dict):
        return isinstance(got, dict) and all(k in got and subset(v, got[k]) for k, v in want.items())
    if isinstance(want, list):
        return isinstance(got, list) and len(want) == len(got) and all(subset(a, b) for a, b in zip(want, got))
    return want == got


def specificity(m):
    return (
        len(m.get("query") or {})
        + len(m.get("absent") or [])
        + len(m.get("headers") or {})
        + (len(m["body"]) if isinstance(m.get("body"), dict) else 1 if m.get("body") is not None else 0)
        + len(m.get("body_regex") or {})
        + len(m.get("form") or {})
    )


def matches(m, method, path, query, headers, body, form=None):
    if (m.get("method") or "GET").upper() != method:
        return False
    if m.get("path") != path:
        return False
    for k, v in (m.get("query") or {}).items():
        if query.get(k) != [str(v)]:
            return False
    for k in m.get("absent") or []:
        if k in query:
            return False
    for k, v in (m.get("headers") or {}).items():
        if headers.get(k.lower()) != str(v):
            return False
    if m.get("body") is not None:
        if body is None or not subset(m["body"], body):
            return False
    for k, v in (m.get("form") or {}).items():
        if (form or {}).get(k) != [str(v)]:
            return False
    for k, pattern in (m.get("body_regex") or {}).items():
        if not isinstance(body, dict) or not isinstance(body.get(k), str) or not re.fullmatch(pattern, body[k], re.S):
            return False
    return True


class Recorder:
    """The recorded exchanges plus what was actually requested."""

    def __init__(self, exchanges):
        self.exchanges = exchanges
        self.hits = [0] * len(exchanges)
        self.unmatched = []
        self.lock = threading.Lock()
        self.base = ""

    def answer(self, method, raw_path, headers, raw_body):
        parts = urlsplit(raw_path)
        query = parse_qs(parts.query, keep_blank_values=True)
        body, form = None, None
        if raw_body:
            try:
                body = json.loads(raw_body)
            except ValueError:
                form = parse_qs(raw_body.decode(errors="replace"), keep_blank_values=True)
        lowered = {k.lower(): v for k, v in headers.items()}
        best = None
        for i, ex in enumerate(self.exchanges):
            m = ex.get("match") or {}
            if matches(m, method, parts.path, query, lowered, body, form):
                if best is None or specificity(m) > specificity(self.exchanges[best]["match"]):
                    best = i
        with self.lock:
            if best is None:
                self.unmatched.append(f"{method} {raw_path}" + (f" body={raw_body.decode()[:300]}" if raw_body else ""))
                return 599, {"Content-Type": "text/plain"}, b"no recorded exchange matches this request"
            self.hits[best] += 1
        resp = self.exchanges[best].get("response") or {}
        out_headers = {k: subst(str(v), self.base) for k, v in (resp.get("headers") or {}).items()}
        if "text" in resp:
            payload = subst(resp["text"], self.base).encode()
            out_headers.setdefault("Content-Type", "text/plain")
        elif "body" in resp:
            payload = json.dumps(subst(resp["body"], self.base)).encode()
            out_headers.setdefault("Content-Type", "application/json")
        else:
            payload = b""
        return int(resp.get("status", 200)), out_headers, payload


def serve(recorder):
    class Handler(BaseHTTPRequestHandler):
        def _handle(self):
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            status, headers, payload = recorder.answer(self.command, self.path, dict(self.headers), raw)
            self.send_response(status)
            for k, v in headers.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _handle

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    recorder.base = f"http://127.0.0.1:{server.server_address[1]}"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def read_jsonl(path):
    if not os.path.isfile(path):
        return []
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def jsonl_stems(d):
    if not os.path.isdir(d):
        return set()
    return {f[: -len(".jsonl")] for f in os.listdir(d) if f.endswith(".jsonl")}


def keep_latest_records(produced, kept):
    """Keep each stream's newest non-empty output across runs.

    The jsonl sink rewrites a stream's file on every run, and an incremental
    stream's second run usually finds nothing new — its file is then empty.
    The comparison is against the latest run that wrote the stream.
    """
    os.makedirs(kept, exist_ok=True)
    for s in jsonl_stems(produced):
        src = os.path.join(produced, f"{s}.jsonl")
        dst = os.path.join(kept, f"{s}.jsonl")
        if read_jsonl(src) or not os.path.exists(dst):
            shutil.copyfile(src, dst)


def canonical(records):
    return sorted(json.dumps(r, sort_keys=True) for r in records)


def run_one(tid, faucet="faucet", update=False):
    """Replay one template; returns a list of failure messages (empty = pass)."""
    case_dir = os.path.join(TESTS, *tid.split("/"))
    with open(os.path.join(case_dir, "replay.yaml")) as f:
        spec = yaml.safe_load(f) or {}
    recorder = Recorder(spec.get("exchanges") or [])
    server = serve(recorder)
    out = tempfile.mkdtemp(prefix="replay-")
    try:
        cmd = [faucet, "run", "--hub", ROOT, "--source", tid, "--sink", "faucet-hq/jsonl", "--param", f"out_dir={out}"]
        if spec.get("overlay"):
            cmd += ["--overlay", os.path.join(case_dir, spec["overlay"]), "--param", f"replay_state_dir={os.path.join(out, '.state')}"]
        for k, v in (spec.get("params") or {}).items():
            cmd += ["--param", f"{k}={subst(str(v), recorder.base)}"]
        failures = []
        kept = os.path.join(out, ".kept")
        for n in range(int(spec.get("runs", 1))):
            proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, env={**os.environ, "FAUCET_HUB_OFFLINE": "1"})
            if proc.returncode != 0:
                failures.append(f"faucet run #{n + 1} exited {proc.returncode}:\n{proc.stdout[-4000:]}\n{proc.stderr[-4000:]}")
                break
            keep_latest_records(os.path.join(out, tid.split("/")[-1]), kept)
        for req in recorder.unmatched:
            failures.append(f"request matches no recorded exchange: {req}")
        for i, n in enumerate(recorder.hits):
            if n == 0:
                m = recorder.exchanges[i].get("match") or {}
                failures.append(f"recorded exchange #{i + 1} was never requested: {m.get('method', 'GET')} {m.get('path')} {m.get('query') or ''}")
        produced = kept
        expected_dir = os.path.join(case_dir, "expected")
        streams = sorted(jsonl_stems(produced) | jsonl_stems(expected_dir))
        if update and not failures:
            os.makedirs(expected_dir, exist_ok=True)
            for s in streams:
                src = os.path.join(produced, f"{s}.jsonl")
                if os.path.isfile(src):
                    rows = [json.dumps(r, sort_keys=True) for r in read_jsonl(src)]
                    with open(os.path.join(expected_dir, f"{s}.jsonl"), "w") as f:
                        f.write("".join(r + "\n" for r in sorted(rows)))
            return []
        for s in streams:
            got = canonical(read_jsonl(os.path.join(produced, f"{s}.jsonl")))
            want = canonical(read_jsonl(os.path.join(expected_dir, f"{s}.jsonl")))
            if got != want:
                missing = [r for r in want if r not in got][:3]
                extra = [r for r in got if r not in want][:3]
                failures.append(f"stream {s}: {len(got)} record(s) written, {len(want)} expected\n  missing: {missing}\n  unexpected: {extra}")
        return failures
    finally:
        server.shutdown()
        shutil.rmtree(out, ignore_errors=True)


def discover():
    out = []
    if not os.path.isdir(TESTS):
        return out
    for owner in sorted(os.listdir(TESTS)):
        d = os.path.join(TESTS, owner)
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            if os.path.isfile(os.path.join(d, name, "replay.yaml")):
                out.append(f"{owner}/{name}")
    return out


def main(argv):
    update = "--update" in argv
    ids = [a for a in argv if not a.startswith("--")] or discover()
    faucet = os.environ.get("FAUCET", "faucet")
    failed = 0
    for tid in ids:
        failures = run_one(tid, faucet=faucet, update=update)
        if failures:
            failed += 1
            print(f"FAIL {tid}")
            for msg in failures:
                print("  - " + msg.replace("\n", "\n    "))
        else:
            print(f"ok   {tid}" + (" (expected/ rewritten)" if update else ""))
    print(f"\n{len(ids)} template(s): {len(ids) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
