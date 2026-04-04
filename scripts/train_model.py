"""
Treina um modelo de detecção de anomalia e exporta para ONNX.

Uso:
    python scripts/train_model.py
    python scripts/train_model.py --output models/anomaly.onnx
"""
import argparse
import math
import random
import time
from pathlib import Path

import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import MinMaxScaler
from skl2onnx import convert_sklearn
from skl2onnx.common.data_types import FloatTensorType


def generate_normal_data(n_samples: int = 2000) -> np.ndarray:
    """
    Gera dados sintéticos representando operação normal do sensor.
    Simula a mesma lógica do SimulatedSensor no cenário 'normal'.

    Temperatura normal: 50°C ~ 68°C com variação senoidal e ruído.
    """
    data = []
    for i in range(n_samples):
        t = i * 0.3
        wave  = math.sin(t) * 5.0
        noise = random.uniform(-1.5, 1.5)
        value = 58.0 + wave + noise
        data.append([value])
    return np.array(data, dtype=np.float32)


def train(X_train: np.ndarray) -> tuple:
    """
    Treina o pipeline: scaler + IsolationForest.

    Retorna o scaler e o modelo treinado separadamente
    porque o ONNX precisa que cada etapa seja convertida.
    """
    # normaliza para [0, 1] — IsolationForest performa melhor com dados normalizados
    scaler = MinMaxScaler(feature_range=(0, 1))
    X_scaled = scaler.fit_transform(X_train)

    # contamination=0.05 — assume que 5% dos dados de treino podem ser outliers
    model = IsolationForest(
        n_estimators=100,
        contamination=0.05,
        random_state=42,
    )
    model.fit(X_scaled)

    return scaler, model


def evaluate(scaler, model, X_train: np.ndarray) -> None:
    """Imprime métricas básicas para validar o modelo treinado."""
    X_scaled = scaler.transform(X_train)

    # score_samples retorna scores negativos — quanto mais negativo, mais anômalo
    raw_scores = model.score_samples(X_scaled)

    # normaliza para [0, 1] onde 1 = mais anômalo
    scores_normalized = 1 - (raw_scores - raw_scores.min()) / (raw_scores.max() - raw_scores.min())

    print(f"  Dados de treino: {len(X_train)} amostras")
    print(f"  Score médio (normal):  {scores_normalized.mean():.3f}")
    print(f"  Score máximo (normal): {scores_normalized.max():.3f}")

    # testa com valores claramente anômalos
    anomaly_values = np.array([[85.0], [90.0], [95.0]], dtype=np.float32)
    X_anom_scaled = scaler.transform(anomaly_values)
    raw_anom = model.score_samples(X_anom_scaled)
    scores_anom = 1 - (raw_anom - raw_scores.min()) / (raw_scores.max() - raw_scores.min())

    print(f"\n  Teste com valores anômalos:")
    for val, score in zip(anomaly_values.flatten(), scores_anom):
        flag = "← anomalia detectada" if score > 0.5 else ""
        print(f"    {val:.1f}°C  →  score {score:.3f}  {flag}")


def export_onnx(scaler, model, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    initial_type = [("float_input", FloatTensorType([None, 1]))]

    # target_opset fixa a versão compatível com o onnxruntime instalado
    target_opset = {"": 17, "ai.onnx.ml": 3}

    scaler_onnx = convert_sklearn(
        scaler,
        initial_types=initial_type,
        target_opset=target_opset,
    )

    model_onnx = convert_sklearn(
        model,
        initial_types=initial_type,
        target_opset=target_opset,
        options={IsolationForest: {"score_samples": True}},
    )

    scaler_path = output_path.parent / "scaler.onnx"
    model_path  = output_path

    with open(scaler_path, "wb") as f:
        f.write(scaler_onnx.SerializeToString())

    with open(model_path, "wb") as f:
        f.write(model_onnx.SerializeToString())

    print(f"\n  Scaler salvo em: {scaler_path}")
    print(f"  Modelo salvo em: {model_path}")

def main() -> None:
    parser = argparse.ArgumentParser(description="Treina e exporta modelo de anomalia para ONNX")
    parser.add_argument("--output", type=Path, default=Path("models/anomaly.onnx"))
    parser.add_argument("--samples", type=int, default=2000)
    args = parser.parse_args()

    print("\nTreinando modelo de detecção de anomalia...")
    print(f"  Amostras: {args.samples}")

    print("\n[1/4] Gerando dados de treino (operação normal)...")
    X_train = generate_normal_data(args.samples)
    print(f"  Range: {X_train.min():.1f}°C ~ {X_train.max():.1f}°C")

    print("\n[2/4] Treinando scaler + IsolationForest...")
    scaler, model = train(X_train)
    print("  Treinamento concluído.")

    print("\n[3/4] Avaliando modelo...")
    evaluate(scaler, model, X_train)

    print("\n[4/4] Exportando para ONNX...")
    export_onnx(scaler, model, args.output)

    print("\nConcluído. Para usar no edgesentinel:")
    print(f"  Edite o config.yaml:")
    print(f"    inference:")
    print(f"      enabled: true")
    print(f"      backend: onnx")
    print(f"      model_path: {args.output}")
    print()


if __name__ == "__main__":
    main()