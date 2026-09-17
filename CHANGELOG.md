# Changelog

All notable changes to edgesentinel are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

Release numbers track the roadmap milestone being closed: `0.3.0` ships when
milestone v0.3 is complete. Features from other milestones land in whichever
release comes next. The full backlog lives in [`docs/roadmap.json`](docs/roadmap.json).

## [Unreleased]

### Fixed

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
