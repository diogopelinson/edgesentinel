# models/

Model files live here but are not versioned: each one is generated or
downloaded on the machine that runs edgesentinel.

| File | How to get it | Used by |
|---|---|---|
| `anomaly.onnx` | `python scripts/train_model.py` (needs `pip install scikit-learn skl2onnx`) | `inference.backend: onnx` in `config.yaml`, and `anomaly_onnx` in the AI service |
| `yolov8n.pt` | fetched by ultralytics the first time the model path is loaded, or downloaded from the [ultralytics assets](https://github.com/ultralytics/assets/releases) | `yolo.model_path` in `config.yaml` |

The Docker Compose stack mounts this directory into the AI Inference Service
at `/app/weights`, so the paths in `ai-inference-service/models.yaml`
(`weights/...`) point at the same files.

`anomaly.onnx` is self-contained: normalisation and scoring are part of the
graph, and its only output is `anomaly_score`. A `scaler.onnx` left over from
earlier versions is no longer read and can be deleted, and an `anomaly.onnx`
from those versions is refused at load time — run the training script again.

`edgesentinel doctor` checks the YOLO weights. A missing `anomaly.onnx` shows
up when the agent starts, as an inference load error followed by
"Continuando sem ML" — monitoring keeps running without anomaly scores.
