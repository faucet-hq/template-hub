# faucet-hq/github

GitHub REST API, version **`2026-03-10`** (the latest supported version; sent
as `X-GitHub-Api-Version`), for **one repository per run**. Written from the
[GitHub REST API documentation](https://docs.github.com/en/rest?apiVersion=2026-03-10)
and its [API versions page](https://docs.github.com/en/rest/about-the-rest-api/api-versions).

```bash
faucet run --source faucet-hq/github --sink faucet-hq/postgres \
  --param github_token="$GITHUB_TOKEN" --param github_owner=octo-org --param github_repo=demo \
  --param pg_url="$PG_URL" --overlay ops/state.yaml
```

## Authentication

A bearer token: a **fine-grained personal access token** or a **GitHub App
installation token** ([authenticating to the REST API](https://docs.github.com/en/rest/authentication/authenticating-to-the-rest-api?apiVersion=2026-03-10)).
Grant read-only repository permissions:

| Permission | Streams |
|---|---|
| Metadata: read | repository (always granted) |
| Issues: read | issues, issue_comments |
| Pull requests: read | pull_requests, review_comments |
| Contents: read | commits, releases |
| Actions: read | workflow_runs |

A classic token needs `repo` for a private repository (none for a public one).
Installation tokens expire after an hour — mint one per run.

## Streams

| Stream | Endpoint | Pagination | Cursor | Primary key | Write | Docs |
|---|---|---|---|---|---|---|
| `repository` | `GET /repos/{owner}/{repo}` | — | — (full refresh) | `id` | overwrite, upsert | [Get a repository](https://docs.github.com/en/rest/repos/repos?apiVersion=2026-03-10#get-a-repository) |
| `issues` | `GET /repos/{owner}/{repo}/issues?state=all&sort=updated&direction=asc` | Link header, 100/page | `updated_at` → `since` | `id` | upsert, append | [List repository issues](https://docs.github.com/en/rest/issues/issues?apiVersion=2026-03-10#list-repository-issues) |
| `issue_comments` | `GET /repos/{owner}/{repo}/issues/comments?sort=updated&direction=asc` | Link header, 100/page | `updated_at` → `since` | `id` | upsert, append | [List issue comments for a repository](https://docs.github.com/en/rest/issues/comments?apiVersion=2026-03-10#list-issue-comments-for-a-repository) |
| `pull_requests` | `GET /repos/{owner}/{repo}/pulls?state=all&sort=created&direction=asc` | Link header, 100/page | — (full refresh) | `id` | overwrite, upsert | [List pull requests](https://docs.github.com/en/rest/pulls/pulls?apiVersion=2026-03-10#list-pull-requests) |
| `review_comments` | `GET /repos/{owner}/{repo}/pulls/comments?sort=updated&direction=asc` | Link header, 100/page | `updated_at` → `since` | `id` | upsert, append | [List review comments in a repository](https://docs.github.com/en/rest/pulls/comments?apiVersion=2026-03-10#list-review-comments-in-a-repository) |
| `commits` | `GET /repos/{owner}/{repo}/commits` (default branch) | Link header, 100/page | `commit.committer.date` → `since` | `sha` | upsert, append | [List commits](https://docs.github.com/en/rest/commits/commits?apiVersion=2026-03-10#list-commits) |
| `releases` | `GET /repos/{owner}/{repo}/releases` | Link header, 100/page | — (full refresh) | `id` | overwrite, upsert | [List releases](https://docs.github.com/en/rest/releases/releases?apiVersion=2026-03-10#list-releases) |
| `workflow_runs` | `GET /repos/{owner}/{repo}/actions/runs?exclude_pull_requests=true` | Link header, 100/page | — (full refresh) | `id` | overwrite, upsert | [List workflow runs for a repository](https://docs.github.com/en/rest/actions/workflow-runs?apiVersion=2026-03-10#list-workflow-runs-for-a-repository) |

Records keep GitHub's field names (already snake_case); nested objects and
arrays (`user`, `labels`, `head`, `commit`, …) land as JSON strings so every
sink receives the same flat shape.

### Why these choices

- **Incremental streams use only the documented server-side filter.** `since`
  is documented on the issues, issue-comments, review-comments and commits
  lists ("Only show results that were last updated after the given time"). The
  bookmark is the largest cursor value written, pushed down as `since` on the
  next run and re-checked client-side. Lists are sorted `updated` ascending so
  pages walk forward in time.
- **The issues stream includes pull requests** — GitHub returns both from that
  endpoint, a pull request carrying a `pull_request` key. `pull_requests` adds
  the PR-only fields (`head`, `base`, `merged_at`, `draft`, reviewers).
- **`pull_requests`, `releases` and `workflow_runs` are full refreshes.** The
  pull-request and release lists have no `since`. The workflow-runs `created`
  filter caps a query at 1,000 results, so an incremental read built on it
  could silently skip runs; the unfiltered list has no such cap. Runs also
  change status after creation, which a full refresh picks up.
- **Deletes are not exposed** by these list endpoints; a deleted issue or
  comment simply stops appearing. The full-refresh streams drop deleted rows
  on `overwrite`.
- **Commits are the default branch's history**, filtered by commit date. A
  commit pushed long after it was committed (a rebase keeps the committer
  date) can predate the bookmark and be missed; re-read a range by running
  once without state and an earlier `github_start_date`.

## Rate limits and throttling

From [Rate limits for the REST API](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api?apiVersion=2026-03-10):
5,000 requests/hour for a user token or installation (up to 12,500 for large
installations, 15,000 on Enterprise Cloud); secondary limits of 100
concurrent requests and 900 points/minute. Both limits answer **403 or 429**.
The template retries a 403/429 carrying `retry-after` after that many seconds,
and one with `x-ratelimit-remaining: 0` after 60 s, up to 5 times.

Expected run time: one request per 100 records per stream. A repository with
10k issues and 20k comments reads in ~300 requests (a few minutes) the first
time and a handful of requests afterwards. `workflow_runs` and
`pull_requests` re-read everything each run — for a very busy repository
(100k+ runs) that is 1,000+ requests per run.

## State

`issues`, `issue_comments`, `review_comments` and `commits` keep their `since`
bookmark in the run's `state:` store; supply one with a deployment overlay or
they re-read from `github_start_date` every run.

## Tests

- `tests/faucet-hq/github/suite.yaml` — parameter-space suite
  (`faucet template test tests/faucet-hq/github/suite.yaml`).
- `tests/faucet-hq/github/replay.yaml` — recorded exchanges built from the
  documented response schemas with synthetic values: Link-header pagination
  (issues, two pages), the envelope of the workflow-runs list, and a second run
  that resumes every incremental stream from its `since` bookmark
  (`python3 scripts/replay.py faucet-hq/github`).
- Throttling: the replay harness answers a repeated request the same way every
  time, so it cannot script "403 then 200". The retry rules were exercised
  against a local server answering `403` + `x-ratelimit-remaining: 0`, then
  `403` + `retry-after: 1`, then `200`: the run waited 60 s and 1 s and wrote
  the record (`throttled 2×` in the run summary).

## Live smoke test

```bash
faucet run --source faucet-hq/github --sink faucet-hq/jsonl \
  --param github_token="$GITHUB_TOKEN" --param github_owner=faucet-hq --param github_repo=template-hub \
  --param out_dir=./out
wc -l out/github/*.jsonl
```

## Changelog

- **v1** — first version, written from the 2026-03-10 REST documentation.
  Needs a faucet release with `retry_on_response` (header matchers), nested
  replication keys (`commit.committer.date`) and query-once next links.
