import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def train_model():
    """
    scripts/train_model.py carregado como módulo. scripts/ não é pacote,
    e o script precisa de scikit-learn e skl2onnx — ausentes, os testes
    que dependem dele são pulados.
    """
    pytest.importorskip("sklearn")
    pytest.importorskip("skl2onnx")
    pytest.importorskip("onnxruntime")

    spec = importlib.util.spec_from_file_location(
        "train_model", ROOT / "scripts" / "train_model.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def anomaly_model_path(train_model, tmp_path_factory) -> Path:
    """
    Modelo treinado e exportado uma vez por sessão, num diretório próprio.
    Os pesos não são versionados, então os testes não podem depender de
    models/anomaly.onnx existir.
    """
    path = tmp_path_factory.mktemp("trained") / "anomaly.onnx"
    scaler, model = train_model.train(train_model.generate_normal_data())
    train_model.export_onnx(scaler, model, path)
    return path


@pytest.fixture(scope="session")
def legacy_model_path(train_model, tmp_path_factory) -> Path:
    """
    Artefato no formato anterior: IsolationForest puro, sem a saída
    anomaly_score. O score derivado dele é exatamente o que estava errado.
    """
    from skl2onnx import convert_sklearn
    from skl2onnx.common.data_types import FloatTensorType

    _, model = train_model.train(train_model.generate_normal_data())
    legacy = convert_sklearn(
        model,
        initial_types=[("float_input", FloatTensorType([None, 1]))],
        target_opset={"": 17, "ai.onnx.ml": 3},
    )
    path = tmp_path_factory.mktemp("legacy") / "anomaly.onnx"
    path.write_bytes(legacy.SerializeToString())
    return path
