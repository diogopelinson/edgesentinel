"""
ONNXModel do AI Inference Service contra o mesmo artefato que o agente usa.

O serviço tem o próprio pacote `core`, que colide com o do agente, e roda
como processo separado. Por isso o teste executa o código do serviço num
subprocesso com o diretório dele como raiz de import.
"""
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from adapters.inference.onnx import ONNXInferenceAdapter
from core.entities import SensorReading

SERVICE_DIR = Path(__file__).resolve().parents[2] / "ai-inference-service"

PROBE = textwrap.dedent("""
    import json, sys
    import numpy as np
    from models.onnx import ONNXModel

    config = json.loads(sys.argv[2])
    model = ONNXModel("anomaly_onnx", confidence_threshold=0.6)
    model.load({"path": sys.argv[1], **config})

    result = {}
    for value in (58.0, 75.0, 85.0, 95.0):
        detections = model.predict(np.array([value], dtype=np.float32))
        result[str(value)] = detections[0].confidence if detections else None
    print(json.dumps(result))
""")


def run_probe(model_path, extra_config: dict | None = None) -> subprocess.CompletedProcess:
    pytest.importorskip("onnxruntime")
    return subprocess.run(
        [sys.executable, "-c", PROBE, str(model_path), json.dumps(extra_config or {})],
        cwd=SERVICE_DIR,
        capture_output=True,
        text=True,
        timeout=120,
    )


def probe_scores(model_path, extra_config: dict | None = None) -> dict[str, float | None]:
    completed = run_probe(model_path, extra_config)
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout.strip().splitlines()[-1])


def test_normal_value_produces_no_detection(anomaly_model_path):
    assert probe_scores(anomaly_model_path)["58.0"] is None


def test_confidence_rises_with_temperature(anomaly_model_path):
    """Regressão: o serviço tinha a mesma calibração do agente e o mesmo 0.9366 fixo."""
    result = probe_scores(anomaly_model_path)

    assert result["75.0"] < result["85.0"] < result["95.0"], result


def test_agrees_with_the_agent_adapter(anomaly_model_path):
    """Os dois consumidores leem a mesma saída — não podem divergir."""
    agent = ONNXInferenceAdapter(threshold=0.6)
    agent.load(str(anomaly_model_path))

    service = probe_scores(anomaly_model_path)

    for value in (75.0, 85.0, 95.0):
        reading = SensorReading("cpu_temp", "CPU Temperature", value, "°C")
        assert service[str(value)] == pytest.approx(agent.predict(reading).score, abs=1e-4)


def test_rejects_a_model_without_the_score_output(legacy_model_path):
    completed = run_probe(legacy_model_path)

    assert completed.returncode != 0
    assert "anomaly_score" in completed.stderr


def test_a_leftover_scaler_path_does_not_break_loading(anomaly_model_path):
    """models.yaml antigos ainda têm scaler_path — o serviço deve seguir subindo."""
    result = probe_scores(anomaly_model_path, {"scaler_path": "weights/scaler.onnx"})

    assert result["95.0"] is not None
