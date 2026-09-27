# faucet-hq/salesforce

Salesforce core CRM objects through **Bulk API 2.0** query jobs: each stream
submits a SOQL job, polls it to completion and streams the CSV result, so an
object of any size is read without the REST query API's 2,000-row pages.

```bash
faucet hub check --source faucet-hq/salesforce --sink faucet-hq/bigquery
faucet run --source faucet-hq/salesforce --sink faucet-hq/bigquery \
  --param salesforce_instance_url=https://acme.my.salesforce.com \
  --param salesforce_client_id="$SF_CLIENT_ID" --param salesforce_client_secret="$SF_CLIENT_SECRET" \
  --param salesforce_refresh_token="$SF_REFRESH_TOKEN" \
  --param bq_project=my-project --param bq_sa_key="$BQ_SA_KEY" --overlay ops/prod.yaml
```

- **API version:** `v62.0`, pinned in every path. Salesforce keeps old API
  versions available for years; a bump is a new template version.
- **Auth:** OAuth 2.0 refresh-token flow against a connected app, declared once
  in the template's `auth:` catalog (`oauth2_refresh`), so every stream shares
  one access token. `salesforce_login_url` is `https://login.salesforce.com`
  (production) or `https://test.salesforce.com` (sandbox);
  `salesforce_instance_url` is the org's My Domain URL.

## Streams

| Stream | SObject | Bulk operation | Sync | Primary key | Write preference |
|---|---|---|---|---|---|
| `accounts` | Account | `queryAll` | incremental on `SystemModstamp` | `Id` | upsert, overwrite |
| `contacts` | Contact | `queryAll` | incremental on `SystemModstamp` | `Id` | upsert, overwrite |
| `leads` | Lead | `queryAll` | incremental on `SystemModstamp` | `Id` | upsert, overwrite |
| `opportunities` | Opportunity | `queryAll` | incremental on `SystemModstamp` | `Id` | upsert, overwrite |
| `users` | User | `query` | incremental on `SystemModstamp` | `Id` | upsert, overwrite |
| `campaigns` | Campaign | `queryAll` | incremental on `SystemModstamp` | `Id` | upsert, overwrite |
| `tasks` | Task | `queryAll` | incremental on `SystemModstamp` | `Id` | upsert, overwrite |

Each stream selects the object's standard fields (the template lists them;
compound address fields are read as their components, since Bulk API 2.0 does
not return compound fields). Columns keep their API names (`BillingCity`,
`IsDeleted`). **Values arrive as CSV text**: numbers and booleans are strings
(`"48000"`, `"true"`) and an empty field is `""` rather than null — cast in the
warehouse, or add a `cast` transform in a copy.

**Incremental.** The first run exports every record. Later runs add
`WHERE SystemModstamp > <bookmark>` to each job's SOQL, where the bookmark is
the previous run's start time minus 10 minutes (`lookback`), so a record
modified while a job ran is re-read rather than missed; the upsert makes the
overlap harmless. `queryAll` includes soft-deleted records (`IsDeleted =
"true"`), so deletions reach the destination as updates. Incremental streams
need a `state:` store (a deployment overlay).

**Custom fields and objects.** Copy the template into your namespace and extend
a stream's `SELECT` (or add a stream per custom object, e.g.
`SELECT Id, Name, Amount__c, SystemModstamp, IsDeleted FROM Invoice__c`). To
list an object's fields, `GET /services/data/v62.0/sobjects/<Object>/describe`
— or let `faucet discover` build the field list with the REST source's
`discovery.describe` recipe.

## Required permissions

- A connected app with OAuth scopes **`api`** and **`refresh_token,
  offline_access`**; a refresh token issued to the integration user.
- The integration user needs **API Enabled** and read access (object and
  field-level security) to each object and field selected. Fields it cannot
  see make the job fail with `INVALID_FIELD` — remove them from the copy's
  `SELECT`.

## Rate limits and run times

Each job pays a fixed queue-and-process floor — typically **15–60 seconds per
stream** even for a handful of rows — then streams results at roughly 1–2 M
rows per minute; up to four streams run at once by default. A first run over
5 M accounts takes ~5 minutes for `accounts`; incremental runs finish in about
a minute in total. Bulk API 2.0 query jobs count against the org's daily API
request limit (one request per submit, poll and result page) and its Bulk API
allocations (Setup → System Overview shows both). Polling backs off from 1 s to 10 s; a job is given
up after 2 hours (`timeout_secs: 7200`).

## Testing

- `tests/faucet-hq/salesforce/replay.yaml` — recorded exchanges (values
  synthetic): the refresh-token grant, then per stream the job submit, poll
  and CSV result pages (accounts across two `Sforce-Locator` pages).
  `python3 scripts/replay.py faucet-hq/salesforce` runs it twice; the second
  run's jobs carry `WHERE SystemModstamp > …` and a soft-deleted account.
- `tests/faucet-hq/salesforce/suite.yaml` — `faucet template test` suite
  (production and sandbox shapes).
- **Live smoke (manual):** against a Developer Edition or sandbox org,
  `faucet run --source faucet-hq/salesforce --sink faucet-hq/sqlite --param salesforce_login_url=https://test.salesforce.com …`.

## Changelog

- **v1** — first release: 7 streams over Bulk API 2.0 (`v62.0`), incremental
  on `SystemModstamp`, soft deletes via `queryAll`.
