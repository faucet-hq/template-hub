# faucet-hq/jira

Jira Cloud issues and the dictionaries needed to read them (projects, users,
fields, statuses, issue types) through the REST API v3.

```bash
faucet hub check --source faucet-hq/jira --sink faucet-hq/bigquery
faucet run --source faucet-hq/jira --sink faucet-hq/bigquery \
  --param jira_url=https://acme.atlassian.net --param jira_email=ops@acme.example \
  --param jira_api_token="$JIRA_API_TOKEN" --param bq_project=my-project --param bq_sa_key="$BQ_SA_KEY"
```

- **API version:** REST API v3 (`/rest/api/3/…`). Issues use the enhanced JQL
  search (`/search/jql`, token-paged), which replaces the retired
  `/rest/api/3/search`.
- **Auth:** basic auth with an Atlassian account email and API token.
- **Jira Data Center / Server** is not covered (different API version and auth).

## Streams

| Stream | Endpoint | Sync | Primary key | Write preference |
|---|---|---|---|---|
| `issues` | `GET /rest/api/3/search/jql?jql=<issues_jql>&fields=<issue_fields>` | full refresh of the JQL result | `id` | overwrite, upsert |
| `projects` | `GET /rest/api/3/project/search?expand=description,lead` | full refresh | `id` | overwrite, upsert |
| `users` | `GET /rest/api/3/users/search` | full refresh | `account_id` | overwrite, upsert |
| `fields` | `GET /rest/api/3/field` | full refresh | `id` | overwrite, upsert |
| `statuses` | `GET /rest/api/3/status` | full refresh | `id` | overwrite, upsert |
| `issue_types` | `GET /rest/api/3/issuetype` | full refresh | `id` | overwrite, upsert |

Keys are snake_cased at every level (`statusCategory` → `status_category`);
custom fields keep their ids (`customfield_10016`) — join `fields` to name
them. An issue's `fields` object stays nested (a JSON column): its shape
depends on the site's configuration.

**Narrowing the issue set.** `issues_jql` selects what to sync; the enhanced
search refuses an unbounded query, hence the default
`updated >= "2000-01-01" ORDER BY updated ASC`. `project in (ENG, OPS) ORDER BY
updated ASC` syncs two projects.

**Why issues are full refresh.** The issue's `updated` timestamp is nested
under `fields`, and the REST source's replication key must be a top-level
field (tracked on the hub issue tracker). Each run re-reads the JQL result and
replaces the table; narrow `issues_jql` (e.g. `updated >= -30d`) and switch the
stream to upsert in a copy of the template for very large sites.

## Required permissions

The account needs **Browse projects** on every project to sync and **Browse
users and groups** (global) for `users`. An API token carries the account's
permissions; there are no token scopes for basic auth.

## Rate limits and run times

Jira Cloud rate-limits by cost per account (points per hour) and answers `429`
with `Retry-After`, which the source honours (`max_retries: 6`). Issue pages
are 100 issues; with `*navigable` fields a page takes ~0.5–2 s, so 50,000
issues take roughly 5–15 minutes. Narrower `issue_fields` are faster.

## Testing

- `tests/faucet-hq/jira/replay.yaml` — recorded exchanges (values synthetic);
  `python3 scripts/replay.py faucet-hq/jira` pages issues through
  `nextPageToken`, projects through `nextPage` and users through
  `startAt`/`maxResults`.
- `tests/faucet-hq/jira/suite.yaml` — `faucet template test` suite with a
  behavioural case over a raw issue (`records/issues.jsonl`).
- **Live smoke (manual):** `faucet run --source faucet-hq/jira --sink faucet-hq/sqlite
  --param jira_url=… --param jira_email=… --param jira_api_token="$T" --param issues_jql="project = ENG ORDER BY updated ASC"`.

## Changelog

- **v1** — first release: 6 streams, REST API v3, enhanced JQL search.
