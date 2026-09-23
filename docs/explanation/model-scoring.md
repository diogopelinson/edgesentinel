# Scoring inside the model file

The ONNX artifact the agent loads does not output a raw model score. It outputs
`anomaly_score`, already normalised and already scaled, because both the
normalisation and the scoring rule are part of the graph. This page explains
why, starting with the bug that forced it.

## The bug

The anomaly model is an IsolationForest trained on CPU temperature between
about 51 and 65 °C. Scored against real readings, it produced this:

| Reading | Score |
|---|---|
| 75 °C | 0.9366 |
| 85 °C | 0.9366 |
| 95 °C | 0.9366 |

One number for every value above the training range — and a different single
number for everything below it. The model was saturating exactly where the
rules live, which made "hot" and "about to fail" indistinguishable.

It was not an export bug. IsolationForest scores a point by how early random
splits isolate it, and the splits are drawn from the range it was trained on.
Past the edge of that range there is nothing left to split: every value falls
into the same leaf and comes back with the same score. Verified in scikit-learn
directly, before ONNX was involved.

## The fix

The score is now defined in two regimes:

| Reading | Score |
|---|---|
| inside the training range | IsolationForest, rescaled to 0 – 0.8 |
| outside it | starts at 0.8 and rises with the distance from the range |

The model keeps doing what it is good at — recognising the shape of normal
inside the data it saw — and a plain distance rule takes over where it has no
information. With that, the reference model gives 0.91 at 75 °C, 0.96 at 85 °C
and 0.98 at 95 °C, while 58 °C scores 0.12.

## Why it lives in the graph, not in the loader

The scoring rule could have been three lines in `adapters/inference/onnx.py`.
It is in the ONNX graph instead, and the reason is that there are two readers.

The agent loads the model locally. The [AI Inference Service](../how-to/run-the-ai-service.md)
loads the same kind of model in a separate container, built from a separate
requirements file and deployed on its own schedule. They share no code, by
design — that separation is what keeps a YOLO crash from taking down sensor
monitoring.

Two readers and one formula in the loader means the formula exists twice.
Which is not a hypothetical: the AI Service carried a copy of the same
calibration code and therefore the same defect, and it had to be fixed twice.

With the rule inside the artifact, both readers have exactly one job: read the
output named `anomaly_score`. There is one place where the score is defined,
one place to fix, and no way for the two services to disagree about what 0.9
means.

The model also carries its own metadata — the output name, the training range,
the boundary score and the distance scale — so a file can be inspected without
the script that produced it.

## What this costs

**Retraining is mandatory for old files.** A model exported by an earlier
version of the script has no `anomaly_score` output; the loader rejects it at
startup with a message pointing at the script. Refusing is the right answer:
the alternative is a silent fallback to the saturating behaviour.

**The rule is harder to change.** Adjusting the boundary score means retraining
rather than editing a constant. That is the trade — a formula that cannot drift
between services in exchange for one that cannot be tweaked in place.

**The model still scores everything.** Putting the rule in the graph fixed what
a score means; it did not fix which readings get one. Every sensor goes through
the model, including those it was never trained on, so CPU usage in percent
lands far outside the temperature range and scores around 0.98 by construction.
That is a real limitation with a roadmap entry — `anomaly-sensor-scoping` — and
until it lands, `anomaly` rules belong on the sensor the model was trained for.

## See also

- [ADR 0005](../adr/0005-scoring-inside-the-model-file.md) — the decision and the alternatives.
- [Train an anomaly model](../how-to/train-an-anomaly-model.md) — producing one and checking it.
