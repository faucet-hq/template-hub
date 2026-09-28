# faucet-hq/jira

Jira Cloud over the **Jira Cloud platform REST API v3**
([reference](https://developer.atlassian.com/cloud/jira/platform/rest/v3/)):
every issue with all of its fields, plus the reference data needed to read
them.

```bash
faucet run --source faucet-hq/jira --sink faucet-hq/bigquery \
  --param jira_url=https://acme.atlassian.net \
  --param jira_email=bot@example.com --param jira_api_token="$JIRA_API_TOKEN" \
  --param bq_project=my-project --param bq_sa_key="$BQ_SA_KEY"
```

## Authentication and permissions

HTTP Basic with an **Atlassian API token** — username the account email,
password the token
([basic auth for REST APIs](https://developer.atlassian.com/cloud/jira/platform/basic-auth-for-rest-apis/)).
Create the token at id.atlassian.com → Security → API tokens, for a dedicated
service account. The data you get is what that account may see: issues need
*Browse projects* on each project (and issue-security permission where set);
`users` needs *Browse users and groups*. If you register an OAuth 2.0 app
instead, the equivalent classic scopes are `read:jira-work` and
`read:jira-user`.

## Streams

| Stream | Endpoint | Doc | Sync | Pagination | Primary key |
|---|---|---|---|---|---|
| issues | `GET /rest/api/3/search/jql` | [search for issues using JQL (enhanced search)](https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issue-search/#api-rest-api-3-search-jql-get) | full refresh | `nextPageToken` | `id` |
| projects | `GET /rest/api/3/project/search` | [get projects paginated](https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-projects/#api-rest-api-3-project-search-get) | full refresh | `nextPage` link | `id` |
| users | `GET /rest/api/3/users/search` | [get all users](https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-users/#api-rest-api-3-users-search-get) | full refresh | `startAt` / `maxResults` | `accountId` |
| fields | `GET /rest/api/3/field` | [get fields](https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issue-fields/#api-rest-api-3-field-get) | full refresh | — | `id` |
| statuses | `GET /rest/api/3/status` | [get all statuses](https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-workflow-statuses/#api-rest-api-3-status-get) | full refresh | — | `id` |
| issue_types | `GET /rest/api/3/issuetype` | [get all issue types for user](https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issue-types/#api-rest-api-3-issuetype-get) | full refresh | — | `id` |
| priorities | `GET /rest/api/3/priority/search` | [search priorities](https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issue-priorities/#api-rest-api-3-priority-search-get) | full refresh | `nextPage` link | `id` |
| resolutions | `GET /rest/api/3/resolution/search` | [search resolutions](https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issue-resolutions/#api-rest-api-3-resolution-search-get) | full refresh | `nextPage` link | `id` |

**Issues** use the enhanced JQL search, the replacement for the removed
`/rest/api/3/search`. It requires a *bounded* query, so the template sends
`created >= 0 ORDER BY created ASC, key ASC` — an unquoted number in JQL is
milliseconds since the epoch
([JQL fields: created](https://support.atlassian.com/jira-software-cloud/docs/jql-fields/#Created)),
which bounds the query without depending on the searching user's time zone.
`fields=*all` returns every system and custom field; `maxResults=100`; pages
follow `nextPageToken`, which is absent on the last page. The `fields` stream
names the `customfield_*` keys.

**Why issues are a full refresh.** The natural incremental is `updated >=
<bookmark>` in epoch milliseconds, but Jira timestamps carry an offset without
a colon (`2026-01-02T12:00:00.000+0000`), which the REST source cannot yet parse
back into a bound (see Limitations). Until it can, the template re-reads issues
each run and replaces the table (`[overwrite, upsert]`) — which also removes
deleted issues, something an `updated` incremental could never see: the search
API does not return deleted issues.

**Paged reference data** follows the `nextPage` URL of each `PageBean`
response; `users` is a bare array paged with `startAt` until a short page.

## Rate limits and run time

Jira Cloud answers `429 Too Many Requests` with `Retry-After` and
`X-RateLimit-*` headers when a burst or quota limit is exceeded
([rate limiting](https://developer.atlassian.com/cloud/jira/platform/rate-limiting/)).
Points-based hourly quotas apply to Forge, Connect and OAuth 2.0 apps; API-token
traffic is governed by the burst limits. The template honours `Retry-After`
and retries up to 8 times with exponential backoff.

With `fields=*all`, Jira returns up to 100 issues per page — expect roughly
3,000–6,000 issues per minute depending on field count, so a 100,000-issue site
takes 20–30 minutes. The reference streams take seconds.

## Live smoke test

```bash
faucet run --source faucet-hq/jira --sink faucet-hq/jsonl \
  --param jira_url=https://<site>.atlassian.net \
  --param jira_email=<email> --param jira_api_token="$JIRA_API_TOKEN" --param out_dir=./out
wc -l out/jira/*.jsonl
```

## Limitations

- **No incremental issues yet.** A `replication_bind` with `format: epoch_ms`
  fails on Jira's `…+0000` offsets; the engine accepts only RFC 3339
  (`+00:00` / `Z`). Once it parses ISO 8601 basic offsets, `issues` becomes
  incremental on `fields.updated`.
- Issue changelogs and worklogs are not included; both need per-issue requests.

## Changelog

- **v1** — first release, built from the Jira Cloud REST API v3 reference:
  eight streams, issues through the enhanced JQL search.
