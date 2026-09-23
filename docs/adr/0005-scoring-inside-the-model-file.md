# 0005 — The scoring rule lives inside the model file

- **Status:** Accepted
- **Date:** 2026-09-18 *(recorded retrospectively)*

## Context

The anomaly model saturated. An IsolationForest trained on CPU temperature
between roughly 51 and 65 °C returned the same score — 0.9366 — for 75, 85 and
95 °C, and a different constant below the range. Every reading a rule cares
about got an identical number.

The cause is not the export: IsolationForest splits only inside the range it
was trained on, so everything beyond the edge lands in the same leaf. Confirmed
in scikit-learn before ONNX was involved.

Fixing the score means combining the model with a rule for what happens outside
its support. The question was where that rule should live, and the constraint
is that there are two readers of the artifact: the agent, which loads it
locally, and the AI Inference Service, which runs in its own container built
from its own requirements and shares no code with the agent by design.

## Decision

Bake normalisation and the scoring rule into the ONNX graph. The artifact takes
the raw sensor value and returns a single output named `anomaly_score`: the
IsolationForest score rescaled to 0 – 0.8 inside the training range, and a
value rising from 0.8 towards 1 with distance outside it. The training range,
the boundary score and the distance scale are written into the file's metadata.

Both readers then have one job: read `anomaly_score`.

Alternatives considered. **The rule in each loader**: three lines of code, and
the formula exists twice. This was not hypothetical — the AI Service already
carried a copy of the calibration code and therefore a copy of the defect, and
the fix had to be applied in both places. **A shared library between the two
services**: a package to version and deploy in step, which is exactly the
coupling the separate service exists to avoid. **Retraining on a wider range**:
pushes the saturation outwards instead of removing it, and a range wide enough
to cover every failure mode is a range where nothing looks unusual.

## Consequences

One definition of the score, in one place, for both services. The agent and the
AI Service cannot disagree about what 0.9 means.

Models exported by earlier versions of the script have no `anomaly_score`
output and are rejected at load time with a message pointing at the training
script. Refusing is deliberate: a silent fallback would restore the saturating
behaviour without saying so.

Changing the scoring rule now requires retraining rather than editing a
constant — the price of a formula that cannot drift between services.

The decision fixed what a score means, not which readings get one. Every sensor
still goes through the model, so a model trained on temperature scores CPU
usage in percent at around 0.98 by construction. That limitation is
`anomaly-sensor-scoping` in the roadmap, and it is recorded here so it is not
mistaken for a consequence of this decision.

## Revisit when

Models come from a registry with versions and per-model metadata
(`model-registry` in the roadmap). Then the scoring rule could live in the
registry entry rather than the graph — one definition, still one place, with
the artifact free to be a plain model again.
