# faucet-hq/google-ads

Google Ads API **v25** (released July 2026, sunset August 2027 per the
[deprecation schedule](https://developers.google.com/google-ads/api/docs/sunset-dates)),
reading Google Ads Query Language reports through
`GoogleAdsService.Search` over REST, **one customer account per run**.
Written from the [Google Ads API documentation](https://developers.google.com/google-ads/api/docs/start).

```bash
faucet run --source faucet-hq/google-ads --sink faucet-hq/bigquery \
  --param google_ads_customer_id=1234567890 --param google_ads_login_customer_id=9876543210 \
  --param-env google_ads_developer_token=GADS_DEV_TOKEN --param-env google_client_id=GADS_CLIENT_ID \
  --param-env google_client_secret=GADS_CLIENT_SECRET --param-env google_refresh_token=GADS_REFRESH_TOKEN \
  --param bq_project=my-project --param bq_sa_key="$BQ_SA_KEY"
```

## Authentication

Every request carries ([REST authorization](https://developers.google.com/google-ads/api/rest/auth)):

- `Authorization: Bearer …` — an OAuth 2.0 access token, minted here from a
  **refresh token** (`oauth2_refresh` provider against
  `https://oauth2.googleapis.com/token`) for a user with access to the
  account, scope `https://www.googleapis.com/auth/adwords`
  ([single-user authentication workflow](https://developers.google.com/google-ads/api/docs/oauth/single-user-authentication)).
- `developer-token` — from the manager account's API Center.
- `login-customer-id` — the manager account the user reaches the account
  through (or the account itself with direct access). Ids are digits only.

## Streams

All streams `POST /v25/customers/{customer_id}/googleAds:search` with a GAQL
`query` ([search](https://developers.google.com/google-ads/api/rest/common/search)).
Columns are the selected fields flattened to snake_case
(`campaign.advertising_channel_type` → `campaign_advertising_channel_type`),
with the `metrics_` / `segments_` prefixes dropped (`cost_micros`, `date`);
ids stay strings (int64 in JSON), metrics are cast to integers/floats.

| Stream | `FROM` resource | Rows | Primary key | Write | Docs |
|---|---|---|---|---|---|
| `customer` | `customer` | the account | customer_id | overwrite, upsert | [customer](https://developers.google.com/google-ads/api/fields/v25/customer) |
| `campaigns` | `campaign` | every campaign | customer_id, campaign_id | overwrite, upsert | [campaign](https://developers.google.com/google-ads/api/fields/v25/campaign) |
| `ad_groups` | `ad_group` | every ad group | customer_id, ad_group_id | overwrite, upsert | [ad_group](https://developers.google.com/google-ads/api/fields/v25/ad_group) |
| `ads` | `ad_group_ad` | every ad | customer_id, ad_group_id, ad_group_ad_ad_id | overwrite, upsert | [ad_group_ad](https://developers.google.com/google-ads/api/fields/v25/ad_group_ad) |
| `keywords` | `ad_group_criterion` (`type = 'KEYWORD'`) | every keyword | customer_id, ad_group_id, ad_group_criterion_criterion_id | overwrite, upsert | [ad_group_criterion](https://developers.google.com/google-ads/api/fields/v25/ad_group_criterion) |
| `campaign_performance` | `campaign` + `segments.date` | campaign × day | customer_id, date, campaign_id | upsert, append | [campaign](https://developers.google.com/google-ads/api/fields/v25/campaign) |
| `ad_group_performance` | `ad_group` + `segments.date` | ad group × day | customer_id, date, ad_group_id | upsert, append | [ad_group](https://developers.google.com/google-ads/api/fields/v25/ad_group) |
| `ad_performance` | `ad_group_ad` + `segments.date` | ad × day | customer_id, date, ad_group_id, ad_group_ad_ad_id | upsert, append | [ad_group_ad](https://developers.google.com/google-ads/api/fields/v25/ad_group_ad) |
| `keyword_performance` | `keyword_view` + `segments.date` | keyword × day | customer_id, date, ad_group_id, ad_group_criterion_criterion_id | upsert, append | [keyword_view](https://developers.google.com/google-ads/api/fields/v25/keyword_view) |
| `search_terms` | `search_term_view` + `segments.date` | search term × keyword × day | customer_id, date, ad_group_id, search_term_view_search_term, keyword_info_text, keyword_info_match_type | upsert, append | [search_term_view](https://developers.google.com/google-ads/api/fields/v25/search_term_view) |

Performance metrics: `impressions`, `clicks`, `cost_micros`, `interactions`,
`conversions`, `conversions_value`, `all_conversions`,
`view_through_conversions`. The field choices follow the
[query cookbook](https://developers.google.com/google-ads/api/docs/query/cookbook)
(the queries behind the Google Ads UI's overview screens), plus ids for keys.
`campaign.start_date_time` / `end_date_time` are the v25 names.

### How rows are read

- **Search, not SearchStream.** Search returns fixed 10,000-row pages with a
  `nextPageToken` that is absent on the last page
  ([paging](https://developers.google.com/google-ads/api/docs/reporting/paging));
  each page is written as it arrives, so memory stays bounded. SearchStream
  returns the whole result as one HTTP response, which this source would parse
  in full before writing anything.
- **Performance streams re-read a rolling window.** `google_ads_date_filter`
  (default `DURING LAST_30_DAYS`, which excludes today —
  [date ranges](https://developers.google.com/google-ads/api/docs/query/date-ranges))
  is re-read every run and upserted on the date + dimension key, because
  conversions are credited back to the click's date for the length of the
  conversion window (30 days by default, up to 90). With 90-day windows, pass
  `BETWEEN '<90 days ago>' AND '<yesterday>'`; for a backfill pass any
  `BETWEEN` range once. The window is stateless — no `state:` needed.
- **Entity streams are full refreshes** (GAQL has no change feed on these
  resources short of `change_status`). Removed entities stay in the results
  with `status = REMOVED`, so deletes are visible as a status.
- Metrics with `segments.date` return only days with activity.

## Quotas and run time

[Quotas](https://developers.google.com/google-ads/api/docs/best-practices/quotas):
the developer token's access level caps daily operations — Explorer 2,880/day
against production accounts, Basic 15,000/day, Standard unlimited; exhaustion
answers `RESOURCE_EXHAUSTED` (HTTP 429), which the source retries with
backoff. One page is one request: a run is 10 requests plus one per extra
10,000 rows — seconds for a typical account; `search_terms` over 30 days is
the largest stream (can be hundreds of thousands of rows on big accounts).

## Tests

- `tests/faucet-hq/google-ads/suite.yaml` — parameter-space suite (rolling
  window and backfill range) plus a behavioral case flattening a
  `GoogleAdsRow`.
- `tests/faucet-hq/google-ads/replay.yaml` — the refresh-token exchange,
  every stream's GAQL query, the documented headers, and two-page
  `pageToken` paging on `campaign_performance`.

## Live smoke test

```bash
faucet run --source faucet-hq/google-ads --sink faucet-hq/jsonl \
  --param google_ads_customer_id=1234567890 --param google_ads_login_customer_id=1234567890 \
  --param-env google_ads_developer_token=GADS_DEV_TOKEN --param-env google_client_id=GADS_CLIENT_ID \
  --param-env google_client_secret=GADS_CLIENT_SECRET --param-env google_refresh_token=GADS_REFRESH_TOKEN \
  --param google_ads_date_filter="DURING LAST_7_DAYS" --param out_dir=./out
```

## Changelog

- **v1** — first version, written from the v25 documentation. Needs a faucet
  release with the `oauth2_refresh` shared provider, `CursorInBody` paging and
  static request `headers`.
