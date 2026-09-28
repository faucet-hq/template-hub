# faucet-hq/zendesk

Zendesk Support over the **Support API v2**
([API reference](https://developer.zendesk.com/api-reference/)). Tickets and
users come from the cursor-based **incremental export** endpoints, which Zendesk
provides for exactly this job — syncing a Support account into another system.
The rest come from list endpoints with cursor pagination.

```bash
faucet run --source faucet-hq/zendesk --sink faucet-hq/bigquery \
  --param zendesk_url=https://acme.zendesk.com \
  --param zendesk_email=admin@example.com --param zendesk_api_token="$ZENDESK_API_TOKEN" \
  --param bq_project=my-project --param bq_sa_key="$BQ_SA_KEY" \
  --overlay my-state.yaml          # a state: block, so the exports resume
```

## Authentication and permissions

HTTP Basic with an **API token**: username `<email>/token`, password the token
([API token authentication](https://developer.zendesk.com/api-reference/introduction/security-and-auth/#api-token)).
Create it in Admin Center → Apps and integrations → APIs → Zendesk API. The
email must belong to an **admin**: the incremental exports and the
satisfaction-ratings list are *Allowed for Admins*; the other endpoints accept
agents.

## Streams

| Stream | Endpoint | Doc | Sync | Cursor | Primary key |
|---|---|---|---|---|---|
| tickets | `GET /api/v2/incremental/tickets/cursor` | [incremental ticket export](https://developer.zendesk.com/api-reference/ticketing/ticket-management/incremental_exports/#incremental-ticket-export-cursor-based) | incremental | export cursor (`after_cursor`) | `id` |
| users | `GET /api/v2/incremental/users/cursor` | [incremental user export](https://developer.zendesk.com/api-reference/ticketing/ticket-management/incremental_exports/#incremental-user-export-cursor-based) | incremental | export cursor (`after_cursor`) | `id` |
| organizations | `GET /api/v2/organizations` | [list organizations](https://developer.zendesk.com/api-reference/ticketing/organizations/organizations/#list-organizations) | full refresh | — | `id` |
| groups | `GET /api/v2/groups` | [list groups](https://developer.zendesk.com/api-reference/ticketing/groups/groups/#list-groups) | full refresh | — | `id` |
| ticket_fields | `GET /api/v2/ticket_fields` | [list ticket fields](https://developer.zendesk.com/api-reference/ticketing/tickets/ticket_fields/#list-ticket-fields) | full refresh | — | `id` |
| ticket_metrics | `GET /api/v2/ticket_metrics` | [list ticket metrics](https://developer.zendesk.com/api-reference/ticketing/tickets/ticket_metrics/#list-ticket-metrics) | full refresh | — | `id` |
| satisfaction_ratings | `GET /api/v2/satisfaction_ratings` | [list satisfaction ratings](https://developer.zendesk.com/api-reference/ticketing/ticket-management/satisfaction_ratings/#list-satisfaction-ratings) | full refresh | — | `id` |

**Incremental exports.** The first request sends `start_time`
(`zendesk_start_time`, default 2000-01-01 — the whole account) and
`per_page=1000`, the maximum. Each page returns `after_cursor`; the next page
sends `cursor=<after_cursor>`. When `end_of_stream` is true the export has
caught up to the present, and the last `after_cursor` is persisted as the
stream's bookmark (`persist_cursor`), so the next run continues from it instead
of re-exporting. Zendesk withholds the most recent minute from these exports to
avoid races, so nothing is missed between runs
([cursor-based incremental exports](https://developer.zendesk.com/documentation/api-basics/working-with-data/using-the-incremental-export-api/#cursor-based-incremental-exports)).
Records are upserted on `id`: an exported ticket or user is its latest state.

**Deletes.** The ticket export includes deleted tickets with `status:
"deleted"` (the template does not pass `exclude_deleted`), so a deletion
arrives as an upsert of that status. Deleted users stay in the user export with
`active: false`. The full-refresh streams overwrite their table each run, so a
deleted organization, group or field disappears.

**List endpoints.** `page[size]=100` (the maximum) selects cursor pagination;
the next page sends `page[after]=<meta.after_cursor>` while `meta.has_more` is
true ([pagination](https://developer.zendesk.com/api-reference/introduction/pagination/#using-cursor-pagination)).
Offset pagination is avoided on purpose: Zendesk rejects offset requests beyond
the first 10,000 records.

## Rate limits and run time

The incremental export endpoints allow **10 requests per minute**; the
template spaces those requests 6 seconds apart (`request_delay: 6`). Other
endpoints share the account limit — 200 to 2,500 requests per minute depending
on plan
([rate limits](https://developer.zendesk.com/api-reference/introduction/rate-limits/)).
A `429` carries `Retry-After`, which the template honours, retrying up to 10
times.

At 1,000 records per export page and 10 pages a minute, the first export runs
at about 10,000 tickets (or users) per minute: 1 million tickets take roughly
1¾ hours. `ticket_metrics` is one record per ticket at 100 per page, so a
1-million-ticket account needs 10,000 list requests — about 15 minutes at 700
requests per minute. Later runs of the two exports read only what changed.

## Live smoke test

```bash
faucet run --source faucet-hq/zendesk --sink faucet-hq/jsonl \
  --param zendesk_url=https://<subdomain>.zendesk.com \
  --param zendesk_email=<admin email> --param zendesk_api_token="$ZENDESK_API_TOKEN" \
  --param zendesk_start_time="$(date -v-7d +%s)" --param out_dir=./out
wc -l out/zendesk/*.jsonl
```

## Limitations

- The export's last page has `end_of_stream: true` but still returns an
  `after_cursor`; the REST source stops when the cursor stops changing, so each
  export makes one extra request that returns no records.
- `start_time` is sent on every request of an export, including the resumed
  ones that carry `cursor` — Zendesk uses it only on the initial request, as the
  reference's own samples show.

## Changelog

- **v1** — first release, built from the Zendesk Support API reference: seven
  streams, cursor-based incremental exports for tickets and users with the
  cursor persisted between runs.
