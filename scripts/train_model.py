"""
Treina um modelo de detecção de anomalia e exporta para ONNX.

Uso:
    python scripts/train_model.py
    python scripts/train_model.py --output models/anomaly.onnx --seed 42

O artefato gerado é autossuficiente — um arquivo só, com este contrato:

    entrada : valor bruto do sensor, float32 [N, 1]
    saída   : 'anomaly_score', float32 [N, 1], em [0, 1]

Toda a regra de score mora aqui. O agente (adapters/inference/onnx.py) e o
AI Inference Service só leem a saída.

Por que o score não é só o IsolationForest: as árvores só fazem cortes
dentro da faixa vista no treino, então todo valor além da borda cai na
mesma folha e recebe o mesmo score — 75 °C e 95 °C ficariam iguais. Por
isso o score tem duas partes:

    dentro da faixa de treino : IsolationForest, em [0, SUPPORT_BOUNDARY_SCORE]
    fora dela                 : SUPPORT_BOUNDARY_SCORE + o que falta até 1,
                                crescendo com a distância até a faixa
"""
import argparse
import math
import random
from pathlib import Path

import numpy as np
import onnx
from onnx import TensorProto, compose, helper
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import MinMaxScaler
from skl2onnx import convert_sklearn
from skl2onnx.common.data_types import FloatTensorType

OUTPUT_NAME = "anomaly_score"
INPUT_NAME = "value"

# todo valor fora da faixa de treino pontua a partir daqui
SUPPORT_BOUNDARY_SCORE = 0.8

# distância, em larguras da faixa de treino, em que o score fora da faixa
# percorre ~63% do caminho entre SUPPORT_BOUNDARY_SCORE e 1
DISTANCE_SCALE = 1.0

# pontos na faixa normalizada [0, 1] usados para achar o range do
# decision_function do IsolationForest
_SUPPORT_GRID_POINTS = 1001

_TARGET_OPSET = {"": 17, "ai.onnx.ml": 3}


def generate_normal_data(n_samples: int = 2000, seed: int = 42) -> np.ndarray:
    """
    Gera dados sintéticos representando operação normal do sensor.
    Simula a mesma lógica do SimulatedSensor no cenário 'normal'.

    Temperatura normal: ~51 °C a ~65 °C com variação senoidal e ruído.
    A semente torna o treino reproduzível.
    """
    rng = random.Random(seed)
    data = []
    for i in range(n_samples):
        t = i * 0.3
        wave  = math.sin(t) * 5.0
        noise = rng.uniform(-1.5, 1.5)
        data.append([58.0 + wave + noise])
    return np.array(data, dtype=np.float32)


def train(X_train: np.ndarray) -> tuple:
    """
    Treina o pipeline: scaler + IsolationForest.

    O MinMaxScaler é parte do contrato, não só pré-processamento: ele leva a
    faixa de treino para [0, 1], e é essa faixa que o score usa para saber
    se um valor está dentro ou fora do que o modelo conhece.
    """
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


def build_onnx(scaler, model) -> onnx.ModelProto:
    """
    Monta o artefato: scaler → IsolationForest → regra de score, num grafo só.
    """
    initial_type = [(INPUT_NAME, FloatTensorType([None, 1]))]

    scaler_onnx = convert_sklearn(scaler, initial_types=initial_type, target_opset=_TARGET_OPSET)
    forest_onnx = convert_sklearn(model,  initial_types=initial_type, target_opset=_TARGET_OPSET)
    forest_onnx = compose.add_prefix(forest_onnx, "forest_")

    scaled   = scaler_onnx.graph.output[0].name
    decision = "forest_scores"     # decision_function: > 0 normal, < 0 anômalo

    merged = compose.merge_models(
        scaler_onnx,
        forest_onnx,
        io_map=[(scaled, forest_onnx.graph.input[0].name)],
        outputs=[scaled, decision],
    )

    grid = np.linspace(0.0, 1.0, _SUPPORT_GRID_POINTS, dtype=np.float32).reshape(-1, 1)
    decisions = model.decision_function(grid)
    decision_max, decision_min = float(decisions.max()), float(decisions.min())

    _append_score_rule(merged.graph, scaled, decision, decision_max, decision_min)

    merged.doc_string = (
        "edgesentinel anomaly model: raw sensor value in, anomaly_score in [0, 1] out"
    )
    _set_metadata(merged, {
        "edgesentinel.output":                 OUTPUT_NAME,
        "edgesentinel.training_min":           f"{float(scaler.data_min_[0]):.6f}",
        "edgesentinel.training_max":           f"{float(scaler.data_max_[0]):.6f}",
        "edgesentinel.support_boundary_score": repr(SUPPORT_BOUNDARY_SCORE),
        "edgesentinel.distance_scale":         repr(DISTANCE_SCALE),
    })

    onnx.checker.check_model(merged, full_check=True)
    return merged


