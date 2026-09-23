## Template

- **Kind:** source-template / sink-template
- **System:** <!-- the API or destination, and a link to its public docs -->
- **Streams:** <!-- one line each: name — write preference — why -->

## Checklist

- [ ] `name` equals the file stem; `description` is one line
- [ ] Every credential is `${param.NAME}` with `secret: true`; no private hostnames, no placeholders
- [ ] `faucet hub lint --hub .` passes
- [ ] `faucet hub check --hub . --source <name> --sink jsonl` and `--sink bigquery` pass (a sink template: checked against `example-rest-api`)
- [ ] `index.json` regenerated (`faucet hub matrix --hub . --format json > index.json`)
- [ ] I tested it against the real system with `faucet run --source <name> --sink jsonl --param …`
