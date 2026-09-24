# Changelog

All notable changes to edgesentinel are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

Release numbers track the roadmap milestone being closed: `0.3.0` ships when
milestone v0.3 is complete. Features from other milestones land in whichever
release comes next. The full backlog lives in [`docs/roadmap.json`](docs/roadmap.json).

## [Unreleased]

### Added

- **`StatePort`** — the contract for state that outlives a single
  evaluation, with `try_acquire(key, ttl)` for cooldowns and `get`/`set` for
  values that have to outlive one reading. It exposes no timestamps on
  purpose: a monotonic epoch means nothing in another process, so a
  distributed implementation can expire keys server-side instead of
  comparing clocks.
- **`InMemoryState`** — the default implementation, per-process and backed by
  `time.monotonic()`, guarded by a lock. `tests/adapters/test_state_contract.py`
  is parametrized by implementation, so the Redis adapter planned for v0.6
  has to pass the same suite.
- **Incidents group the firings of a rule.** The first firing opens an
  incident, every later firing of the same rule joins it, and the incident
  closes on its own when the reading comes back past a resolution margin —
  the threshold minus 10% of its absolute value, away from the alarm — so a
  value oscillating on the edge no longer produces an episode per reading.
  The states are `triggered`, `acknowledged` and `resolved`: acknowledging
  keeps the history recording and stops the actions repeating, which is how
  a rule stays audited while someone is already working on it.
- **`resolve_threshold`** on a rule's condition names the closing point when
  the default margin is the wrong distance. A value on the alarm side of the
  threshold fails when the config is loaded — `> 85` resolving at 90 would
  close the incident with the sensor still over the limit — and so does the
  field on `==` or `anomaly`, which have no numeric edge.
- **`IncidentPort`, `Incident` and `IncidentState`** — the contract and the
  domain entity, immutable like the rest of `core/`. `SQLiteEventStore`
  implements the port alongside `EventPort`, so events and incidents share
  one file and one `close()`. One open incident per rule is guaranteed by a
  partial unique index (`WHERE state != 'resolved'`), not by a lock in the
  engine, and the engine keeps no incident in memory: it reads the open ones
  on every evaluation, so the lifecycle survives a restart with no loading
  step and an acknowledgement made by another process lands on the next
  cycle. A store that raises is logged and swallowed, as a history failure
  is — the alert still goes out, with `incident_id` left empty.
