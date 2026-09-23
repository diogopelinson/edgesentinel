<!--
Conventions are in CONTRIBUTING.md; AI agents have their own copy in AGENTS.md.
Delete any section that does not apply.
-->

## What this changes

<!-- One paragraph. Why the change exists — the diff already shows what it does. -->

## Roadmap

<!--
The feature id in docs/roadmap.json, if this delivers one. Say "none" for a
fix or a docs change that is not in the backlog.
-->

## How it was verified

<!--
The command you ran and what it printed. If you added tests, say what you
broke on purpose to prove they can fail.
-->

## Checklist

- [ ] `pytest tests/ -q` is green
- [ ] New tests fail against the unfixed code (mutation-checked)
- [ ] Docs updated in this branch — `docs/`, the two READMEs, the two USAGE guides, whichever apply
- [ ] `CHANGELOG.md` updated under `[Unreleased]`
- [ ] `docs/roadmap.json` reflects reality, if this delivers a feature
- [ ] One file per commit, English messages, no attribution trailers
