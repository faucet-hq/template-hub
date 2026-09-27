# faucet-hq/hubspot

HubSpot CRM objects through the CRM v3 API — one table per object, with each
object's `properties` lifted to top-level columns.

```bash
faucet hub check --source faucet-hq/hubspot --sink faucet-hq/postgres
faucet run --source faucet-hq/hubspot --sink faucet-hq/postgres \
  --param hubspot_token="$HUBSPOT_TOKEN" --param pg_url="$PG_URL"
```

- **API version:** CRM v3 (`/crm/v3/…`), pinned in every path.
- **Auth:** a private app access token (`hubspot_token`). An OAuth app's access
  token works the same way.

## Streams

| Stream | Endpoint | Sync | Primary key | Write preference |
|---|---|---|---|---|
| `contacts` | `GET /crm/v3/objects/contacts` | full refresh | `id` | overwrite, upsert |
| `companies` | `GET /crm/v3/objects/companies` | full refresh | `id` | overwrite, upsert |
| `deals` | `GET /crm/v3/objects/deals` | full refresh | `id` | overwrite, upsert |
| `tickets` | `GET /crm/v3/objects/tickets` | full refresh | `id` | overwrite, upsert |
| `products` | `GET /crm/v3/objects/products` | full refresh | `id` | overwrite, upsert |
| `owners` | `GET /crm/v3/owners` | full refresh | `id` | overwrite, upsert |
| `deal_pipelines` | `GET /crm/v3/pipelines/deals` | full refresh | `id` | overwrite, upsert |

**Columns.** Each object stream reads the properties named by its
`*_properties` param (sensible defaults; add custom properties with e.g.
`--param contact_properties="email,firstname,my_score"`). Records are
flattened, the `properties__` prefix is removed and keys are snake_cased, so a
contact lands as `id, email, firstname, …, created_at, updated_at, archived`.
HubSpot returns every property value as a string (`"48000"`), and so does the
table; cast in the warehouse or add a `cast` transform in a copy. Pipeline
`stages` stay a nested array.

**Why full refresh.** The CRM list endpoints have no modified-since filter. The
search endpoint does (`hs_lastmodifieddate`), but its filter sits inside the
request body's `filterGroups`, where the REST source cannot yet place a
bookmark (tracked on the hub issue tracker), and it stops at 10,000 results per
query. Every run therefore re-reads each object and replaces the table, which
also removes deleted records.

## Required scopes

Private app scopes: `crm.objects.contacts.read`, `crm.objects.companies.read`,
`crm.objects.deals.read`, `tickets`, `e-commerce` (products),
`crm.objects.owners.read`. Deal pipelines are readable with
`crm.objects.deals.read`.

## Rate limits and run times

Private apps get 100 requests per 10 seconds (Free/Starter) or 190 (Pro and
Enterprise), plus a daily cap; each request returns up to 100 records. With up
to four streams in parallel, 1 M contacts take roughly 10–20 minutes; a portal
of 50,000 records across all objects finishes in about a minute. A `429` is
retried after its `Retry-After` (`max_retries: 6`).

## Testing

- `tests/faucet-hq/hubspot/replay.yaml` — recorded exchanges (values synthetic);
  `python3 scripts/replay.py faucet-hq/hubspot` runs every stream through the
  REST source (contacts pages twice through `paging.next.after`) and compares
  the flattened records with `expected/`.
- `tests/faucet-hq/hubspot/suite.yaml` — `faucet template test` suite; its
  behavioural case feeds a raw API record (`records/contacts.jsonl`) through
  the shared transforms and asserts the exact column set.
- **Live smoke (manual):** in a developer test account,
  `faucet run --source faucet-hq/hubspot --sink faucet-hq/sqlite --param hubspot_token="$T"`.

## Changelog

- **v1** — first release: 7 streams, CRM v3, full refresh, properties lifted
  to columns.
