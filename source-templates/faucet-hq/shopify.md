# faucet-hq/shopify

Shopify **GraphQL Admin API, version `2026-07`** (the latest stable version;
each is supported for at least 12 months —
[versioning](https://shopify.dev/docs/api/usage/versioning)), one store per
run. Written from the [GraphQL Admin API reference](https://shopify.dev/docs/api/admin-graphql).

```bash
faucet run --source faucet-hq/shopify --sink faucet-hq/postgres \
  --param shopify_shop_url=https://demo-store.myshopify.com \
  --param-env shopify_client_id=SHOPIFY_CLIENT_ID --param-env shopify_client_secret=SHOPIFY_CLIENT_SECRET \
  --param pg_url="$PG_URL" --overlay ops/state.yaml
```

## Why GraphQL, and why not Bulk Operations (yet)

Shopify lists the REST Admin API as **legacy**; the GraphQL Admin API is the
supported surface. For very large reads Shopify recommends
[bulk operations](https://shopify.dev/docs/api/usage/bulk-operations/queries),
which "don't have the max cost limits or rate limits that single queries
have". This template uses ordinary paginated queries instead, because the
engine cannot yet express a bulk operation end to end (see *Engine gaps*
below). Every stream is incremental or small, so steady-state runs read only
what changed.

## Authentication

The [client credentials grant](https://shopify.dev/docs/apps/build/authentication-authorization/access-tokens/client-credentials-grant):
an app created in the **Dev Dashboard** and installed on a store in the same
Shopify organization exchanges its client id and secret at
`POST https://{shop}.myshopify.com/admin/oauth/access_token`
(`grant_type=client_credentials`, form-encoded) for a token valid 24 hours,
sent as `X-Shopify-Access-Token`. The token is fetched once per run and
re-fetched on expiry.

Access scopes to grant the app: `read_orders` (plus `read_all_orders` for
orders older than 60 days), `read_customers`, `read_products`,
`read_locations`. Customer names, emails and addresses are protected customer
data: the app needs protected-customer-data access for those fields.

## Streams

| Stream | Query | Cursor (server-side filter) | Sort | Page size | Primary key | Write | Docs |
|---|---|---|---|---|---|---|---|
| `orders` | `orders` | `updatedAt` → `query: "updated_at:>'…'"` | `UPDATED_AT` | 50 | `id` | upsert, append | [orders](https://shopify.dev/docs/api/admin-graphql/2026-07/queries/orders) |
| `customers` | `customers` | `updatedAt` → `updated_at:>` | `UPDATED_AT` | 200 | `id` | upsert, append | [customers](https://shopify.dev/docs/api/admin-graphql/2026-07/queries/customers) |
| `products` | `products` | `updatedAt` → `updated_at:>` | `UPDATED_AT` | 150 | `id` | upsert, append | [products](https://shopify.dev/docs/api/admin-graphql/2026-07/queries/products) |
| `product_variants` | `productVariants` | `updatedAt` → `updated_at:>` | `ID` | 250 | `id` | upsert, append | [productVariants](https://shopify.dev/docs/api/admin-graphql/2026-07/queries/productVariants) |
| `collections` | `collections` | — (full refresh) | `UPDATED_AT` | 250 | `id` | overwrite, upsert | [collections](https://shopify.dev/docs/api/admin-graphql/2026-07/queries/collections) |
| `locations` | `locations` | — (full refresh) | — | 250 | `id` | overwrite, upsert | [locations](https://shopify.dev/docs/api/admin-graphql/2026-07/queries/locations) |
| `deleted_products` | `events` (`action:'destroy' AND subject_type:'PRODUCT'`) | `createdAt` → `created_at:>` | `CREATED_AT` | 250 | `id` | upsert, append | [events](https://shopify.dev/docs/api/admin-graphql/2026-07/queries/events) |

Pagination is Relay cursors (`pageInfo { hasNextPage endCursor }` →
`$after`, [pagination](https://shopify.dev/docs/api/usage/pagination-graphql)).
Nested objects are flattened with `_` (`total_price_set_shop_money_amount`,
`customer_id`, `billing_address_country_code_v2`); `tags` is a JSON array
string. Ids are Shopify global ids (`gid://shopify/Order/…`).

### Choices, from the docs

- **Every incremental filter is a documented search field** (`updated_at`
  on orders, customers, products, variants; `created_at` on events), sorted
  by the same key where a sort key exists ("try specifying a sort key that
  matches the field used in the search"). Pages then walk forward in time, so
  the bookmark — the largest `updatedAt` written, bound into `$query` on the
  next run — is safe even if a run stops early.
- **Page sizes keep the requested cost under 1,000 points** — the single-query
  limit, checked against the *requested* cost before execution
  ([rate limits](https://shopify.dev/docs/apps/build/apis/graphql-admin/rate-limits)).
  A connection costs 2 points plus one per object requested, so an order with
  its seven money sets and two addresses is ~13 points: 50 per page.
- **Deletes**: `deleted_products` records product destroy events (events are
  kept for one year; `deletionEvents` is deprecated in favour of `events`).
  Deleted orders and customers are not exposed by these queries.
- **`customers` `updated_at` matches a whole day** (per the query reference),
  so a run re-reads that day's already-seen customers; the upsert absorbs it.
- **Order line items, refunds, fulfillments and inventory levels are not
  included**: a nested connection multiplies the requested cost by its page
  size (50 orders × 50 line items is over the 1,000-point limit), so they
  need bulk operations.

## Rate limits and throttling

Cost-based leaky bucket per app and store: 100 points/second (Standard),
200 (Advanced), 1,000 (Plus), 2,000 (Commerce Components). A throttled query
answers **HTTP 200** with `errors[].extensions.code = "THROTTLED"`. The
GraphQL source fails the run on any `errors[]` response before a bookmark is
written, so a throttle never loses data, but it is not retried (see *Engine
gaps*). At the page sizes above a Standard store sustains roughly 500 orders
or 3,000 customers a minute; steady-state incremental runs take seconds.

Shopify also caps pagination of a list at 25,000 objects
([limits](https://shopify.dev/docs/api/usage/limits)). Because every
incremental stream is sorted by its cursor, a stream that stops there resumes
from its bookmark on the next run; a first sync of a very large store
therefore takes several runs (or bulk operations, once supported).

## State

`orders`, `customers`, `products`, `product_variants` and `deleted_products`
keep their bookmarks in the run's `state:` store; supply one with a deployment
overlay or they re-read from `shopify_start_date` every run.

## Tests

- `tests/faucet-hq/shopify/suite.yaml` — parameter-space suite plus a
  behavioral case flattening an order.
- `tests/faucet-hq/shopify/replay.yaml` — the client-credentials exchange,
  every stream's query and variables, cursor paging over two pages (orders),
  and a second run that binds each bookmark into `$query`.

## Engine gaps

- **2xx throttling.** `THROTTLED` arrives as HTTP 200 with a GraphQL error;
  neither the GraphQL source's retry nor `retry_on_response` (non-2xx only)
  can retry it. Needed: a matcher on `errors[].extensions.code` for 2xx bodies.
- **Bulk operations.** `async_job` can submit `bulkOperationRunQuery`, but its
  poll is a URL with no request body, while Shopify's status check is a
  GraphQL `POST`; its incremental push-down injects a SQL `WHERE`, not a
  search-syntax filter; and the JSONL result needs `__parentId` lines routed
  to child tables.

## Live smoke test

```bash
faucet run --source faucet-hq/shopify --sink faucet-hq/jsonl \
  --param shopify_shop_url=https://demo-store.myshopify.com \
  --param-env shopify_client_id=SHOPIFY_CLIENT_ID --param-env shopify_client_secret=SHOPIFY_CLIENT_SECRET \
  --param shopify_start_date="2026-09-01T00:00:00Z" --param out_dir=./out
```

## Changelog

- **v1** — first version, written from the 2026-07 GraphQL Admin API
  reference. Needs a faucet release with GraphQL incremental replication
  (`replication_bind` into a variable) and the `token_endpoint` provider's
  form encoding and `apply_as` header.
