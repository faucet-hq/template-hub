# faucet-hq/meta-ads

A Meta (Facebook / Instagram) ad account — its structure and daily ad-level
performance — through the Marketing API. Insights are pulled with an
**asynchronous report run**, the method Meta recommends for anything larger
than a few days of one campaign.

```bash
faucet hub check --source faucet-hq/meta-ads --sink faucet-hq/bigquery
faucet run --source faucet-hq/meta-ads --sink faucet-hq/bigquery \
  --param meta_ad_account_id=1234567890 --param meta_access_token="$META_ACCESS_TOKEN" \
  --param bq_project=my-project --param bq_sa_key="$BQ_SA_KEY"
```

- **API version:** Graph/Marketing API `v24.0`, pinned in every path. Meta
  supports a version for about two years; the changelog records bumps.
- **Auth:** an access token sent as `Authorization: Bearer`. Use a **system
  user** token from Business Manager (it does not expire) rather than a user
  token (60 days).

## Streams

| Stream | Endpoint | Sync | Primary key | Write preference |
|---|---|---|---|---|
| `ad_account` | `GET /v24.0/act_{id}` | full refresh (one record) | `id` | overwrite, upsert |
| `campaigns` | `GET /v24.0/act_{id}/campaigns` | full refresh | `id` | overwrite, upsert |
| `ad_sets` | `GET /v24.0/act_{id}/adsets` | full refresh | `id` | overwrite, upsert |
| `ads` | `GET /v24.0/act_{id}/ads` | full refresh | `id` | overwrite, upsert |
| `ad_creatives` | `GET /v24.0/act_{id}/adcreatives` | full refresh | `id` | overwrite, upsert |
| `ad_insights` | `POST /v24.0/act_{id}/insights` (async, `level=ad`, `time_increment=1`) | rolling window | `ad_id`, `date_start` | upsert, overwrite |

Entity lists page 500 at a time through `paging.next` and return objects that
are not deleted (archived ones included). Insights are one row per ad per day
with delivery, cost and `actions` / `action_values` (arrays of
`{action_type, value}`, kept nested). Graph returns numbers as strings
(`"12.25"`); money is in the account currency.

**Rolling window.** `ad_insights` re-reads `insights_window` (`last_7d`,
`last_14d`, `last_28d` — the default, matching Meta's attribution window —
`last_30d` or `last_90d`) every run and upserts on ad + day, so late-attributed
conversions update earlier days while older history stays in the table.

## Required permissions

The token needs the **`ads_read`** permission (and `business_management` to
read through a business), and the system user must be assigned to the ad
account with at least the *Analyze* task. The app must have **Ads Management
Standard Access** for production-scale rate limits.

## Rate limits and run times

Marketing API limits are per ad account and scored by call cost; heavy use
returns error code 17/80004 with HTTP 400 or `429`. `429` is retried with
backoff (`max_retries: 8`, base 5 s); a throttle surfaced as HTTP 400 fails the
run — rerun later or narrow the window. The insights report run typically
completes in 10 s – 5 min (polled every 1 s, backing off to 15 s, up to 1 h);
results are then read 500 rows per page — an account with 2,000 active ads
over 28 days (~56,000 rows) reads in about 2 minutes.

## Testing

- `tests/faucet-hq/meta-ads/replay.yaml` — recorded exchanges (values
  synthetic): entity lists through `paging.next`, and the insights report run
  submitted, polled to `Job Completed` and read through
  `paging.cursors.after`. `python3 scripts/replay.py faucet-hq/meta-ads`.
- `tests/faucet-hq/meta-ads/suite.yaml` — `faucet template test` suite: every
  `insights_window` value and a rejected one.
- **Live smoke (manual):** with a system-user token on a test ad account,
  `faucet run --source faucet-hq/meta-ads --sink faucet-hq/sqlite --param meta_ad_account_id=… --param meta_access_token="$T" --param insights_window=last_7d`.

## Changelog

- **v1** — first release: 6 streams, Marketing API `v24.0`, insights via async
  report runs over a rolling window.
