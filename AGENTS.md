# AGENTS.md

Instructions for AI coding agents working in this repository. Humans want
[README.md](README.md) and [CONTRIBUTING.md](CONTRIBUTING.md); this file holds
the details an agent needs before it touches anything.

## What this project is

edgesentinel is a monitoring agent for Linux edge devices: it reads sensors,
optionally scores readings with a local ML model, evaluates rules, groups
repeated firings into incidents, records everything in a local SQLite file and
exports metrics over OpenTelemetry. It is a single Python process meant to run
unattended for weeks on hardware as small as a Raspberry Pi.

## Setup and commands

The project is developed on Windows and deployed on Linux. Paths below use the
Windows layout; on Linux use `.venv/bin/`.

```bash
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e .[all]
.venv\Scripts\python.exe -m pip install pytest pytest-mock pytest-cov
```

| Task | Command |
|---|---|
| Whole suite | `.venv\Scripts\python.exe -m pytest tests/ -q` |
| One file | `.venv\Scripts\python.exe -m pytest tests/core/test_rules.py -q` |
| Coverage | `.venv\Scripts\python.exe -m pytest tests/ --cov=core --cov=application --cov-report=term-missing` |
| Run without hardware | `.venv\Scripts\python.exe -m cli.main simulate --scenario stress` |
| Inspect the environment | `.venv\Scripts\python.exe -m cli.main doctor` |

**Call Python through `.venv\Scripts\python.exe -m`, not through the console
scripts.** The launchers in `.venv\Scripts\` (`pytest.exe`, `edgesentinel.exe`,
`pip.exe`) embed the absolute path of the directory the venv was created in; the
project has moved since, so they fail with a path error. `python.exe -m` ignores
them and works.

Tests never touch the network and never need hardware. A test that would needs
a fake instead.

## Layout

```
core/           pure domain: ports, entities, rules, incidents. No imports from
                adapters, application or config. This rule is the architecture.
application/    engine (rule evaluation), pipeline (sense -> infer -> act),
                monitor (async loop, graceful shutdown)
adapters/       everything that talks to the outside: sensors/, inference/,
                actions/, exporter/, store/, state/
config/         YAML schema, loader (validation), mapper (config -> domain)
cli/            run, simulate, doctor, events; builder assembles objects
docs/           documentation, in the Diataxis layout - see docs/README.md
tests/          mirrors the source tree; integration/ holds the end-to-end ones
```

Dependencies point inward: `adapters` and `application` may import `core`, never
the other way round. A new integration is a new adapter behind an existing port;
if it needs a new port, the port goes in `core/ports.py` and the domain stays
unaware of the implementation.

## Conventions

**Commits.** English, imperative mood, one file per commit. The subject follows
`type(scope): summary` — `feat`, `fix`, `test`, `docs`, `refactor`, `chore`. The
body says *why*, not what the diff already shows. Do not add `Co-Authored-By`
or any other attribution trailer.

**Branches.** One branch per feature, named `feat/<id>`, `fix/<id>` or
`docs/<id>`, where `<id>` is the feature id in `docs/roadmap.json`. Merge with
`--no-ff` so the branch stays visible in the history.

**Tests first.** Write the failing test, commit it, then make it pass. Before
claiming a test is meaningful, break the code it covers on purpose and confirm
the test fails — a test that passes against broken code is worse than no test,
because it is believed. Restore the code afterwards.

**Language.** Code, comments and docstrings are in Portuguese; commit messages,
`README.md`, `USAGE-EN.md` and everything under `docs/` are in English.
`README-BR.md` and `USAGE-PTBR.md` are the Portuguese mirrors and are kept in
sync in the same branch as the change.

**Documentation.** A feature is not done until the docs that mention the area
are updated in the same branch: the two READMEs, the two USAGE guides, the
relevant page under `docs/`, and `CHANGELOG.md` under `[Unreleased]`.

## The roadmap is executable

`docs/roadmap.json` is the single source of truth for the backlog, and
`tests/test_roadmap.py` enforces it. Read it before proposing work.

- `status` is **derived**, not chosen: `done` and `ready` have no pending
  dependency, `planned` has one, `blocked` names a `blocked_by`.
- `depends_on` and `unlocks` are the same edge written twice. Add both or the
  test fails.
- A feature marked `done` carries `delivered_in`, the short SHA of the merge
  commit that delivered it, and that commit must exist in the repository.
- No feature may depend on one in a later milestone.
- `does` and `adds` are one-sentence summaries, capped at 400 characters.

When a feature is delivered: mark it `done` with its merge SHA, promote the
features it unlocked that now have nothing pending, and correct `design_notes`
when the delivery differed from the plan. Recording what actually shipped
matters more than defending the original entry.

## Careful here

- **`models/*.onnx` and `*.pt` are not versioned.** They are built by
  `scripts/train_model.py` or downloaded. Never commit weights; never assume
  they exist in a fresh clone.
- **`data/` is runtime state** (the event and incident database). It is
  gitignored and must never be committed or read at import time.
- **`config.yaml` at the root belongs to the user.** Tests must use their own
  temporary config, never the repository one.
- **The event database has a schema version.** Changing the tables in
  `adapters/store/sqlite.py` means bumping `_SCHEMA_VERSION` and adding a
  migration that preserves existing rows; there are tests for old databases.
- **Actions run on the alert path.** Anything that can block or raise —
  network, disk, GPIO — is logged and swallowed, never allowed to stop an
  evaluation. The same applies to the event store and the incident store: a
  storage failure must not silence an alert.
- **Do not read the clock inside the engine.** Cooldowns go through
  `StatePort`, because a monotonic epoch means nothing in another process and
  the Redis adapter has to be able to own expiry. A test asserts that
  `application/engine.py` contains no reference to `monotonic`.

## Continuous integration

`.github/workflows/tests.yml` runs the suite on every push and pull request:
Ubuntu with Python 3.10, 3.11, 3.12 and 3.13, plus Windows with 3.10. It
checks out the full history on purpose — `tests/test_roadmap.py` verifies
`delivered_in` against real commits and skips itself on a shallow clone — and
installs `scikit-learn`, `skl2onnx`, `onnx` and `opencv-python-headless` so the
model and payload tests actually run instead of skipping.

`tests/test_ci_workflow.py` guards that file, so changing the matrix or the
install list without updating it fails the suite.

## Before opening a pull request

1. `pytest tests/ -q` is green.
2. The new tests fail against the unfixed code (mutation-checked).
3. Docs and `CHANGELOG.md` updated in the same branch.
4. `docs/roadmap.json` reflects reality.
5. One file per commit, English messages, no attribution trailers.
