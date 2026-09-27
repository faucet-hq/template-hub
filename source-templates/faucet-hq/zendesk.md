# faucet-hq/zendesk

Zendesk Support through the API v2: tickets, users and organizations from the
incremental export API, plus groups, ticket metrics, satisfaction ratings and
ticket field definitions.

```bash
faucet hub check --source faucet-hq/zendesk --sink faucet-hq/bigquery
faucet run --source faucet-hq/zendesk --sink faucet-hq/bigquery \
  --param zendesk_url=https://acme.zendesk.com --param zendesk_email=ops@acme.example \
  --param zendesk_api_token="$ZENDESK_API_TOKEN" --param bq_project=my-project --param bq_sa_key="$BQ_SA_KEY" \
  --overlay ops/prod.yaml          # `state:` for the incremental streams
```

- **API version:** Zendesk's API v2 (`/api/v2/…`), the only version.
- **Auth:** API token — basic auth as `<email>/token`. `zendesk_url` is your
  account root (`https://<subdomain>.zendesk.com`, or a host-mapped domain).

## Streams

| Stream | Endpoint | Sync | Primary key | Write preference |
|---|---|---|---|---|
| `tickets` | `GET /api/v2/incremental/tickets/cursor.json` | incremental on `updated_at` (`start_time`, then `after_url`) | `id` | upsert, overwrite |
| `users` | `GET /api/v2/incremental/users/cursor.json` | incremental on `updated_at` | `id` | upsert, overwrite |
| `organizations` | `GET /api/v2/incremental/organizations.json` | incremental on `updated_at` (`next_page`) | `id` | upsert, overwrite |
| `satisfaction_ratings` | `GET /api/v2/satisfaction_ratings.json?start_time=` | incremental on `updated_at` | `id` | upsert, overwrite |
| `groups` | `GET /api/v2/groups.json` | full refresh | `id` | overwrite, upsert |
| `ticket_metrics` | `GET /api/v2/ticket_metrics.json` | full refresh | `id` | overwrite, upsert |
| `ticket_fields` | `GET /api/v2/ticket_fields.json` | full refresh | `id` | overwrite, upsert |

The first run exports everything updated since `start_date` (default
2010-01-01); each later run resumes from the last `updated_at` it wrote. The
incremental export includes deleted tickets (`status: deleted`), so an upsert
sink keeps their final state. Full-refresh streams use cursor pagination
(`page[size]=100`). Ticket `custom_fields` stay a nested array — decode them
with `ticket_fields`.

Incremental streams need a `state:` store (a deployment overlay).

## Required permissions

An API token (Admin Center → Apps and integrations → APIs → Zendesk API, token
access enabled) belonging to an **admin** — the incremental export endpoints
are admin-only. Satisfaction ratings need CSAT enabled on the account.

## Rate limits and run times

The incremental export endpoints are limited to **10 requests per minute**
(30 with the High Volume API add-on), each returning up to 1,000 records — so
an export runs at roughly 10,000 records a minute: a first `tickets` run over
1 M tickets takes ~100 minutes; later runs are usually a single request. The
other endpoints share the account limit (200–2,500 requests per minute by
plan). A `429` is retried after its `Retry-After` (`max_retries: 8`).

## Testing

- `tests/faucet-hq/zendesk/replay.yaml` — recorded exchanges (values synthetic);
  `python3 scripts/replay.py faucet-hq/zendesk` replays two runs: the exports
  start at `start_time=<start_date>`, follow `after_url`/`next_page` (which
  carry only the cursor), and the second run resumes at the epoch of the last
  `updated_at`; `groups` pages through `links.next`.
- `tests/faucet-hq/zendesk/suite.yaml` — `faucet template test` suite.
- **Live smoke (manual):** against a sandbox account,
  `faucet run --source faucet-hq/zendesk --sink faucet-hq/sqlite --param zendesk_url=… --param zendesk_email=… --param zendesk_api_token="$T" --param start_date=2024-01-01T00:00:00Z`.

## Changelog

- **v1** — first release: 7 streams; tickets, users, organizations and
  satisfaction ratings incremental on `updated_at`.