- **Documentation in the [Diátaxis](https://diataxis.fr/) layout**, under
  `docs/`: two tutorials, nine how-to guides, five reference pages, three
  explanations and seven architecture decision records, each directory with
  its own index. Everything in `USAGE-EN.md` moved there; the file remains as
  a map of where each section went. `USAGE-PTBR.md` stays a single maintained
  file and is the Portuguese entry point alongside `README-BR.md`.
- **`AGENTS.md`** — instructions for AI coding agents, following the AGENTS.md
  convention: build and test commands, the layout, the conventions of this
  repository and the things that are not guessable from the code, such as the
  schema version in the event database and the rule that the engine may not
  read a clock. Kept under 300 lines, which a test enforces.
- **`CONTRIBUTING.md`, `SECURITY.md`, `LICENSE`** and GitHub issue and pull
  request templates. SECURITY.md lists what the agent assumes about its
  network — an unauthenticated metrics endpoint, unsigned webhook payloads,
  secrets in plain text in the config — rather than only how to report a
  vulnerability. The MIT licence text had been claimed by the README since the
  first commit and was never in the repository.
- **Static analysis with CodeQL**, on every pull request and weekly, with the
  `security-extended` queries. It covers what tests do not: a path built from
  YAML, a request assembled from config, a call with physical effect. Alerts go
  to the Security tab and do not gate a merge yet — the volume has to be known
  first. A test asserts the job keeps its `security-events: write` permission,
  without which the analysis runs green and publishes nothing.
- **A coverage floor on the core.** CI fails when `core/` and `application/`
  fall below 95%, which is where they sit today at 97%. The floor is declared
  once, in `pyproject.toml`, and a test requires both READMEs to cite the same
  number — the point is that the figures printed in the documentation cannot rot
  quietly. The adapters have no floor: covering absent hardware would be
  theatre. Coverage moved out of the version matrix into its own job, so the
  matrix runs faster and measures compatibility only.
- **Dependency watching** — Dependabot for the agent, the AI service and the
  GitHub Actions themselves, weekly and grouped; plus `pip-audit` on a schedule
  in its own workflow, so an advisory published after the last commit is still
  noticed. The audit reports and does not gate: a CVE in a transitive dependency
  must not block a pull request that has nothing to do with it. `SECURITY.md`
  describes both, including the limit — without a lockfile, the audit describes
  a fresh install rather than what is running on a device.
- **A smoke check that boots the agent** (`scripts/smoke.py`, run by CI on every
  push). It writes a config, starts the real process, waits for `/metrics` to
  answer and for a rule to reach the database, then sends SIGTERM — what systemd
  and Docker send — and requires exit code 0 with the history intact. Eight
  checks in about fifteen seconds. The suite covers functions; this covers the
  program, which is where the last two defects hid: `python -m cli.main`
  printing nothing at all, and `simulate` reading every sensor twice per tick.
  Mutation-checked, including one mutation it deliberately does not catch, with
  the reason written in the script.
- **ruff and mypy, enforced by CI.** `ruff check .` over the repository with
  E, W, F, UP, B, C4, SIM and RUF, and `mypy --strict` over `core/` and
  `application/`, both configured in `pyproject.toml` so the command in the
  pipeline is the command you run locally. Three rules are off with the reason
  written next to each: `E501` (column alignment is deliberate), `BLE001`
  (`except Exception` is an architectural decision here) and `C408` in tests
  (`dict(field=value)` is kwargs being assembled). Everything else passes with
  nothing ignored.
- **Continuous integration** (`.github/workflows/tests.yml`): every push and
  pull request runs the suite on Ubuntu with Python 3.10, 3.11, 3.12 and 3.13,
  and on Windows with 3.10. `requires-python` has promised 3.10 and newer since
  the first release and only 3.10 was ever exercised. The workflow installs the
  optional dependencies the tests need, so the eighteen model and payload tests
  run there instead of skipping, and checks out the full history, without which
  the roadmap's delivery commits cannot be verified. `tests/test_ci_workflow.py`
  guards all of that.
- **`tests/test_roadmap.py`** — `docs/roadmap.json` is now verified by the
  suite: fields present, dependency edges symmetric, no dependency in a later
  milestone, no cycles, status derived from the graph rather than asserted,
  and every `delivered_in` an actual commit.

### Fixed

- **Exceptions raised while handling another now say so.** Nine sites gained
  `from None` or `from e` — `from None` where a missing optional package is
  re-raised with install instructions, `from e` in the remote adapter and the
  AI service, where the HTTP failure underneath is what a debugger needs.
- **`zip()` states its length expectation** in the events table, the rendered
  rows and the training report: `strict=True` turns a silent truncation into an
  error.
- **A dead variable left the remote inference adapter** — `has_detections` was
  computed and never read, while the score came from `confidence`.
- **Two tests stopped claiming more than they checked.** One asserted that
  mutating a frozen dataclass raises `Exception`, which any failure satisfies;
  it now asserts `FrozenInstanceError`. The other annotated a helper as
  returning `Event` without importing it, and shadowed `unittest.mock.call`
  with a variable of the same name.
- **A test failed instead of skipping without OpenCV.** The frame payload test
  encodes through `cv2`, which belongs to the optional `[camera]` extra; it
  passed here only because this checkout had every extra installed. Found by
  running the suite on a second interpreter with only the `onnx` extra.
- **`python -m cli.main` did nothing.** The module had no `__main__` block, so
  it was imported and the process exited 0 having printed nothing. It is the
  documented way to run the CLI when a venv's console scripts break — they
  embed the absolute path of the directory the venv was created in — so it now
  runs, and a test pins both entry points to the same version string.
- **`simulate` read every sensor twice per tick**, printing one value and
  evaluating another: 81.82 on screen against 82.02 in the alert, close enough
  to look like rounding. The simulated sensors also advanced two steps per
  tick, so the scenario curve ran at double speed.
- **The JSON output of `edgesentinel events` was missing `incident_id`.** The
  record predates incidents and was never revisited, so grouping the events of
  an episode meant opening the database by hand.

- **A rule could fire twice at once.** The engine compared and then wrote
  `rule._last_triggered` in separate steps, while pipelines run on executor
  threads sharing one engine. Taking a cooldown is now a single atomic
  operation on the state; a test drives twenty concurrent callers and
  requires exactly one to win.
- **The ONNX anomaly score no longer saturates.** IsolationForest only splits
  inside the range it was trained on, so every reading beyond that range got
  the same score — 0.9366 for anything above ~65 °C and 1.0 for anything
  below ~50 °C — exactly where rules fire. Inside the training range the
  score still comes from IsolationForest, now rescaled to 0–0.8; outside it
  the score starts at 0.8 and rises with the distance to the range. The
  reference model now gives 0.91 at 75 °C, 0.96 at 85 °C and 0.98 at 95 °C.
  A 55-second `simulate --scenario stress` run recorded 265 distinct scores
  for `cpu_temp` events, where it used to record one.
- The AI Inference Service's ONNX model carried the same calibration code and
  the same defect; it is fixed the same way.
- The Grafana setup steps pointed to `dashboards/edgesentinel.json`, which does
  not exist; they now name `dashboards/edgesentinel_dashboard_v2.json`. A test
  now checks that relative links and dashboard paths in the docs exist.

### Changed

- **The repository root is no longer an importable package.** An empty
  `__init__.py` from the first structural commit made the project directory
  itself a package, so every module had two names — `core.entities` and
  `edgesentinel.core.entities` — and mypy refused to run at all. Nothing
  imported it.
- **The README is an entry point rather than a manual.** It was 582 lines and
  served as tutorial, reference, guide and rationale at once; it now covers
  what the project is, why it exists, a quickstart, and a map into `docs/`.
  Nothing was deleted — each part has a page.
- **`docs/roadmap.json` grew from 32 to 48 features** across three new
  milestones: project health (documentation, CI, linting, packaging, a
  container image), field operation (hot reload, action retries, notification
  channels, maintenance windows, health endpoints, a systemd unit) and
  composite rules (expressions across sensors, rates of change). Every
  feature, old and new, gained two one-line fields: `does` and `adds`.
- **The event database migrates to schema 2 when it is first opened** — an
  `incidents` table and an `incident_id` column on `events`. An existing
  `data/events.db` is migrated in place and keeps its events; nothing to do
  by hand. Events written before the migration keep `incident_id` empty.
- Cooldown state left the `Rule` entity: the `_last_triggered` field is gone
  and the engine asks the state for `cooldown:<rule name>`. `Rule` is now
  only the declaration of a rule. Behaviour is unchanged, and the existing
  cooldown tests were not touched.
- **Anomaly models have a new format — retrain them** with
  `python scripts/train_model.py`. The export is now one self-contained
  `anomaly.onnx` whose single output, `anomaly_score`, already includes
  normalisation and the scoring rule, so the agent and the AI service only
  read it. `scaler.onnx` is no longer produced or read. A model in the old
  format is refused at load time with a message pointing to the script, and
  a `scaler_path` in `models.yaml` is ignored with a warning.
- `scripts/train_model.py` takes `--seed`; training data is reproducible.
- ONNX tests train their own model instead of reading `models/`, and the AI
  service's ONNX model has tests of its own.
- The package description is now in English — "Intelligent observability for
  Linux embedded devices" — matching `README.md`, which the package
  publishes as its long description. A test keeps the two aligned.
- Model weights are no longer versioned. `models/anomaly.onnx`,
  `models/scaler.onnx`, `models/yolov8n.pt` and
  `ai-inference-service/weights/yolov8n.pt` were removed from the index, and
  `.gitignore` now excludes `models/*.pt`, `models/*.onnx` and
  `ai-inference-service/weights/`. `models/README.md` explains how to obtain
  each file. Earlier commits still contain them.

  **Pulling this change deletes your local copies of those four files** —
  git removes files that an incoming commit stops tracking. The YOLO weights
  can be brought back from the last release that tracked them; they stay out
  of git because they now match the ignore rules:

  ```bash
  git restore --source=v0.3.0 --worktree -- models/yolov8n.pt ai-inference-service/weights/yolov8n.pt
  ```

  Do not restore `anomaly.onnx` or `scaler.onnx` the same way: they are in the
  old model format. Generate a new `anomaly.onnx` with the training script.

## [0.3.0] - 2026-09-17

Closes milestone **v0.3 — events and severity**. Milestone v0.2 (sensor
foundation) is partially delivered here and continues in later releases.

### Added

- **Rule severity** — `info`, `warning` (default) or `critical` per rule,
  validated when the config loads and passed to every action through
  `ActionContext.extras["severity"]`.
- **Event Store** — every rule firing is recorded in a local SQLite file
  (`data/events.db` by default) with rule, sensor, value, severity, reading
  time and anomaly score. Writes are queued and batched by a dedicated thread,
  flushed on shutdown including Ctrl+C, and pruned by `retention_days` at
  startup. Configured through the `event_store` block; enabled by default.
- **`edgesentinel events`** — query the history from the terminal, filtering
  by severity, sensor, rule and time window (`--last 30m|24h|7d`), as an
  aligned table or JSON Lines (`--json`). Read-only, data on stdout, status on
  stderr, exit codes 0 / 1 / 2.
- **`default_actions`** — actions per severity for rules that do not declare
  their own `actions`. A rule's list replaces the default; `actions: []`
  dispatches nothing and still records history.
- `EventPort` and `Event` in the core, following the existing ports and
  adapters layout.
- `docs/roadmap.json`, an executable backlog: features with dependencies,
  acceptance criteria and delivery commits, plus the recorded Python/Go
  language boundary.
- This changelog.

### Changed

- The `log` action logs at the level of the rule's severity. Its constructor
  level now only applies when it is called outside the rule engine.
- `edgesentinel simulate` records events, so the history can be demonstrated
  without an SBC.
- `README.md` is now in English; the Portuguese README moved to
  `README-BR.md`.
- The package version has a single source, `cli.__version__`, read by
  `pyproject.toml`. `edgesentinel --version` reports it.
- The example `config.yaml` routes its rules through `default_actions` and
  adds a critical temperature rule at 85 °C. Resolved actions for the existing
  rules are unchanged.
- `data/` and `.idea/` are ignored by git.

### Fixed

- `CpuTemperatureSensor` no longer raises from its constructor on hosts
  without a thermal sensor. It reports absence through `is_available()`, so
  `run` and `doctor` take their "unavailable" path instead of their
  construction-failure path, and read errors list the paths that were tried.
- A rule written with `actions: log` (a string rather than a list) is now a
  load-time error. It used to be iterated into the action ids `l`, `o` and
  `g`.

### Known issues

- The ONNX anomaly model returns the same score (`0.9366`) for every reading.
- Model weights under `models/` are tracked by git. The `.onnx` files were
  committed before the ignore rule existed, and `models/*.pt` is not ignored
  at all: a missing newline in `.gitignore` merged it with the `.coverage`
  entry.
- The Grafana setup steps refer to `dashboards/edgesentinel.json`; the file in
  the repository is `dashboards/edgesentinel_dashboard_v2.json`.
- The AI Inference Service keeps its own version (`0.1.0`); it is deployed
  separately and did not change in this release.

## [0.1.0] - 2026-04-06

Initial version, never tagged.

### Added

- Hardware sensors read from `/proc` and `/sys`: CPU temperature, CPU usage
  and memory usage.
- Camera pipeline with MediaMTX and YOLO, plus a simulated camera.
- Rule engine with numeric and `anomaly` operators and per-rule cooldowns.
- Inference backends: dummy, ONNX, TFLite and the remote AI Inference Service.
- Actions: `log`, `webhook` and `gpio_write`.
- Prometheus and OpenTelemetry exporters with a Grafana dashboard.
- `run`, `simulate` and `doctor` commands.
- Containerized AI Inference Service (FastAPI) and the Docker Compose stack.

[0.3.0]: https://github.com/diogopelinson/edgesentinel/releases/tag/v0.3.0
[0.1.0]: https://github.com/diogopelinson/edgesentinel/tree/b3614c7
