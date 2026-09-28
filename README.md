# faucet-stream Template Hub

The shared catalog of **source templates** and **sink templates** for
[faucet-stream](https://github.com/faucet-hq/faucet-stream). A source template
describes one system once — auth, pagination, incremental cursors, the record
shape, and the **streams** (tables) it produces, each with the write semantics
it needs. A sink template describes one destination. Any source composes with
any sink at run time, so a template written for one warehouse works for every
other destination in this catalog.

Browse it: **<https://faucet-hq.github.io/hub>** · matrix + copy-paste commands
in [`index.json`](./index.json).

## Use a template

The CLI reads this repository directly — no clone:

```bash
faucet hub list                                        # default hub = this repository
faucet hub check --source faucet-hq/example-rest-api --sink faucet-hq/bigquery
faucet run       --source faucet-hq/example-csv --sink faucet-hq/jsonl     # runs offline
faucet run       --source <owner>/<name> --sink faucet-hq/bigquery \
  --param api_token="$TOKEN" --param bq_project=my-project --param bq_sa_key="$BQ_SA_KEY"
```

`--hub` / `FAUCET_HUB` accept a local directory, `github:owner/repo[@ref][/path]`,
or a GitHub URL; the remote catalog is cached under `~/.cache/faucet/hub/` and
reused offline. A local `./hub` directory, when present, takes precedence.

Mirror the catalog into a running `faucet serve` (the console's Templates view
then lists every template, with a sink selector per source):

```yaml
# hub-sync.yaml
version: 1
origins:
  - name: hub
    source:
      type: github
      config: { repo: faucet-hq/template-hub, paths: [source-templates, sink-templates] }
    launch: always
```

```bash
faucet serve --history sqlite:./faucet.db --templates-sync hub-sync.yaml
```

Or register one template into a registry by hand:

```bash
faucet template register source-templates/example-rest-api.yaml --launch
faucet template run faucet-hq/example-rest-api --sink faucet-hq/bigquery --param api_token="$TOKEN" …
```

## Official templates

The `faucet-hq/` namespace is the maintained set. Each source template has a
README beside it (`source-templates/faucet-hq/<name>.md` — required scopes,
run times, changelog), a `faucet template test` suite and recorded API
fixtures under `tests/faucet-hq/<name>/`, and composes with every official
sink.

| Template | System | Streams | Incremental |
|---|---|---|---|
| [`faucet-hq/salesforce`](source-templates/faucet-hq/salesforce.md) | Salesforce (Bulk API 2.0, v67.0) | accounts, contacts, leads, opportunities, opportunity_line_items, users, campaigns, campaign_members, cases, tasks, events | all streams, `SystemModstamp` (+ soft deletes via `queryAll`) |
| [`faucet-hq/hubspot`](source-templates/faucet-hq/hubspot.md) | HubSpot CRM (API 2026-09) | contacts, companies, deals, tickets (+ `_archived` for each), owners, deal_pipelines, ticket_pipelines | contacts, companies, deals, tickets (last-modified via CRM search) |
| [`faucet-hq/stripe`](source-templates/faucet-hq/stripe.md) | Stripe (API 2026-08-26.dahlia) | customers, subscriptions, invoices, charges, refunds, payment_intents, products, prices, payouts, disputes, balance_transactions, events | balance_transactions, events (`created` windows) |
| [`faucet-hq/jira`](source-templates/faucet-hq/jira.md) | Jira Cloud REST v3 | issues, projects, users, fields, statuses, issue_types, priorities, resolutions | — (full refresh) |
| [`faucet-hq/zendesk`](source-templates/faucet-hq/zendesk.md) | Zendesk Support API v2 | tickets, users, organizations, groups, ticket_fields, ticket_metrics, satisfaction_ratings | tickets, users (incremental exports, deletes included) |
| [`faucet-hq/shopify`](source-templates/faucet-hq/shopify.md) | Shopify GraphQL Admin API 2026-07 | orders, customers, products, product_variants, collections, locations, deleted_products | orders, customers, products, product_variants, deleted_products (`updated_at` / `created_at`) |
| [`faucet-hq/github`](source-templates/faucet-hq/github.md) | GitHub REST (2026-03-10) | repository, issues, issue_comments, pull_requests, review_comments, commits, releases, workflow_runs | issues, issue_comments, review_comments, commits (`since`) |
| [`faucet-hq/google-ads`](source-templates/faucet-hq/google-ads.md) | Google Ads API v25 (GAQL search) | customer, campaigns, ad_groups, ads, keywords, campaign/ad_group/ad/keyword performance, search_terms | rolling window (performance streams) |
| [`faucet-hq/meta-ads`](source-templates/faucet-hq/meta-ads.md) | Meta Marketing API v25.0 | ad_account, campaigns, ad_sets, ads, ad_creatives, campaign/ad insights + age-gender/country/platform breakdowns (async) | rolling window (insights) |
| [`faucet-hq/google-analytics-4`](source-templates/faucet-hq/google-analytics-4.md) | GA4 Data API v1beta (`runReport`) | traffic_daily, traffic_sources, landing_pages, pages, events, devices, geography | windowed with a 3-day lookback (all streams) |

Incremental streams keep their bookmark in a `state:` store — supply one with a
deployment overlay (`--overlay`), or they re-read everything each run.

## Publish a template

**Registering a template in the hub is a pull request into your own
namespace.** The website's [Publish](https://faucet-hq.github.io/hub#publish)
button opens a pre-filled new-file form in this repository; or copy the closest
existing file:

1. `source-templates/<your-github-login>/<name>.yaml` (or `sink-templates/…`),
   with `owner: <your-github-login>`, `name` equal to the file stem
   (`^[a-z0-9][a-z0-9_-]*$`) and a one-line `description`. The template's hub id
   is `<owner>/<name>` — `acme/netsuite` and `octo/netsuite` coexist. The hub's
   **official** set is the `faucet-hq/` namespace, owned by the org like any
   other; a bare `--source netsuite` resolves to `faucet-hq/netsuite`.
2. Credentials are **always** `${param.NAME}` with `secret: true` — never a
   literal, never a private hostname or placeholder value. The lint refuses both.
3. Declare every stream with its `write` preference (`[overwrite, upsert]`,
   `[upsert, append]`, `append`, …) and `primary_keys`; use `parent` for
   per-record fan-out and `sources:` + `source.ref` for a second endpoint family.
4. Run what CI runs:

```bash
faucet hub lint  --hub .
faucet hub check --hub . --source <your-login>/<name> --sink faucet-hq/jsonl      # and bigquery / postgres / sqlite
faucet template test tests/<your-login>/<name>/suite.yaml   # if you add a suite (see CONTRIBUTING → Tests)
python3 scripts/replay.py <your-login>/<name>               # if you add recorded fixtures
faucet hub matrix --hub . --format json > index.json        # CI regenerates this on merge
```

CI lints every template, composes every source × sink pairing, runs every
`tests/*/*/suite.yaml` and replays every recorded fixture, and keeps
`index.json` current. A green check is the review bar; a maintainer merges.

Schemas: `faucet schema source-template` / `faucet schema sink-template`.
Reference: [Template Hub cookbook](https://faucet-hq.github.io/faucet-stream/cookbook/template-hub.html).

## Namespaces, ownership, versions

- **Owner = GitHub user or org.** `source-templates/<owner>/` belongs to the
  GitHub account whose login it is. The first pull request into a new namespace
  also adds `<owner>/OWNERS` recording the author's numeric GitHub id (logins
  can be renamed; ids cannot); every later change to that namespace must come
  from an id listed there. An org namespace lists several ids; an existing owner
  adds a colleague with a PR. CI (`.github/workflows/ownership.yml`) enforces
  this from the PR *author*, and it is a required check.
- **Official templates** live in the `faucet-hq/` namespace (`owner: faucet-hq`),
  owned by the org through its own `OWNERS` file and reviewed via CODEOWNERS.
  `--source netsuite` means `faucet-hq/netsuite`; `--source acme/netsuite` a
  community one. If there is no official template of a name, the unqualified
  form lists the variants instead of guessing. Nothing lives at the top level.
- **Versions are numeric and automatic.** Every merged change to a template's
  meaning is the next version — v1, v2, v3 — computed from git history by
  `scripts/index.py` (comment-only edits do not count). A sidecar
  `<name>.faucet.yaml` beside the template with `launch: false` publishes a new
  version as a preview without moving `stable`; `stable: 3` pins it. Consumers
  select with `--source acme/netsuite@stable` (default), `@newest`, or `@3`.
  A version is retired with `deprecated:` in the sidecar, never deleted: `@N`
  still resolves it (with a warning), `@newest` skips it. See
  [CONTRIBUTING → Versions](CONTRIBUTING.md#versions) for fixing forward,
  rolling back, and retiring a version.

## Stars and trust

Each template has a discussion under **Discussions → Templates**. Upvoting
(↑) it **stars** the template. Stars, the last update, how long `stable` has held, open issues
and the publisher's track record appear in `index.json` under `trust`, on the
[hub page](https://faucet-hq.github.io/hub), and in
`faucet hub list --sort stars|updated`. See
[CONTRIBUTING → Stars and trust signals](CONTRIBUTING.md#stars-and-trust-signals).

## Layout

```
source-templates/faucet-hq/<name>.yaml  the hub's official source templates (owner: faucet-hq)
source-templates/<owner>/<name>.yaml    community source templates (owner: <owner>)
source-templates/<owner>/OWNERS       who may change that namespace (GitHub ids)
sink-templates/…                      the same for destinations
source-templates/faucet-hq/<name>.md  an official template's README: scopes, run times, changelog
tests/<owner>/<name>/suite.yaml       `faucet template test` suite for a template
tests/<owner>/<name>/replay.yaml      recorded API exchanges + expected/<stream>.jsonl (scripts/replay.py)
examples/data/                        fixtures the example-csv template reads (runs offline)
index.json                            generated: sources, sinks, matrix, commands, versions, stable, live_versions, trust
stars.json                            generated: stars, open issues, publisher ages (scripts/stars.py, hourly)
scripts/index.py                      regenerates index.json (CI runs it on merge)
scripts/stars.py                      opens each template's star discussion and collects trust signals
scripts/replay.py                     serves recorded exchanges and runs a template's streams against them
```

## License

Templates are dual-licensed under Apache-2.0 or MIT, like faucet-stream itself.
By contributing you agree your template is published under both.
