# Contributing to edgesentinel

Thanks for taking the time. This file covers how to set the project up, what a
change is expected to carry, and the conventions that keep the history
readable. If you are an AI coding agent, read [AGENTS.md](AGENTS.md) instead —
it says the same things in the form an agent needs.

## Setting up

Python 3.10 or newer. No hardware is required to develop: every sensor has a
simulated counterpart, and the whole test suite runs on a laptop.

```bash
git clone https://github.com/diogopelinson/edgesentinel.git
cd edgesentinel
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e .[all]
pip install pytest pytest-mock pytest-cov
pytest tests/ -q
```

`pip install -e .` alone is enough for the core; the extras pull in ONNX
runtime, OpenCV, GPIO and OpenTelemetry. `edgesentinel doctor` reports what is
available in your environment and what each missing piece would enable.

To see it running without any hardware:

```bash
edgesentinel simulate --scenario stress
```

## What a change carries

**A test that failed before your fix.** Write it first, watch it fail, then
make it pass. Then do the check that matters: break the code your test covers
on purpose and confirm the test fails. A test that stays green against broken
code is worse than no test, because it is believed.

**Documentation, in the same branch.** If the change is visible to a user, it
belongs in the docs that cover that area — [docs/](docs/README.md) for the
English documentation, `README-BR.md` and `USAGE-PTBR.md` for the Portuguese
mirrors — and in `CHANGELOG.md` under `[Unreleased]`.

**Style and types that pass.** `ruff check .` over the repository and
`mypy` over `core/` and `application/`, both configured in `pyproject.toml`
and both run by CI. `ruff check . --fix` applies the safe fixes; anything it
leaves is worth reading rather than silencing, and if a rule genuinely fights
the design, turn it off in the config with the reason next to it — that is how
`E501`, `BLE001` and `C408` came to be off.

**A green pipeline.** Every push and pull request runs the suite on Ubuntu
with Python 3.10 through 3.13, and on Windows with 3.10 — the version this
project is developed on. The workflow installs the optional dependencies the
tests need (`scikit-learn`, `skl2onnx`, `onnx`, `opencv-python-headless`), so a
test that skips locally still runs there. If you do not install them, expect
around eighteen skips in your local run and nothing red.

**An honest roadmap.** `docs/roadmap.json` is the backlog and
`tests/test_roadmap.py` verifies it. If your change delivers a feature listed
there, mark it `done` with the merge SHA and promote whatever it unlocked. If
the delivery differed from the plan, correct the entry: what shipped is more
useful to the next reader than what was predicted.

A worked example of all of the above, using a change that is actually in the
history — the failing test, the two commits, the mutation check and the filled
in template — is in
[Submit a pull request](docs/how-to/submit-a-pull-request.md).

## Conventions

**Commits are one file each.** It reads oddly at first and pays for itself on
the day someone bisects. The subject is English, imperative, and shaped as
`type(scope): summary` — `feat`, `fix`, `test`, `docs`, `refactor`, `chore`.
The body explains why the change exists; the diff already shows what it does.

**Branches are named after the feature** they deliver: `feat/incident-lifecycle`
for the entry with that id in the roadmap. Merge with `--no-ff` so the branch
survives in the history.

**Code and comments are in Portuguese.** Commit messages and everything in
`docs/`, `README.md` and `USAGE-EN.md` are in English. This split is
deliberate: the code is read by the people who write it, and the documentation
is read by anyone.

## Architecture in one paragraph

The core domain — `core/` — knows nothing about Prometheus, SQLite, GPIO or
YOLO. It defines ports; `adapters/` implements them; `application/` wires them
together. A new integration is a new adapter behind an existing port. If it
needs a new port, the port goes in `core/ports.py` and the domain stays
unaware of what implements it. Anything that talks to the outside world —
network, disk, hardware — logs its failure and swallows it, because an alert
must go out even when the machinery around it is failing. See
[docs/explanation/architecture.md](docs/explanation/architecture.md).

## Reporting a bug

Open an issue with what you expected, what happened, the output of
`edgesentinel doctor`, and the relevant part of your `config.yaml` with any
secrets removed. If it involves a sensor, say which device and which OS.

For anything with a security impact, do not open an issue — see
[SECURITY.md](SECURITY.md).
