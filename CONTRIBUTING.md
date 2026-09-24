# Contributing a template

A template here is used by people you will never meet, against credentials you
will never see. The rules below exist so that is safe.

## Namespaces and ownership

Your templates live under **your** namespace: `source-templates/<your-github-login>/`
(a user or an org login, lowercase). Inside each file, `owner:` names the same
login, so the template stays owned once it leaves the catalog. The first PR
that creates a namespace adds an `OWNERS` file:

```yaml
# source-templates/acme/OWNERS
owners:
  - { login: acme-bot, id: 12345678 }     # your numeric GitHub id — CI tells you if it is wrong
```

Only accounts listed there can change the namespace afterwards; an existing
owner adds another with a PR. The hub's own templates live in the `faucet-hq/`
namespace, owned by the org the same way. Nothing lives at the top level. A PR
that touches someone else's namespace fails the **Ownership** check.

## Versions

You never write a version number. Each merged change to a template's meaning
becomes its next version (v1, v2, v3 …); comment and whitespace edits fold
into the previous one. `stable` is the version consumers get by default. A
sidecar beside the template controls it:

```yaml
# source-templates/acme/netsuite.faucet.yaml
launch: false      # publish this change as a preview — stable stays where it is
# stable: 3        # or pin stable explicitly (a rollback is a PR that lowers it)
description: Acme's NetSuite — saved searches + ledger
```

## What a source template must have

```yaml
kind: source-template
name: acme-billing                 # == file stem; with owner, the hub id is acme/acme-billing
owner: acme                        # == the directory this file lives in
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

## Stars and trust signals

When several namespaces publish a template for the same system, `index.json`
gives each entry a `trust` block so people can choose between them:

| Field | Where it comes from |
|---|---|
| `stars` / `star_url` | upvotes (↑) on the template's discussion, opened automatically in the **Templates** category. GitHub allows one upvote per account. |
| `updated` / `stable_since` | dates of the newest and the stable version, from git history |
| `compatible_sinks` | sink templates the source composes with in full |
| `open_issues` | open issues labelled `template:<id>` (the label is created for you) |
| `publisher` | how many templates the namespace publishes, and its GitHub account age |

`scripts/stars.py` collects these into `stars.json` every hour and after each
merge (`.github/workflows/stars.yml`), and `scripts/index.py` merges them into
`index.json`. You never edit either file by hand. To report a problem with a
template, open an issue with its `template:<id>` label; to recommend one,
upvote its discussion.

## Before you open the PR

```bash
curl -LsSf https://github.com/faucet-hq/faucet-stream/releases/latest/download/faucet-cli-installer.sh | sh
faucet hub lint   --hub .
faucet hub check  --hub . --source <your-login>/<name> --sink faucet-hq/jsonl
faucet hub check  --hub . --source <your-login>/<name> --sink faucet-hq/bigquery
faucet hub matrix --hub . --format json > index.json
```

Every source must compose with at least two sinks in this catalog. CI runs the
same commands; a red check names the template and the stream.

## Review

A maintainer checks that the template describes the public API faithfully, that
stream write preferences match the data's semantics, and that nothing private
leaked. There is no CLA; templates are published under Apache-2.0 OR MIT.
