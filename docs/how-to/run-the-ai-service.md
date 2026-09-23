# Run the AI Inference Service

The containerised service that holds YOLO and the ONNX models, and how to add a model to it.

## Endpoints

```bash
# status
curl http://localhost:8080/health
# {"status":"ok","models":2}

# loaded models
curl http://localhost:8080/models
# [{"id":"yolo_v8n","type":"yolo","status":"loaded"},...]

# inference with base64 frame
curl -X POST http://localhost:8080/predict \
  -H "Content-Type: application/json" \
  -d '{"model_id":"yolo_v8n","frame_b64":"BASE64_HERE"}'

# inference with stream URL (captures one frame automatically)
curl -X POST http://localhost:8080/predict \
  -H "Content-Type: application/json" \
  -d '{"model_id":"yolo_v8n","stream_url":"rtsp://localhost:8554/camera_01"}'

# sensor anomaly inference
curl -X POST http://localhost:8080/predict \
  -H "Content-Type: application/json" \
  -d '{"model_id":"anomaly_onnx","sensor_value":85.0}'
```

**Response:**

```json
{
  "model_id": "yolo_v8n",
  "detections": [
    {"class_name": "person", "confidence": 0.91, "bbox": [120.0, 50.0, 380.0, 480.0]}
  ],
  "inference_latency_ms": 178.42,
  "has_detections": true
}
```

## Adding a model

Edit `ai-inference-service/models.yaml`:

```yaml
models:
  - id: yolo_v8n
    type: yolo
    path: weights/yolov8n.pt
    target_classes: [person, car, truck]
    confidence_threshold: 0.5

  - id: fire_detector
    type: yolo
    path: weights/fire.pt
    target_classes: [fire, smoke]
    confidence_threshold: 0.4
```

```bash
docker compose restart ai-inference-service
curl http://localhost:8080/models
# [..., {"id":"fire_detector","type":"yolo","status":"loaded"}]
```

The `weights/` paths resolve to the repository's `models/` directory, which Docker Compose mounts at `/app/weights`. So `weights/fire.pt` means the file `models/fire.pt` on the host. Weight files are never committed: `.gitignore` excludes `models/*.pt`, `models/*.onnx` and `ai-inference-service/weights/`, and [`models/README.md`](../../models/README.md) says how to obtain the ones the project uses.

## ONNX anomaly models

`type: onnx` models, in the AI service and in the agent (`inference.backend: onnx`), follow one contract:

| | Name | Type | Meaning |
|---|---|---|---|
| input | any | `float32 [N, 1]` | the raw sensor value, unscaled |
| output | `anomaly_score` | `float32 [N, 1]` | 0 = normal, 1 = maximally anomalous |

`scripts/train_model.py` produces such a model, with normalisation and the scoring rule built into the graph. Any other ONNX file exposing that input and output works as well. A file without an `anomaly_score` output is refused when it loads — the AI service logs the error and keeps serving the other models. A `scaler_path` left in `models.yaml` from earlier versions is ignored with a warning.

For `anomaly_onnx`, the `/predict` response carries one `anomaly` detection whose `confidence` is the `anomaly_score`, or no detection when the score is below `confidence_threshold`.

---
