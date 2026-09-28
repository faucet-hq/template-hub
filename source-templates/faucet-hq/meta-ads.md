# faucet-hq/meta-ads

Meta Marketing API **v25.0** for **one ad account per run**: the account and
its campaigns, ad sets, ads and creatives from the Graph API edges, and daily
Insights through **asynchronous report runs**. Written from the
[Marketing API documentation](https://developers.facebook.com/docs/marketing-api).

v25.0 (February 2026) is the version the Marketing API reference pages use in
their examples today; v26.0 (July 2026) is newer
([changelog](https://developers.facebook.com/docs/graph-api/changelog)). Both
are supported; moving to v26.0 is a one-line change of the `/v25.0/` prefix
once its changes have been checked against these fields.

```bash
faucet run --source faucet-hq/meta-ads --sink faucet-hq/bigquery \
  --param meta_ad_account_id=1234567890 --param-env meta_access_token=META_TOKEN \
  --param bq_project=my-project --param bq_sa_key="$BQ_SA_KEY"
```

## Authentication

A **system-user access token** from Business Manager (Business Settings →
System users) with the `ads_read` permission and the ad account assigned —
the server-to-server token Meta recommends for automated reads
([access tokens](https://developers.facebook.com/docs/facebook-login/guides/access-tokens),
[permissions](https://developers.facebook.com/docs/permissions/)). A user token
with `ads_read` also works but expires. The token is sent as
`Authorization: Bearer …`.

## Streams

| Stream | Endpoint | Pagination | Cursor | Primary key | Write | Docs |
|---|---|---|---|---|---|---|
| `ad_account` | `GET /act_{id}` | — | — | `id` | overwrite, upsert | [Ad Account](https://developers.facebook.com/docs/marketing-api/reference/ad-account) |
| `campaigns` | `GET /act_{id}/campaigns` | `paging.next`, 500/page | — (full refresh) | `id` | overwrite, upsert | [campaigns edge](https://developers.facebook.com/docs/marketing-api/reference/ad-account/campaigns) |
| `ad_sets` | `GET /act_{id}/adsets` | `paging.next`, 500/page | — (full refresh) | `id` | overwrite, upsert | [adsets edge](https://developers.facebook.com/docs/marketing-api/reference/ad-account/adsets) |
| `ads` | `GET /act_{id}/ads` | `paging.next`, 500/page | — (full refresh) | `id` | overwrite, upsert | [ads edge](https://developers.facebook.com/docs/marketing-api/reference/ad-account/ads) |
| `ad_creatives` | `GET /act_{id}/adcreatives` | `paging.next`, 200/page | — (full refresh) | `id` | overwrite, upsert | [adcreatives edge](https://developers.facebook.com/docs/marketing-api/reference/ad-account/adcreatives) |
| `campaign_insights` | async `level=campaign` | report cursor `after` | rolling `date_preset` | campaign_id, date_start | upsert, append | [Insights](https://developers.facebook.com/docs/marketing-api/reference/ad-account/insights) |
| `ad_insights` | async `level=ad` | report cursor `after` | rolling `date_preset` | ad_id, date_start | upsert, append | [Insights](https://developers.facebook.com/docs/marketing-api/reference/ad-account/insights) |
| `ad_insights_age_gender` | async `level=ad`, `breakdowns=age,gender` | report cursor `after` | rolling `date_preset` | ad_id, date_start, age, gender | upsert, append | [breakdowns](https://developers.facebook.com/docs/marketing-api/insights/breakdowns) |
| `ad_insights_country` | async `level=ad`, `breakdowns=country` | report cursor `after` | rolling `date_preset` | ad_id, date_start, country | upsert, append | [breakdowns](https://developers.facebook.com/docs/marketing-api/insights/breakdowns) |
| `ad_insights_platform` | async `level=ad`, `breakdowns=publisher_platform,platform_position` | report cursor `after` | rolling `date_preset` | ad_id, date_start, publisher_platform, platform_position | upsert, append | [breakdowns](https://developers.facebook.com/docs/marketing-api/insights/breakdowns) |

Insights metrics: impressions, reach, clicks, inline_link_clicks, spend (the
campaign/ad streams add frequency, unique_clicks, cpc, cpm, ctr,
cost_per_action_type); `actions` / `action_values` stay JSON arrays of
`{action_type, value}`. Counts are cast to integers, money and rates to floats.

### How rows are read

- **Insights use async report runs** ([async jobs](https://developers.facebook.com/docs/marketing-api/insights/async),
  [best practices](https://developers.facebook.com/docs/marketing-api/insights/best-practices)):
  `POST /act_{id}/insights` returns a `report_run_id`; `GET /{report_run_id}`
  is polled (≤30 s apart, up to an hour) until `async_status` is
  `Job Completed` (`Job Failed` / `Job Skipped` fail the run); then
  `GET /{report_run_id}/insights?limit=500` is read page by page on
  `paging.cursors.after`. Meta recommends async for anything beyond small
  reads; synchronous Insights calls time out on large accounts.
- **Rolling window.** `time_increment=1` gives one row per day; the window is
  `meta_insights_date_preset` (default `last_28d`), re-read every run and
  upserted on the day + breakdown key, because "Insights refresh every 15
  minutes and do not change after 28 days of being reported". A backfill is
  a single run with a wider preset (`last_90d`, `this_year`, `maximum`).
  `use_unified_attribution_setting=true` reports each ad set's own
  attribution setting, matching Ads Manager.
- **Deletes.** The edges return only non-archived, non-deleted objects unless
  asked; every entity stream passes the full `effective_status` list, so
  deleted and archived objects stay in the table with that status.
- **Entities are full refreshes.** The ad-set and ads edges document an
  `updated_since` integer, but not its unit or whether it is inclusive, and the
  campaigns edge documents none; a full refresh with `overwrite` is the read
  the docs fully specify. Accounts with tens of thousands of ads read in a
  few dozen pages.

## Rate limits and throttling

[Rate limiting](https://developers.facebook.com/docs/marketing-api/overview/rate-limiting):
Business Use Case limits per ad account (error codes 80000, 80003, 80004,
80014), ad-account API limits (17 with subcode 2446079, 613), and app limits
(4). Throttling answers a Graph error — HTTP 400/403 whose `error.code` is
one of those — not a 429. The template retries those codes after 60 s, up to
5 times; `X-Business-Use-Case-Usage` carries the precise
`estimated_time_to_regain_access`. Insights report runs "can take up to an
hour", so a large account's run is dominated by report time; entity streams
are one request per 200–500 objects.

## Tests

- `tests/faucet-hq/meta-ads/suite.yaml` — parameter-space suite with one case
  per declared Insights window (`enum_coverage`) and a rejected one.
- `tests/faucet-hq/meta-ads/replay.yaml` — Bearer auth, `paging.next` paging
  (campaigns), every Insights report run: submit → poll → fetch, with cursor
  paging over three pages on `ad_insights`.
- Throttling: a local server answering HTTP 400 `error.code: 80004` then a
  plain HTTP 400 error showed the first retried after 60 s and the second
  surfaced as an error (`throttled 1×`).

## Live smoke test

```bash
faucet run --source faucet-hq/meta-ads --sink faucet-hq/jsonl \
  --param meta_ad_account_id=1234567890 --param-env meta_access_token=META_TOKEN \
  --param meta_insights_date_preset=last_7d --param out_dir=./out
```

## Changelog

- **v1** — first version, written from the v25.0 documentation. Needs a
  faucet release with `retry_on_response` (JSON body matchers), `async_job`
  with a body-cursor locator, and `sources:` named connectors.
