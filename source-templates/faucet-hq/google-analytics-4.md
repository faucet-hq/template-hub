# faucet-hq/google-analytics-4

Google Analytics 4 through the **Google Analytics Data API v1beta**,
[`properties.runReport`](https://developers.google.com/analytics/devguides/reporting/data/v1/rest/v1beta/properties/runReport)
— one report per stream, read day by day in rolling windows. Written from the
[Data API documentation](https://developers.google.com/analytics/devguides/reporting/data/v1).

```bash
faucet run --source faucet-hq/google-analytics-4 --sink faucet-hq/bigquery \
  --param ga4_property_id=123456789 --param google_sa_key="$(cat sa.json)" \
  --param bq_project=my-project --param bq_sa_key="$BQ_SA_KEY" --overlay ops/state.yaml
```

## Authentication

A **Google Cloud service account** (the server-to-server path in the
[Data API quickstart](https://developers.google.com/analytics/devguides/reporting/data/v1/quickstart-client-libraries)):

1. Enable the *Google Analytics Data API* in the service account's project.
2. Create a key (JSON) for the service account.
3. In GA4 **Admin → Property access management**, add the service account's
   email as a **Viewer**.

The template exchanges a signed JWT for an access token (`google_service_account`
provider, OAuth 2.0 JWT-bearer grant) with the scope
`https://www.googleapis.com/auth/analytics.readonly`. Pass the key JSON from a
secret store (`--param-env`, `${secret:…}`); it is never written to logs.

## Streams

Every stream is a `runReport` over the dimensions and metrics listed, with a
`date` dimension so each window's rows are idempotent. Rows are typed
(integers, floats) and stamped with `property_id`.

| Stream | Dimensions | Metrics | Primary key |
|---|---|---|---|
| `traffic_daily` | date | sessions, totalUsers, newUsers, activeUsers, engagedSessions, screenPageViews, eventCount, keyEvents, userEngagementDuration, totalRevenue | property_id, date |
| `traffic_sources` | date, sessionSource, sessionMedium, sessionCampaignName, sessionDefaultChannelGroup | sessions, totalUsers, newUsers, engagedSessions, keyEvents, totalRevenue | property_id + dimensions |
| `landing_pages` | date, landingPagePlusQueryString (→ `landing_page`) | sessions, totalUsers, newUsers, engagedSessions, keyEvents | property_id + dimensions |
| `pages` | date, hostName, pagePath | screenPageViews, activeUsers, eventCount, userEngagementDuration | property_id + dimensions |
| `events` | date, eventName | eventCount, totalUsers, keyEvents | property_id + dimensions |
| `devices` | date, deviceCategory, operatingSystem, browser | sessions, totalUsers, newUsers, engagedSessions, screenPageViews | property_id + dimensions |
| `geography` | date, country, region, city | sessions, totalUsers, newUsers, engagedSessions | property_id + dimensions |

Endpoint for all: `POST /v1beta/properties/{property}:runReport`
([reference](https://developers.google.com/analytics/devguides/reporting/data/v1/rest/v1beta/properties/runReport));
names from the [API schema](https://developers.google.com/analytics/devguides/reporting/data/v1/api-schema).
Columns are snake_case (`total_users`, `session_source`); `date` stays GA4's
`YYYYMMDD` string. Write preference: `upsert` (on the primary key), else `append`.

### How rows are read

- **Rolling windows.** Each run reads from its bookmark minus
  `ga4_lookback_days` (default **3**) up to today, in windows of
  `ga4_window_days` (default 30). GA4 keeps processing a day's data for
  24–48 hours ([Data freshness](https://support.google.com/analytics/answer/11198161)),
  so the lookback re-reads those days and the upsert replaces the earlier
  figures. The bookmark is the end of the last completed window, so a failed
  run resumes from the window it stopped in. Windows are computed in UTC while
  GA4 dates are in the property's time zone; the lookback covers the offset.
- **Paging by body `offset`/`limit`** ([pagination](https://developers.google.com/analytics/devguides/reporting/data/v1/basics#pagination)),
  `ga4_page_size` rows per request (default 100,000; the API returns at most
  250,000 per request). An empty report omits `rows`, which ends the window.
- **Positional cells.** "The order of the columns is consistent in the
  request, header, and rows" ([API basics](https://developers.google.com/analytics/devguides/reporting/data/v1/basics)),
  so each stream names its cells with the same list it requests. That is what
  lets rows be paged one record per row — zipping against the response's own
  header lists would need the whole response as one record, and body-offset
  paging counts records.
- **No deletes**: reports are aggregates; a restated day is replaced by upsert.
- High-cardinality reports (`pages`, `landing_pages`, `geography`) can be
  rolled into an `(other)` row by GA4 on large properties, as in the GA4 UI.

## Quotas and run time

[Standard-property quotas](https://developers.google.com/analytics/devguides/reporting/data/v1/quotas):
200,000 tokens per property per day, 40,000 per hour, 14,000 per project per
property per hour, 10 concurrent requests. Exhaustion answers HTTP 429
(`RESOURCE_EXHAUSTED`), which the source retries with backoff, honouring
`Retry-After`. A daily run re-reads ~4 days per stream: 7 small requests,
seconds of wall time and a few hundred tokens. A first backfill of a year is
~13 windows × 7 streams ≈ 90 requests; a busy property's `pages` report can
cost tens of tokens per request, so long backfills may need spreading across
hours.

## State

All streams are windowed incremental reads; their bookmarks live in the run's
`state:` store. Without one (no overlay), every run re-reads from
`ga4_start_date`.

## Tests

- `tests/faucet-hq/google-analytics-4/suite.yaml` — parameter-space suite plus
  a behavioral case that names, types and stamps a raw `runReport` row.
- `tests/faucet-hq/google-analytics-4/replay.yaml` — the token exchange
  (served by the replay, with a throwaway RSA key), body-offset paging
  (page size 2), an empty report (no `rows`), and a second run that re-reads
  the lookback and upserts restated values.
- Throttling: a local server answering `429` (`RESOURCE_EXHAUSTED`,
  `retry-after: 1`) then `200` was retried after 1 s and the row written.

## Live smoke test

```bash
faucet run --source faucet-hq/google-analytics-4 --sink faucet-hq/jsonl \
  --param ga4_property_id=123456789 --param-env google_sa_key=GA4_SA_KEY \
  --param ga4_start_date="$(date -v-7d +%F)" --param out_dir=./out
head -3 out/google-analytics-4/traffic_daily.jsonl
```

## Changelog

- **v1** — first version, written from the Data API v1beta documentation.
  Needs a faucet release with the `google_service_account` auth provider
  (`google-sa` feature, in the default CLI build), body JSON-Pointer window
  binds, and `OffsetInBody` pagination.
