"""
Trains an anomaly detection model and exports it to ONNX.

Usage:
    python scripts/train_model.py
    python scripts/train_model.py --output models/anomaly.onnx --seed 42

The artifact produced is self-contained — one file, with this contract:

    input  : the raw sensor value, float32 [N, 1]
    output : 'anomaly_score', float32 [N, 1], within [0, 1]

The whole scoring rule lives here. The agent (adapters/inference/onnx.py) and
the AI Inference Service only read the output.

Why the score is not the IsolationForest alone: the trees only cut inside the
range seen during training, so every value past the edge lands in the same leaf
and gets the same score — 75 °C and 95 °C would come out equal. So the score has
two parts:

    inside the training range : IsolationForest, within [0, SUPPORT_BOUNDARY_SCORE]
    outside it                : SUPPORT_BOUNDARY_SCORE plus whatever is left up
                                to 1, growing with the distance to the range
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

# every value outside the training range scores from here up
SUPPORT_BOUNDARY_SCORE = 0.8

# the distance, in widths of the training range, at which the out-of-range
# score covers ~63% of the way from SUPPORT_BOUNDARY_SCORE to 1
DISTANCE_SCALE = 1.0

# points on the normalized [0, 1] range, used to find the range of the
# decision_function do IsolationForest
_SUPPORT_GRID_POINTS = 1001

_TARGET_OPSET = {"": 17, "ai.onnx.ml": 3}


def generate_normal_data(n_samples: int = 2000, seed: int = 42) -> np.ndarray:
    """
    Generates synthetic data representing normal sensor operation.
    Mirrors the same logic SimulatedSensor uses in the 'normal' scenario.

    Normal temperature: ~51 °C to ~65 °C, with a sinusoidal swing and noise.
    The seed is what makes the training reproducible.
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
    Trains the pipeline: scaler + IsolationForest.

    The MinMaxScaler is part of the contract, not merely preprocessing: it maps
    the training range onto [0, 1], and that range is what the score uses to
    tell whether a value is inside or outside what the model has seen.
    """
    scaler = MinMaxScaler(feature_range=(0, 1))
    X_scaled = scaler.fit_transform(X_train)

    # contamination=0.05 — assumes up to 5% of the training data are outliers
    model = IsolationForest(
        n_estimators=100,
        contamination=0.05,
        random_state=42,
    )
    model.fit(X_scaled)

    return scaler, model


def build_onnx(scaler, model) -> onnx.ModelProto:
    """
    Assembles the artifact: scaler → IsolationForest → scoring rule, one graph.
    """
    initial_type = [(INPUT_NAME, FloatTensorType([None, 1]))]

    scaler_onnx = convert_sklearn(scaler, initial_types=initial_type, target_opset=_TARGET_OPSET)
    forest_onnx = convert_sklearn(model,  initial_types=initial_type, target_opset=_TARGET_OPSET)
    forest_onnx = compose.add_prefix(forest_onnx, "forest_")

    scaled   = scaler_onnx.graph.output[0].name
    decision = "forest_scores"     # decision_function: > 0 normal, < 0 anomalous

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
    Adds the anomaly_score output to the graph:

        distance  d = max(0, x - 1) + max(0, -x)       (x = normalized value)
        inside    B · clip((dmax - decision) / (dmax - dmin), 0, 1)
        outside   B + (1 - B) · (1 - exp(-d / scale))
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
        # distance to the training range, in widths of that range
        node("Sub",  [scaled, "score_one"],           ["score_past_top"]),
        node("Relu", ["score_past_top"],              ["score_above"]),
        node("Neg",  [scaled],                        ["score_past_bottom"]),
        node("Relu", ["score_past_bottom"],           ["score_below"]),
        node("Add",  ["score_above", "score_below"],  ["score_distance"]),

        # inside the range: IsolationForest rescaled onto [0, B]
        node("Sub",  ["score_dmax", decision],                    ["score_gap"]),
        node("Div",  ["score_gap", "score_span"],                 ["score_ratio"]),
        node("Clip", ["score_ratio", "score_zero", "score_one"],  ["score_ratio_clipped"]),
        node("Mul",  ["score_ratio_clipped", "score_boundary"],   ["score_inside"]),

        # outside the range: from B up to 1, growing with the distance
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
    """Prints the exported artifact's score at a few reference points."""
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
    for (label, value), score in zip(points, scores, strict=True):
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
    print("  Edite o config.yaml:")
    print("    inference:")
    print("      enabled: true")
    print("      backend: onnx")
    print(f"      model_path: {args.output}")
    print()


if __name__ == "__main__":
    main()
