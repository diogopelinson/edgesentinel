# Security policy

## Reporting a vulnerability

Report privately through GitHub's
[security advisory form](https://github.com/diogopelinson/edgesentinel/security/advisories/new),
not as a public issue. Include what an attacker gains, the steps to reproduce
it, and the version you tested.

Expect an acknowledgement within a week. This is a single-maintainer project,
so fixes are best effort, and you will be told plainly if a report is going to
take a while or is not going to be fixed.

## Supported versions

The latest release on `main` is the only supported version. Fixes go into the
next release rather than being backported.

## What this project assumes about its environment

edgesentinel runs on a device inside a network you control, and several of its
defaults assume that. None of these are bugs; they are constraints worth
knowing before a deployment.

**The metrics endpoint is unauthenticated.** `exporter.port` serves
`/metrics` to anything that can reach it, which is what Prometheus expects.
Bind it to an interface your scrapers can reach and nothing else.

**Actions make outbound requests with what you configure.** A `webhook` action
posts the rule name, the sensor value and the anomaly score to the URL in the
config. The payload is not signed and the destination is not verified beyond
TLS; treat the URL as a credential.

**Secrets currently live in `config.yaml`.** A webhook URL containing a token
is stored in plain text in the file you version and distribute to your fleet.
Reading secrets from the environment instead is a planned feature
(`config-env-substitution` in [the roadmap](docs/roadmap.json)); until it
lands, keep the URL out of the repository.

**The event database is a local file with no access control.** `data/events.db`
holds the readings and rule firings of the device; its protection is the file
system's.

**GPIO actions drive real hardware.** A rule with a `gpio_write` action can
energise a relay. The agent does not check what is on the other side of the
pin.

**Model files are trusted input.** `scripts/train_model.py` builds the ONNX
artifact the agent loads, and the loader validates its shape but not its
provenance. Do not point `inference.model_path` at a model you did not build
or obtain from a source you trust.
