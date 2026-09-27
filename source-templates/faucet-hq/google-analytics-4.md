# faucet-hq/google-analytics-4

Daily Google Analytics 4 reports — traffic by channel, pages, events, devices,
geography and acquisition — through the GA4 Data API `runReport` method, one
report per stream.

```bash
faucet hub check --source faucet-hq/google-analytics-4 --sink faucet-hq/bigquery
faucet run --source faucet-hq/google-analytics-4 --sink faucet-hq/bigquery \
  --param ga4_property_id=123456789 \
  --param google_client_id="$GOOGLE_CLIENT_ID" --param google_client_secret="$GOOGLE_CLIENT_SECRET" \
  --param google_refresh_token="$GOOGLE_REFRESH_TOKEN" \
  --param bq_project=my-project --param bq_sa_key="$BQ_SA_KEY"
```

- **API version:** Data API `v1beta`, pinned in the path. The changelog records
  a move to `v1` when Google ships it.
- **Auth:** OAuth 2.0 refresh token (scope
  `https://www.googleapis.com/auth/analytics.readonly`) via the template's
  `auth:` catalog.
- **Property:** `ga4_property_id` is the numeric property id (Admin → Property
  settings), not the `G-…` measurement id.

## Streams

| Stream | Dimensions | Metrics | Primary key | Write preference |
|---|---|---|---|---|
| `daily_traffic` | `date`, `sessionDefaultChannelGroup` | `sessions`, `totalUsers`, `newUsers`, `screenPageViews`, `engagementRate`, `keyEvents` | `date`, `session_default_channel_group` | upsert, overwrite |
| `pages` | `date`, `hostName`, `pagePath` | `screenPageViews`, `activeUsers`, `averageSessionDuration` | `date`, `host_name`, `page_path` | upsert, overwrite |
| `events` | `date`, `eventName` | `eventCount`, `totalUsers` | `date`, `event_name` | upsert, overwrite |
| `devices` | `date`, `deviceCategory`, `operatingSystem` | `sessions`, `totalUsers` | `date`, `device_category`, `operating_system` | upsert, overwrite |
| `geography` | `date`, `country`, `region`, `city` | `sessions`, `totalUsers` | `date`, `country`, `region`, `city` | upsert, overwrite |
| `acquisition` | `date`, `sessionSource`, `sessionMedium`, `sessionCampaignName` | `sessions`, `totalUsers`, `keyEvents` | `date`, `session_source`, `session_medium`, `session_campaign_name` | upsert, overwrite |

`runReport` returns each row positionally — `dimensionValues` and
`metricValues` arrays in the order the request listed the dimensions and
metrics. Each stream declares its lists once (YAML anchors) and the
`zip_columns` transform names every cell from those same lists, then the keys
are snake_cased: `sessionDefaultChannelGroup` lands as
`session_default_channel_group`. A row whose width differs from its list fails
the run rather than putting a value under the wrong column. GA4 returns every
value as a string (`date` as `YYYYMMDD`, `engagementRate` as a decimal
string); add a `cast` transform in a copy if you want typed columns.

**Rolling window.** Every stream re-reads `report_window` (`7daysAgo`,
`14daysAgo`, `30daysAgo` or `90daysAgo`, default 30) up to yesterday on each
run and upserts on the dimensions, because GA4 keeps processing a day's data
for up to 72 hours and attribution settles later still. History older than
the window stays in the table. For a backfill, copy the template and set a
fixed `dateRanges` (`startDate: 2023-01-01`, `endDate: 2023-12-31`). On a sink
without upsert (JSON Lines) each run rewrites the window.

**Thresholding and sampling.** GA4 may withhold rows for small user counts
(data thresholds, with Google signals on) and returns `(other)` for
high-cardinality dimensions such as `pagePath` over large windows; the numbers
match the GA4 UI's explorations, not raw event counts.

## Required permissions

- A Google user with at least **Viewer** on the GA4 property.
- An OAuth client (Google Cloud console) with the **Google Analytics Data API**
  enabled, and a refresh token for that user with the `analytics.readonly`
  scope.

## Rate limits and run times

Each request returns up to `report_page_size` rows (default 100,000; GA4
allows 250,000), paged by `offset`/`limit` in the request body. Standard
properties get 200,000 core tokens per day and 40,000 per hour; a report
costs roughly 10 tokens plus more for wide windows and high-cardinality
dimensions, and `429 RESOURCE_EXHAUSTED` is retried with backoff
(`max_retries: 6`). A typical property finishes in under a minute; `pages`
over 90 days on a large site (a few hundred thousand rows) takes a few
requests and a couple of minutes.

## Testing

- `tests/faucet-hq/google-analytics-4/replay.yaml` — recorded exchanges
  (values synthetic): the refresh-token grant (form fields asserted), then one
  `runReport` per stream with `report_page_size=2`, so `daily_traffic` pages
  through the body offset and an empty report (`events`) yields nothing.
  `python3 scripts/replay.py faucet-hq/google-analytics-4` compares the zipped
  records with `expected/`.
- `tests/faucet-hq/google-analytics-4/suite.yaml` — `faucet template test`
  suite: every `report_window` value, a rejected value, a raw report row zipped
  to named columns, and a narrower row failing the page.
- **Live smoke (manual):** `faucet run --source faucet-hq/google-analytics-4
  --sink faucet-hq/sqlite --param ga4_property_id=… …`.

## Changelog

- **v1** — first release: 6 daily report streams, Data API `v1beta`, a rolling
  window. Requires a faucet build with `zip_columns` column groups.
