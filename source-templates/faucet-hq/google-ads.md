# faucet-hq/google-ads

A Google Ads account's structure (campaigns, ad groups, ads) and daily
performance (campaign, ad group, keyword) through the Google Ads API, one GAQL
query per stream.

```bash
faucet hub check --source faucet-hq/google-ads --sink faucet-hq/bigquery
faucet run --source faucet-hq/google-ads --sink faucet-hq/bigquery \
  --param google_ads_customer_id=1234567890 --param google_ads_login_customer_id=9876543210 \
  --param google_ads_developer_token="$GOOGLE_ADS_DEVELOPER_TOKEN" \
  --param google_client_id="$GOOGLE_CLIENT_ID" --param google_client_secret="$GOOGLE_CLIENT_SECRET" \
  --param google_refresh_token="$GOOGLE_REFRESH_TOKEN" \
  --param bq_project=my-project --param bq_sa_key="$BQ_SA_KEY"
```

- **API version:** `v22`, pinned in the path. Google sunsets each Google Ads API
  version roughly a year after release — the changelog records each bump, and
  a run against a sunset version fails with `UNSUPPORTED_VERSION` (bump the
  version in a copy, or take the newer template version).
- **Auth:** OAuth 2.0 refresh token (scope `https://www.googleapis.com/auth/adwords`)
  via the template's `auth:` catalog, plus the account's developer token and
  the `login-customer-id` header (the manager account the credentials act
  through, or the customer id itself for direct access).

## Streams

| Stream | GAQL resource | Sync | Primary key | Write preference |
|---|---|---|---|---|
| `campaigns` | `campaign` (+ budget) | full refresh | `campaign_id` | overwrite, upsert |
| `ad_groups` | `ad_group` | full refresh | `ad_group_id` | overwrite, upsert |
| `ads` | `ad_group_ad` | full refresh | `ad_group_id`, `ad_group_ad_ad_id` | overwrite, upsert |
| `campaign_performance` | `campaign`, daily | rolling window | `segments_date`, `campaign_id` | upsert, overwrite |
| `ad_group_performance` | `ad_group`, daily | rolling window | `segments_date`, `ad_group_id` | upsert, overwrite |
| `keyword_performance` | `keyword_view`, daily | rolling window | `segments_date`, `ad_group_id`, `ad_group_criterion_criterion_id` | upsert, overwrite |

Each row of `googleAds:search` is nested by resource (`campaign`, `metrics`,
`segments`); the template flattens it and snake_cases the keys, so
`metrics.costMicros` lands as `metrics_cost_micros` and `segments.date` as
`segments_date`. Google encodes 64-bit numbers (ids, `cost_micros`,
`impressions`) as strings; `metrics_conversions` is a float. Costs are in
micros of the account currency.

**Rolling window.** The performance streams re-read `performance_window`
(`LAST_7_DAYS`, `LAST_14_DAYS` or `LAST_30_DAYS`, default 30) every run and
upsert on date + entity, because conversions are attributed back to earlier
days for weeks. History older than the window stays in the table. For a
backfill, copy the template and change `DURING …` to
`BETWEEN '2023-01-01' AND '2023-12-31'`. On a sink without upsert (JSON Lines)
each run rewrites the window.

## Required permissions

- A developer token with at least **Explorer/Basic** access (a test-account
  token reads only test accounts).
- An OAuth client (Google Cloud console) and a refresh token for a Google user
  with read access to the account, scope `adwords`.

## Rate limits and run times

Search pages are 10,000 rows; the API allows 15,000 operations per day at Basic
access (unlimited at Standard) and throttles by QPS with `RESOURCE_EXHAUSTED`
(`429`), retried with backoff (`max_retries: 6`). A typical account finishes in
under a minute; `keyword_performance` over 30 days for 50,000 keywords is ~1.5 M
rows — ~150 requests, a few minutes.

## Testing

- `tests/faucet-hq/google-ads/replay.yaml` — recorded exchanges (values
  synthetic): the refresh-token grant (form fields asserted), then one search
  per stream (campaigns across two pages via `nextPageToken` → `pageToken`).
  `python3 scripts/replay.py faucet-hq/google-ads` compares the flattened
  records with `expected/`.
- `tests/faucet-hq/google-ads/suite.yaml` — `faucet template test` suite: every
  `performance_window` value, a rejected value, and a raw search row through
  the transforms.
- **Live smoke (manual):** with a test-account developer token,
  `faucet run --source faucet-hq/google-ads --sink faucet-hq/sqlite --param google_ads_customer_id=… …`.

## Changelog

- **v1** — first release: 6 streams, Google Ads API `v22`, performance over a
  rolling window.
