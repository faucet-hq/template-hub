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
faucet hub check --source example-rest-api --sink bigquery
faucet run       --source example-csv --sink jsonl     # runs offline
faucet run       --source <source> --sink bigquery \
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
faucet template run example-rest-api --sink bigquery --param api_token="$TOKEN" …
```

## Publish a template

**Registering a template in the hub is a pull request.** The website's
[Publish](https://faucet-hq.github.io/hub#publish) button opens a pre-filled
new-file form in this repository; or copy the closest existing file:

1. `source-templates/<name>.yaml` or `sink-templates/<name>.yaml`, with `name`
   equal to the file stem (`^[a-z0-9][a-z0-9_-]*$`) and a one-line `description`.
2. Credentials are **always** `${param.NAME}` with `secret: true` — never a
   literal, never a private hostname or placeholder value. The lint refuses both.
3. Declare every stream with its `write` preference (`[overwrite, upsert]`,
   `[upsert, append]`, `append`, …) and `primary_keys`; use `parent` for
   per-record fan-out and `sources:` + `source.ref` for a second endpoint family.
4. Run what CI runs:

```bash
faucet hub lint  --hub .
faucet hub check --hub . --source <yours> --sink jsonl      # and bigquery / postgres / sqlite
faucet hub matrix --hub . --format json > index.json        # CI regenerates this on merge
```

CI lints every template, composes every source × sink pairing, and keeps
`index.json` current. A green check is the review bar; a maintainer merges.

Schemas: `faucet schema source-template` / `faucet schema sink-template`.
Reference: [Template Hub cookbook](https://faucet-hq.github.io/faucet-stream/cookbook/template-hub.html).

## Layout

```
source-templates/   one file per system   (kind: source-template)
sink-templates/     one file per destination (kind: sink-template)
examples/data/      fixtures the example-csv template reads (runs offline)
index.json          generated: sources, sinks, the compatibility matrix, commands
```

## License

Templates are dual-licensed under Apache-2.0 or MIT, like faucet-stream itself.
By contributing you agree your template is published under both.
