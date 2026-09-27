# faucet-hq/stripe

Stripe payments, billing and balance data through the Stripe REST API, one
table per object.

```bash
faucet hub check --source faucet-hq/stripe --sink faucet-hq/bigquery
faucet run --source faucet-hq/stripe --sink faucet-hq/postgres \
  --param stripe_api_key="$STRIPE_API_KEY" --param pg_url="$PG_URL" \
  --overlay ops/prod.yaml          # a deployment overlay with `state:` for the incremental streams
```

- **API version:** pinned to `2024-06-20` with the `Stripe-Version` header, so
  a change to your account's default version never changes the records. A bump
  is a new template version (see the changelog).
- **Auth:** `stripe_api_key` — a secret key, or better a **restricted key**
  with *Read* on the resources below. Test-mode keys (`sk_test_…`) read test
  data.

## Streams

| Stream | Endpoint | Sync | Primary key | Write preference |
|---|---|---|---|---|
| `customers` | `GET /v1/customers` | full refresh | `id` | overwrite, upsert |
| `subscriptions` | `GET /v1/subscriptions?status=all` | full refresh | `id` | overwrite, upsert |
| `invoices` | `GET /v1/invoices` | full refresh | `id` | overwrite, upsert |
| `charges` | `GET /v1/charges` | full refresh | `id` | overwrite, upsert |
| `refunds` | `GET /v1/refunds` | full refresh | `id` | overwrite, upsert |
| `payment_intents` | `GET /v1/payment_intents` | full refresh | `id` | overwrite, upsert |
| `products` | `GET /v1/products` | full refresh | `id` | overwrite, upsert |
| `prices` | `GET /v1/prices` | full refresh | `id` | overwrite, upsert |
| `payouts` | `GET /v1/payouts` | full refresh | `id` | overwrite, upsert |
| `balance_transactions` | `GET /v1/balance_transactions` | incremental on `created` (`created[gt]` pushed down) | `id` | upsert, overwrite |
| `events` | `GET /v1/events` | incremental on `created` (`created[gt]` pushed down) | `id` | upsert, overwrite |

Every list is paged 100 at a time with `starting_after` (the last object id of
the previous page). Records are written as Stripe returns them — nested objects
(`metadata`, `items`, `recurring`, …) stay nested; the warehouse sinks store
them as JSON columns.

**Why most streams are full refresh.** Stripe list endpoints filter on
`created`, not on last-modified, and customers, subscriptions, invoices and
charges change after they are created (status, refunds, dunning). A
`created`-cursor would miss those updates, so these streams re-read the object
set each run and replace the table. Balance transactions are immutable, so an
incremental cursor on `created` is exact. `events` is the change feed: Stripe
keeps 30 days of events, so run it at least that often.

Incremental streams need a `state:` store (a deployment overlay); without one
they re-read everything each run, which `faucet validate` warns about.

## Required permissions

A restricted key with **Read** on: Customers, Subscriptions, Invoices, Charges
(includes Refunds), PaymentIntents, Products, Prices, Payouts, Balance
(balance transactions), Events. Nothing is written.

## Rate limits and run times

Stripe allows 100 read requests per second in live mode (25 in test mode).
Up to four streams run at once by default (`execution.max_concurrent` in a
deployment overlay changes it), one request in flight per stream, and each
request returns up to 100 objects — so a stream reads roughly 3,000–10,000 objects a
minute depending on object size. An account with 1 M charges takes ~2–5
minutes for `charges`; the first `balance_transactions` / `events` run reads
all history (events: 30 days), later runs only what is new. A `429` is retried
with backoff (`max_retries: 5`).

## Testing

- `tests/faucet-hq/stripe/replay.yaml` — recorded request/response exchanges
  (shapes from the API reference, values synthetic). `python3 scripts/replay.py
  faucet-hq/stripe` serves them locally, runs every stream twice through the
  real REST source (the second run proves the `created[gt]` resume), and
  compares the written records with `tests/faucet-hq/stripe/expected/`.
- `tests/faucet-hq/stripe/suite.yaml` — `faucet template test` parameter-space
  suite (validation + a behavioural case).
- **Live smoke (manual, never in CI):** with a test-mode restricted key,
  `faucet run --source faucet-hq/stripe --sink faucet-hq/sqlite --param stripe_api_key="$STRIPE_TEST_KEY"`
  and check `./out/faucet.db` has a table per stream.

## Changelog

- **v1** — first release: 11 streams, API version `2024-06-20`,
  `balance_transactions` and `events` incremental on `created`.
