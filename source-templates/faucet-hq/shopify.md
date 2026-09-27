# faucet-hq/shopify

A Shopify store's orders, customers, products, collections and locations
through the Admin REST API.

```bash
faucet hub check --source faucet-hq/shopify --sink faucet-hq/bigquery
faucet run --source faucet-hq/shopify --sink faucet-hq/bigquery \
  --param shopify_store_url=https://acme.myshopify.com --param shopify_access_token="$SHOPIFY_TOKEN" \
  --param bq_project=my-project --param bq_sa_key="$BQ_SA_KEY" --overlay ops/prod.yaml
```

- **API version:** `2025-07`, pinned in every path. Shopify supports each
  version for at least 12 months; a bump is a new template version.
- **Auth:** a **custom app** Admin API access token (`shpat_…`), sent as
  `X-Shopify-Access-Token`. Shopify marks the REST Admin API as legacy and
  requires GraphQL for *new public apps*; custom apps created in a store's admin
  can still use REST, which is what this template does.

## Streams

| Stream | Endpoint | Sync | Primary key | Write preference |
|---|---|---|---|---|
| `orders` | `GET /admin/api/2025-07/orders.json?status=any` | incremental on `updated_at` (`updated_at_min` pushed down) | `id` | upsert, overwrite |
| `customers` | `GET /admin/api/2025-07/customers.json` | incremental on `updated_at` | `id` | upsert, overwrite |
| `products` | `GET /admin/api/2025-07/products.json` | incremental on `updated_at` | `id` | upsert, overwrite |
| `custom_collections` | `GET /admin/api/2025-07/custom_collections.json` | full refresh | `id` | overwrite, upsert |
| `smart_collections` | `GET /admin/api/2025-07/smart_collections.json` | full refresh | `id` | overwrite, upsert |
| `locations` | `GET /admin/api/2025-07/locations.json` | full refresh | `id` | overwrite, upsert |

Pages are 250 records, followed through the `Link` header (the `page_info`
URL, which carries no other filters, as Shopify requires). Orders keep their
nested `line_items`, `refunds`, `shipping_lines`, … — the warehouse sinks store
them as JSON columns. The first run reads everything updated since
`start_date`; later runs resume from the last `updated_at` written, converted
to UTC.

Incremental streams need a `state:` store (a deployment overlay).

**Not included:** inventory levels (the endpoint is per location, and a
per-parent fan-out stream cannot use a full-refresh write mode safely — see the
hub issue tracker), and order transactions/fulfillment orders (per-order
endpoints; order `refunds` and `fulfillments` are already nested in `orders`).

## Required scopes

Custom app Admin API scopes: `read_orders` (add `read_all_orders` for orders
older than 60 days), `read_customers`, `read_products` (products and
collections), `read_locations`.

## Rate limits and run times

The REST Admin API allows 2 requests per second on standard plans (a bucket of
40), 20 per second on Shopify Plus; each request returns up to 250 records. A
store with 200,000 orders needs ~800 requests for `orders` — about 7 minutes on
a standard plan — for the first run; later runs usually need one or two
requests per stream. A `429` is retried after its `Retry-After`
(`max_retries: 8`).

## Testing

- `tests/faucet-hq/shopify/replay.yaml` — recorded exchanges (values
  synthetic); `python3 scripts/replay.py faucet-hq/shopify` replays two runs:
  orders page through the `Link` header, and the second run resumes with
  `updated_at_min=<last updated_at in UTC>`.
- `tests/faucet-hq/shopify/suite.yaml` — `faucet template test` suite.
- **Live smoke (manual):** against a development store,
  `faucet run --source faucet-hq/shopify --sink faucet-hq/sqlite --param shopify_store_url=… --param shopify_access_token="$T"`.

## Changelog

- **v1** — first release: 6 streams, Admin REST API `2025-07`; orders,
  customers and products incremental on `updated_at`.
