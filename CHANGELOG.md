# Changelog

All notable changes to edgesentinel are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

Release numbers track the roadmap milestone being closed: `0.3.0` ships when
milestone v0.3 is complete. Features from other milestones land in whichever
release comes next. The full backlog lives in [`docs/roadmap.json`](docs/roadmap.json).

## [Unreleased]

### Changed

- Model weights are no longer versioned. `models/anomaly.onnx`,
  `models/scaler.onnx`, `models/yolov8n.pt` and
  `ai-inference-service/weights/yolov8n.pt` were removed from the index, and
  `.gitignore` now excludes `models/*.pt`, `models/*.onnx` and
  `ai-inference-service/weights/`. `models/README.md` explains how to obtain
  each file. Existing local copies are untouched; earlier commits still
  contain them.

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
