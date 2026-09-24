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
faucet hub check --hub . --source <yours> --sink jsonl      # and bigquery / postgres / sqlite
faucet hub matrix --hub . --format json > index.json        # CI regenerates this on merge
```

CI lints every template, composes every source × sink pairing, and keeps
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

## Layout

```
source-templates/faucet-hq/<name>.yaml  the hub's official source templates (owner: faucet-hq)
source-templates/<owner>/<name>.yaml    community source templates (owner: <owner>)
source-templates/<owner>/OWNERS       who may change that namespace (GitHub ids)
sink-templates/…                      the same for destinations
examples/data/                        fixtures the example-csv template reads (runs offline)
index.json                            generated: sources, sinks, matrix, commands, versions, stable
scripts/index.py                      regenerates index.json (CI runs it on merge)
```

## License

Templates are dual-licensed under Apache-2.0 or MIT, like faucet-stream itself.
By contributing you agree your template is published under both.
