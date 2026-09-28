# faucet-hq/stripe

Stripe's core billing and payments objects over the v1 REST API, pinned to
API version **`2026-08-26.dahlia`**
([versioning](https://docs.stripe.com/api/versioning)).

```bash
faucet run --source faucet-hq/stripe --sink faucet-hq/bigquery \
  --param stripe_api_key="$STRIPE_API_KEY" \
  --param bq_project=my-project --param bq_sa_key="$BQ_SA_KEY" \
  --overlay my-state.yaml          # a state: block, so the windowed streams resume
```

## Authentication

Bearer authentication with a **restricted API key** (`rk_live_…`), which
Stripe recommends over the full secret key for any integration that only needs
a subset of the API ([API keys](https://docs.stripe.com/keys),
[restricted keys](https://docs.stripe.com/keys#limit-access)). Grant **Read**
on: Customers, Subscriptions, Invoices, Charges, Refunds, PaymentIntents,
Products, Prices, Payouts, Disputes, Balance transactions (under *Balance*),
and Events. Nothing is written.

Every request carries `Stripe-Version: 2026-08-26.dahlia`, so the record shape
does not change when the account's default version is upgraded. Override it
with `--param stripe_api_version=…`. Event payloads are the exception: each
event's `data.object` is rendered in the version the event was created with
(its `api_version` field) — [list events](https://docs.stripe.com/api/events/list).

## Streams

All list endpoints share Stripe's cursor pagination: `limit=100` (the
maximum), then `starting_after=<id of the last object>` until a page comes
back empty ([pagination](https://docs.stripe.com/api/pagination)).

| Stream | Endpoint | Doc | Sync | Cursor | Primary key |
|---|---|---|---|---|---|
| customers | `GET /v1/customers` | [list customers](https://docs.stripe.com/api/customers/list) | full refresh | — | `id` |
| subscriptions | `GET /v1/subscriptions?status=all` | [list subscriptions](https://docs.stripe.com/api/subscriptions/list) | full refresh | — | `id` |
| invoices | `GET /v1/invoices` | [list invoices](https://docs.stripe.com/api/invoices/list) | full refresh | — | `id` |
| charges | `GET /v1/charges` | [list charges](https://docs.stripe.com/api/charges/list) | full refresh | — | `id` |
| refunds | `GET /v1/refunds` | [list refunds](https://docs.stripe.com/api/refunds/list) | full refresh | — | `id` |
| payment_intents | `GET /v1/payment_intents` | [list payment intents](https://docs.stripe.com/api/payment_intents/list) | full refresh | — | `id` |
| products | `GET /v1/products` | [list products](https://docs.stripe.com/api/products/list) | full refresh | — | `id` |
| prices | `GET /v1/prices` | [list prices](https://docs.stripe.com/api/prices/list) | full refresh | — | `id` |
| payouts | `GET /v1/payouts` | [list payouts](https://docs.stripe.com/api/payouts/list) | full refresh | — | `id` |
| disputes | `GET /v1/disputes` | [list disputes](https://docs.stripe.com/api/disputes/list) | full refresh | — | `id` |
| balance_transactions | `GET /v1/balance_transactions` | [list balance transactions](https://docs.stripe.com/api/balance_transactions/list) | incremental | `created` window | `id` |
| events | `GET /v1/events` | [list events](https://docs.stripe.com/api/events/list) | incremental | `created` window | `id` |

**Why most streams are full refresh.** Stripe's list endpoints filter only on
`created`, and these objects change after creation (an invoice is paid, a
charge refunded, a subscription canceled). A `created` filter would never see
those updates, so the stream re-reads the object list each run and replaces the
table (`[overwrite, upsert]`). `subscriptions` passes `status=all` because the
endpoint omits canceled subscriptions by default.

**Incremental streams.** Balance transactions are immutable ledger entries and
events are an append-only log, so both are read by `created` window:
`created[gte]` / `created[lt]` bound each request (both documented filters),
the window end is persisted as the bookmark, and each run re-reads the last hour
(`lookback: 1h`) so an object that became visible late is still picked up; the
upsert on `id` absorbs the overlap. The first run starts at
`stripe_start_date` (default 2011-01-01, i.e. everything) in 365-day windows.

**Deletes.** A deleted customer, product, price or coupon disappears from its
list, so the full-refresh overwrite drops it. The `events` stream records every
deletion as it happens (`customer.deleted`, `product.deleted`,
`price.deleted`, … — [types of events](https://docs.stripe.com/api/events/types))
for downstream history. Stripe retains events for **30 days**: run the template
at least that often, or older changes are gone from `/v1/events`.

## Rate limits and run time

Stripe allows 100 read requests per second per account in live mode (25 in a
sandbox) and 25 per second per endpoint, and answers `429 Too Many Requests`
with a `Stripe-Rate-Limited-Reason` header when a limit is hit
([rate limits](https://docs.stripe.com/rate-limits)); `429` also signals a
transient object-lock timeout. The template retries `429` with exponential
backoff (up to 6 attempts, `Retry-After` honoured when present) and reads
streams one page at a time, well under the per-endpoint limit. Accounts also
have a monthly read allocation of about 500 GET requests per transaction
(minimum 10,000) — a full sync of an account with *N* objects costs roughly
*N* / 100 requests, plus one per stream.

At 100 objects per request and ~3–5 requests per second, expect about
20,000–30,000 objects per minute per stream; a 1-million-object account's first
sync takes around 45 minutes, and later runs of the windowed streams take
seconds.

## Live smoke test

With a sandbox restricted key:

```bash
faucet run --source faucet-hq/stripe --sink faucet-hq/jsonl \
  --param stripe_api_key="$STRIPE_TEST_KEY" --param out_dir=./out
wc -l out/stripe/*.jsonl
```

## Limitations

- Stripe's list response carries `has_more`; the REST source's cursor
  pagination stops on an empty page instead, so each stream makes one extra,
  empty request at the end.
- Nested sub-lists that Stripe truncates at 10 items inside a list response
  (for example `subscription.items`, `invoice.lines`) are stored as returned;
  expanding them fully needs per-object follow-up requests.

## Changelog

- **v1** — first release, built from the Stripe API reference: twelve streams,
  `Stripe-Version` pinned to `2026-08-26.dahlia`, windowed incremental
  `balance_transactions` and `events`.
