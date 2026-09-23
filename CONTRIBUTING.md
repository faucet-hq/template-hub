# Contributing a template

A template here is used by people you will never meet, against credentials you
will never see. The rules below exist so that is safe.

## What a source template must have

```yaml
kind: source-template
name: acme-billing                 # == file stem; hub id; the composed pipeline's name
description: Acme Billing — invoices, payments, customers
tags: [finance, billing]
docs: https://developer.acme-billing.example/api      # optional
params:
  api_token: { type: string, required: true, secret: true, description: "API token" }
source:
  type: rest
  config:
    base_url: https://api.acme-billing.example/v1
    auth: { type: bearer, config: { token: "${param.api_token}" } }
    records_path: $.data[*]
    pagination: { type: NextLinkInBody, next_link_path: $.page.next }
transforms:
  - { type: keys_case, config: { mode: snake } }
streams:
  - name: invoices
    source: { config: { path: /invoices } }
    primary_keys: [id]
    write: [overwrite, upsert]
  - name: payments
    source: { config: { path: /payments, replication_method: { type: Incremental, replication_key: updated_at } } }
    primary_keys: [id]
    write: [upsert, append]
```

- **Public endpoints only.** A hostname a user cannot reach from the internet
  belongs in a `${param.*}`, not in the template.
- **No credentials, no placeholders.** `${param.NAME}` with `secret: true` for
  anything secret; `${env:…}` / `${secret:…}` are also accepted. `REPLACE_ME`,
  `xxx`, `your-token-here` are refused by the lint.
- **One stream per table you would want in a warehouse**, each with the write
  preference that keeps it correct: `[overwrite, upsert]` for a full refresh,
  `[upsert, append]` for an incremental feed, `append` for an event log.
  `upsert` needs `primary_keys`.
- **Shape once, in `transforms`.** Shared shaping (`keys_case`, `json_encode`
  for nested fields, `cast`) runs before every sink, so every destination sees
  the same records.
- **Name things after the system, not your company.** A template is for the
  API, not for one deployment of it.

## What a sink template must have

```yaml
kind: sink-template
name: bigquery
description: Google BigQuery — one table per stream
params:
  bq_project: { type: string, required: true }
  bq_dataset: { type: string, default: raw }
  bq_sa_key:  { type: string, required: true, secret: true }
sink:
  type: bigquery
  config:
    project_id: "${param.bq_project}"
    dataset_id: "${param.bq_dataset}"
    auth: { type: service_account_key, config: { json: "${param.bq_sa_key}" } }
per_stream:
  table_id: "${stream}"
```

- `per_stream` is the addressing rule: every key is copied into each stream's
  sink config with `${stream}` and `${source}` substituted.
- Never write `write_mode` or `key` — the composer injects them per stream.
- `write_mode_aliases` declares a mode the destination satisfies by
  construction (a file rewritten every run *is* `overwrite`), never a keyed one.

## Before you open the PR

```bash
curl -LsSf https://github.com/faucet-hq/faucet-stream/releases/latest/download/faucet-cli-installer.sh | sh
faucet hub lint   --hub .
faucet hub check  --hub . --source <yours> --sink jsonl
faucet hub check  --hub . --source <yours> --sink bigquery
faucet hub matrix --hub . --format json > index.json
```

Every source must compose with at least two sinks in this catalog. CI runs the
same commands; a red check names the template and the stream.

## Review

A maintainer checks that the template describes the public API faithfully, that
stream write preferences match the data's semantics, and that nothing private
leaked. There is no CLA; templates are published under Apache-2.0 OR MIT.
