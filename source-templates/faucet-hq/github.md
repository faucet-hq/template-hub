# faucet-hq/github

One GitHub repository — issues, comments, pull requests, commits, releases,
Actions runs — through the GitHub REST API. Run it once per repository (a
matrix of repositories is a deployment concern: one run per `github_repo`).

```bash
faucet hub check --source faucet-hq/github --sink faucet-hq/postgres
faucet run --source faucet-hq/github --sink faucet-hq/postgres \
  --param github_token="$GITHUB_TOKEN" --param github_owner=octo-org --param github_repo=octo-repo \
  --param pg_url="$PG_URL" --overlay ops/prod.yaml     # `state:` for the incremental streams
```

- **API version:** pinned with `X-GitHub-Api-Version: 2022-11-28`.
- **GitHub Enterprise Server:** set `api_base_url` to `https://<host>/api/v3`.

## Streams

| Stream | Endpoint | Sync | Primary key | Write preference |
|---|---|---|---|---|
| `repository` | `GET /repos/{owner}/{repo}` | full refresh (one record) | `id` | overwrite, upsert |
| `issues` | `GET /repos/{owner}/{repo}/issues?state=all&sort=updated&direction=asc` | incremental on `updated_at` (`since=` pushed down) | `id` | upsert, overwrite |
| `issue_comments` | `GET /repos/{owner}/{repo}/issues/comments?sort=updated&direction=asc` | incremental on `updated_at` (`since=` pushed down) | `id` | upsert, overwrite |
| `pull_requests` | `GET /repos/{owner}/{repo}/pulls?state=all` | full refresh | `id` | overwrite, upsert |
| `commits` | `GET /repos/{owner}/{repo}/commits` (default branch) | full refresh | `sha` | overwrite, upsert |
| `releases` | `GET /repos/{owner}/{repo}/releases` | full refresh | `id` | overwrite, upsert |
| `workflow_runs` | `GET /repos/{owner}/{repo}/actions/runs` | full refresh | `id` | overwrite, upsert |
| `contributors` | `GET /repos/{owner}/{repo}/contributors` | full refresh | `id` | overwrite, upsert |

Pages are 100 items, followed through the `Link` header. `issues` includes pull
requests, as the GitHub API does (a record with a `pull_request` object is a
PR); join `pull_requests` on `number` for review and merge fields. Nested
objects (`user`, `labels`, `head`, …) stay nested.

**Why pull requests and commits are full refresh.** The pulls endpoint has no
`since` filter, and a commit's timestamp lives in a nested field
(`commit.committer.date`) the REST source cannot use as a replication key (see
the hub issue tracker). Both are read in full each run; for very large
repositories run them less often than the incremental streams (select streams
with `faucet run … --select <stream>`).

Incremental streams need a `state:` store (a deployment overlay); the first run
reads all history.

## Required permissions

A fine-grained token scoped to the repository with **read-only**: Metadata,
Issues, Pull requests, Contents (commits, releases, contributors), Actions
(workflow runs). A classic token needs `repo` (private repositories) or
`public_repo`. A GitHub App installation token with the same read permissions
works as `github_token`.

## Rate limits and run times

5,000 requests per hour for a token (15,000 for an Enterprise Cloud org's
GitHub App); each request returns up to 100 items. A repository with 20,000
issues and 50,000 commits needs ~700 requests for a first run (a few minutes);
later runs read only what changed plus the full-refresh streams. A secondary
rate-limit `403`/`429` is retried with backoff (`max_retries: 5`).

## Testing

- `tests/faucet-hq/github/replay.yaml` — recorded exchanges (values synthetic);
  `python3 scripts/replay.py faucet-hq/github` replays two runs: issues page
  twice through the `Link` header and resume with `since=<last updated_at>`.
- `tests/faucet-hq/github/suite.yaml` — `faucet template test` suite.
- **Live smoke (manual):** `faucet run --source faucet-hq/github --sink faucet-hq/sqlite
  --param github_token="$GITHUB_TOKEN" --param github_owner=faucet-hq --param github_repo=template-hub`.

## Changelog

- **v1** — first release: 8 streams, REST API version `2022-11-28`, `issues`
  and `issue_comments` incremental on `updated_at`.