def _append_score_rule(
    graph: onnx.GraphProto,
    scaled: str,
    decision: str,
    decision_max: float,
    decision_min: float,
) -> None:
    """
    Acrescenta ao grafo a saída anomaly_score:

        distância  d = max(0, x - 1) + max(0, -x)       (x = valor normalizado)
        dentro     B · clip((dmax - decisão) / (dmax - dmin), 0, 1)
        fora       B + (1 - B) · (1 - exp(-d / escala))
    """
    constants = {
        "score_zero":     0.0,
        "score_one":      1.0,
        "score_dmax":     decision_max,
        "score_span":     decision_max - decision_min,
        "score_boundary": SUPPORT_BOUNDARY_SCORE,
        "score_headroom": 1.0 - SUPPORT_BOUNDARY_SCORE,
        "score_scale":    DISTANCE_SCALE,
    }
    for name, value in constants.items():
        graph.initializer.append(helper.make_tensor(name, TensorProto.FLOAT, [], [value]))

    node = helper.make_node
    graph.node.extend([
        # distância até a faixa de treino, em larguras da faixa
        node("Sub",  [scaled, "score_one"],           ["score_past_top"]),
        node("Relu", ["score_past_top"],              ["score_above"]),
        node("Neg",  [scaled],                        ["score_past_bottom"]),
        node("Relu", ["score_past_bottom"],           ["score_below"]),
        node("Add",  ["score_above", "score_below"],  ["score_distance"]),

        # dentro da faixa: IsolationForest reescalado para [0, B]
        node("Sub",  ["score_dmax", decision],                    ["score_gap"]),
        node("Div",  ["score_gap", "score_span"],                 ["score_ratio"]),
        node("Clip", ["score_ratio", "score_zero", "score_one"],  ["score_ratio_clipped"]),
        node("Mul",  ["score_ratio_clipped", "score_boundary"],   ["score_inside"]),

        # fora da faixa: de B até 1, crescendo com a distância
        node("Div",  ["score_distance", "score_scale"],   ["score_scaled_distance"]),
        node("Neg",  ["score_scaled_distance"],           ["score_neg_distance"]),
        node("Exp",  ["score_neg_distance"],              ["score_decay"]),
        node("Sub",  ["score_one", "score_decay"],        ["score_growth"]),
        node("Mul",  ["score_growth", "score_headroom"],  ["score_extra"]),
        node("Add",  ["score_boundary", "score_extra"],   ["score_outside"]),

        node("Greater", ["score_distance", "score_zero"],                  ["score_is_outside"]),
        node("Where",   ["score_is_outside", "score_outside", "score_inside"], [OUTPUT_NAME]),
    ])

    del graph.output[:]
    graph.output.append(helper.make_tensor_value_info(OUTPUT_NAME, TensorProto.FLOAT, [None, 1]))


def _set_metadata(model: onnx.ModelProto, values: dict[str, str]) -> None:
    del model.metadata_props[:]
    for key, value in values.items():
        entry = model.metadata_props.add()
        entry.key, entry.value = key, value


def export_onnx(scaler, model, output_path: Path) -> None:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(build_onnx(scaler, model).SerializeToString())
    print(f"\n  Modelo salvo em: {output_path}")


def evaluate(model_path: Path, X_train: np.ndarray) -> None:
    """Imprime o score do artefato exportado em pontos de referência."""
    import onnxruntime as ort

    session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
    low, high = float(X_train.min()), float(X_train.max())
    width = high - low

    points = [
        ("abaixo, 1 largura",  low - width),
        ("borda inferior",     low),
        ("centro",             (low + high) / 2),
        ("borda superior",     high),
        ("acima, 1/2 largura", high + width / 2),
        ("75 °C",              75.0),
        ("85 °C",              85.0),
        ("95 °C",              95.0),
    ]
    x = np.array([[v] for _, v in points], dtype=np.float32)
    scores = session.run([OUTPUT_NAME], {INPUT_NAME: x})[0].ravel()

    print(f"  Faixa de treino: {low:.1f} ~ {high:.1f}")
    for (label, value), score in zip(points, scores):
        flag = "← anomalia" if score >= SUPPORT_BOUNDARY_SCORE else ""
        print(f"    {label:<20} {value:>7.1f}  →  score {score:.4f}  {flag}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Treina e exporta modelo de anomalia para ONNX")
    parser.add_argument("--output", type=Path, default=Path("models/anomaly.onnx"))
    parser.add_argument("--samples", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    print("\nTreinando modelo de detecção de anomalia...")
    print(f"  Amostras: {args.samples}  |  semente: {args.seed}")

    print("\n[1/4] Gerando dados de treino (operação normal)...")
    X_train = generate_normal_data(args.samples, seed=args.seed)
    print(f"  Range: {X_train.min():.1f}°C ~ {X_train.max():.1f}°C")

    print("\n[2/4] Treinando scaler + IsolationForest...")
    scaler, model = train(X_train)
    print("  Treinamento concluído.")

    print("\n[3/4] Exportando para ONNX...")
    export_onnx(scaler, model, args.output)

    print("\n[4/4] Avaliando o artefato exportado...")
    evaluate(args.output, X_train)

    print("\nConcluído. Para usar no edgesentinel:")
    print(f"  Edite o config.yaml:")
    print(f"    inference:")
    print(f"      enabled: true")
    print(f"      backend: onnx")
    print(f"      model_path: {args.output}")
    print()


if __name__ == "__main__":
    main()
