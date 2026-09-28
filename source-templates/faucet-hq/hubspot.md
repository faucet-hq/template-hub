# faucet-hq/hubspot

HubSpot CRM on the date-versioned **2026-09** API
([API reference](https://developers.hubspot.com/docs/api-reference/latest/crm)):
contacts, companies, deals and tickets read incrementally through the CRM
search API, their archived (deleted) records, owners, and the deal and ticket
pipelines.

```bash
faucet run --source faucet-hq/hubspot --sink faucet-hq/bigquery \
  --param hubspot_access_token="$HUBSPOT_TOKEN" \
  --param bq_project=my-project --param bq_sa_key="$BQ_SA_KEY" \
  --overlay my-state.yaml          # a state: block, so the CRM streams resume
```

## Authentication and scopes

Bearer access token of a **private app** created in the portal (Settings →
Integrations → Private apps), which HubSpot documents for single-account
integrations
([private apps](https://developers.hubspot.com/docs/apps/legacy-apps/private-apps/overview)).
Grant these read scopes, as listed on each endpoint's reference page:

| Scope | Streams |
|---|---|
| `crm.objects.contacts.read` | contacts, contacts_archived |
| `crm.objects.companies.read` | companies, companies_archived |
| `crm.objects.deals.read` | deals, deals_archived, deal_pipelines |
| `tickets` | tickets, tickets_archived, ticket_pipelines |
| `crm.objects.owners.read` | owners |

## Streams

| Stream | Endpoint | Doc | Sync | Cursor | Primary key |
|---|---|---|---|---|---|
| contacts | `POST /crm/objects/2026-09/contacts/search` | [search contacts](https://developers.hubspot.com/docs/api-reference/latest/crm/objects/contacts/search/search-contacts) | incremental | `lastmodifieddate` / `updatedAt` | `id` |
| companies | `POST /crm/objects/2026-09/companies/search` | [search companies](https://developers.hubspot.com/docs/api-reference/latest/crm/objects/companies/search/search-companies) | incremental | `hs_lastmodifieddate` / `updatedAt` | `id` |
| deals | `POST /crm/objects/2026-09/deals/search` | [search deals](https://developers.hubspot.com/docs/api-reference/latest/crm/objects/deals/search/search-deals) | incremental | `hs_lastmodifieddate` / `updatedAt` | `id` |
| tickets | `POST /crm/objects/2026-09/tickets/search` | [search tickets](https://developers.hubspot.com/docs/api-reference/latest/crm/objects/tickets/search/search-tickets) | incremental | `hs_lastmodifieddate` / `updatedAt` | `id` |
| contacts_archived, companies_archived, deals_archived, tickets_archived | `GET /crm/objects/2026-09/{object}?archived=true` | [list contacts](https://developers.hubspot.com/docs/api-reference/latest/crm/objects/contacts/get-contacts) | full refresh | — | `id` |
| owners | `GET /crm/owners/2026-09` | [retrieve all owners](https://developers.hubspot.com/docs/api-reference/latest/crm/owners/get-owners) | full refresh | — | `id` |
| deal_pipelines, ticket_pipelines | `GET /crm/pipelines/2026-09/{deals,tickets}` | [retrieve all pipelines](https://developers.hubspot.com/docs/api-reference/latest/crm/pipelines/get-pipelines) | full refresh | — | `id` |

**Incremental reads through search.** The object list endpoints cannot filter
by modification time; the search API can, and sorts
([CRM search](https://developers.hubspot.com/docs/api-reference/search/guide)).
Each request filters `<last-modified> GTE <bookmark>`, sorts ascending on it,
and asks for 200 records (the maximum). The search API refuses to page past
10,000 results for one query, so the template does not page with `after`:
a second filter carries a **keyset** — the largest `updatedAt` of the page just
read — and every page is a new query starting there. Contacts use
`lastmodifieddate`; the other objects use `hs_lastmodifieddate` (each object's
documented default property). `updatedAt` on each result mirrors it and is the
bookmark. Date filters accept ISO 8601 strings
([date and datetime values](https://developers.hubspot.com/docs/api-reference/crm-properties-v3/guide)).

The keyset is inclusive (`GTE`), so the record(s) at a page boundary appear on
both pages; the upsert on `id` makes that harmless, while an exclusive bound
could skip a record sharing the boundary millisecond. HubSpot notes that a
just-modified record can take a few moments to appear in search. Records are
flattened (`properties.email` → `properties__email`).

**Deletes.** Search never returns archived records. The four `*_archived`
streams list them (`archived=true`, 100 per page, `paging.next.after`) with
their `archivedAt`, so a downstream model can remove them from the live table.

## Rate limits and run time

Privately distributed apps get 100 requests per 10 seconds (Free and Starter)
or 190 (Professional and Enterprise), and 250,000 to 1,000,000 requests a day
per account; the search endpoints are further limited to **five requests per
second per account**, and a breach answers `429`
([usage guidelines](https://developers.hubspot.com/docs/developer-tooling/platform/usage-guidelines),
[search limits](https://developers.hubspot.com/docs/api-reference/search/guide#limits)).
Each search stream waits one second between requests (`request_delay: 1`), so
the four together stay under five per second; `429`s are retried with backoff.

At 200 records a second per search stream, a first sync of 1 million contacts
takes about 1½ hours; later runs read only what was modified since the
bookmark.

## Live smoke test

```bash
faucet run --source faucet-hq/hubspot --sink faucet-hq/jsonl \
  --param hubspot_access_token="$HUBSPOT_TOKEN" \
  --param hubspot_start_date="$(date -u -v-7d +%Y-%m-%dT%H:%M:%SZ)" --param out_dir=./out
wc -l out/hubspot/*.jsonl
```

## Limitations

- **Fixed property lists.** HubSpot returns only the properties a request
  names, and the REST source cannot first read `/crm/properties/…` and inject
  the full list, so each object requests a documented default set (see the
  template). Copy the template to add custom properties.
- If more than 200 records share one `updatedAt` millisecond, the keyset
  cannot advance past them and the pass stops there (logged as a pagination
  loop), and later runs stop at the same place. Bulk imports that stamp one
  timestamp on many records are the case to watch for.
- The search bookmark is rendered at second precision, so each run re-reads
  the records of the bookmark's second (deduplicated by the upsert).

## Changelog

- **v1** — first release, built from the HubSpot 2026-09 API reference: four
  incremental CRM streams through search with a keyset cursor, archived records,
  owners, deal and ticket pipelines.
