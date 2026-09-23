# Train an anomaly model

Produce the `anomaly.onnx` the agent loads, then check that it scores your
sensor sensibly before trusting a rule to it. Model files are never committed,
so a fresh clone has none and this is the step that creates one.

## Train it

```bash
pip install scikit-learn skl2onnx
python scripts/train_model.py
```

That writes `models/anomaly.onnx`. `--seed N` changes the training sample, and
running it twice with the same seed produces the same model.

## What comes out

One self-contained file with a fixed contract: the raw sensor value goes in as
`value`, and an `anomaly_score` between 0 and 1 comes out. Normalisation and
the scoring rule are inside the graph, so the agent and the
[AI Inference Service](run-the-ai-service.md) read the same number and cannot
disagree about what it means. See
[Scoring inside the model file](../explanation/model-scoring.md) for why it is
built that way.

The file also carries its own metadata:

```
edgesentinel.output                   anomaly_score
edgesentinel.training_min             51.554623
edgesentinel.training_max             64.479652
edgesentinel.support_boundary_score   0.8
edgesentinel.distance_scale           1.0
```

## Check it before trusting it

```bash
python - <<'PY'
import numpy as np, onnxruntime as ort

session = ort.InferenceSession("models/anomaly.onnx")
for value in (50.0, 58.0, 65.0, 75.0, 85.0, 95.0):
    score = session.run(["anomaly_score"], {"value": np.array([[value]], dtype=np.float32)})[0]
    print(f"{value:5.1f} -> {float(np.ravel(score)[0]):.4f}")
PY
```

The reference model answers:

```
 50.0 -> 0.8227
 58.0 -> 0.1239
 65.0 -> 0.8079
 75.0 -> 0.9114
 85.0 -> 0.9591
 95.0 -> 0.9811
```

Read that column carefully, because it is what the model actually claims:

- **58 °C scores 0.12.** It sits in the middle of the training range, so it is ordinary.
- **50 °C scores 0.82.** Below the training range is anomalous too — a CPU that suddenly runs cold is as unusual as one running hot.
- **75, 85 and 95 °C separate properly.** Past the edge of the training range the score keeps climbing with distance instead of saturating, which is what lets one rule distinguish "warm" from "about to fail".

If your numbers come back flat — every value above the range returning the same
score — you have a model from an older version of the script. Train it again;
the agent rejects such a file at load time with a message pointing here.

## Point the agent at it

```yaml
inference:
  enabled: true
  backend: onnx
  model_path: models/anomaly.onnx
```

Then a rule can use the score instead of a threshold:

```yaml
rules:
  - name: temperature_anomaly
    condition:
      sensor_id: cpu_temp
      operator: anomaly
    severity: warning
```

## The gotcha: the model scores every sensor

Every reading goes through the model, and the reference model was trained on
**CPU temperature only**. CPU usage in percent falls far outside its training
range, so it gets a high score by construction — around 0.98 — and an `anomaly`
rule over that sensor would fire constantly on a number that means nothing.

Until the scoping option lands (`anomaly-sensor-scoping` in
[the roadmap](../roadmap.json)), keep `anomaly` rules on the sensor the model
was trained for, and use ordinary thresholds for the rest.

## Train it on your own data

`scripts/train_model.py` generates its sample; swap that for readings from your
own device and the rest of the pipeline is unchanged. Two rules to keep:

- the exported graph must produce an output named `anomaly_score` — the loader looks for it by name;
- write the training range into the metadata, because that is what the scoring rule outside the range is measured against.
