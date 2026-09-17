"""
Contrato do artefato gerado por scripts/train_model.py — o que o agente e o
AI Inference Service podem assumir de qualquer modelo de anomalia:

  entrada : o valor bruto do sensor, float32 [N, 1]
  saída   : 'anomaly_score', float32 [N, 1], em [0, 1]
"""
import numpy as np
import pytest

onnx = pytest.importorskip("onnx")
ort = pytest.importorskip("onnxruntime")


def session_for(path):
    return ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])


def scores(path, values):
    session = session_for(path)
    x = np.array([[v] for v in values], dtype=np.float32)
    return session.run(["anomaly_score"], {session.get_inputs()[0].name: x})[0].ravel()


def metadata(path) -> dict[str, str]:
    return {p.key: p.value for p in onnx.load(str(path)).metadata_props}


class TestArtifact:

    def test_export_writes_a_single_file(self, train_model, tmp_path):
        scaler, model = train_model.train(train_model.generate_normal_data(n_samples=300))

        train_model.export_onnx(scaler, model, tmp_path / "anomaly.onnx")

        assert sorted(p.name for p in tmp_path.iterdir()) == ["anomaly.onnx"]

    def test_passes_the_onnx_checker(self, anomaly_model_path):
        onnx.checker.check_model(onnx.load(str(anomaly_model_path)), full_check=True)

    def test_takes_one_raw_value(self, anomaly_model_path):
        (single,) = session_for(anomaly_model_path).get_inputs()

        assert single.type == "tensor(float)"
        assert single.shape[1] == 1

    def test_exposes_only_the_anomaly_score(self, anomaly_model_path):
        outputs = session_for(anomaly_model_path).get_outputs()

        assert [o.name for o in outputs] == ["anomaly_score"]
        assert outputs[0].type == "tensor(float)"

    def test_scores_a_batch_like_individual_values(self, anomaly_model_path):
        values = [20.0, 58.0, 95.0]

        batch = scores(anomaly_model_path, values)
        one_by_one = [scores(anomaly_model_path, [v])[0] for v in values]

        np.testing.assert_allclose(batch, one_by_one)


class TestMetadata:

    def test_records_the_training_range(self, anomaly_model_path):
        meta = metadata(anomaly_model_path)
        low, high = float(meta["edgesentinel.training_min"]), float(meta["edgesentinel.training_max"])

        # dados de referência: 58 °C ± 5 de onda ± 1.5 de ruído
        assert 50.0 < low < high < 66.0

    def test_records_the_scoring_constants(self, anomaly_model_path, train_model):
        meta = metadata(anomaly_model_path)

        assert float(meta["edgesentinel.support_boundary_score"]) == train_model.SUPPORT_BOUNDARY_SCORE
        assert float(meta["edgesentinel.distance_scale"]) == train_model.DISTANCE_SCALE
        assert meta["edgesentinel.output"] == "anomaly_score"

    def test_boundary_score_starts_right_past_the_training_range(self, anomaly_model_path, train_model):
        meta = metadata(anomaly_model_path)
        low, high = float(meta["edgesentinel.training_min"]), float(meta["edgesentinel.training_max"])
        step = (high - low) * 0.01
        boundary = train_model.SUPPORT_BOUNDARY_SCORE

        just_below, just_above = scores(anomaly_model_path, [low - step, high + step])

        assert boundary <= just_below < boundary + 0.01
        assert boundary <= just_above < boundary + 0.01


class TestTraining:

    def test_data_is_reproducible_for_a_seed(self, train_model):
        first = train_model.generate_normal_data(n_samples=100, seed=7)
        second = train_model.generate_normal_data(n_samples=100, seed=7)

        np.testing.assert_array_equal(first, second)

    def test_different_seeds_give_different_data(self, train_model):
        first = train_model.generate_normal_data(n_samples=100, seed=7)
        second = train_model.generate_normal_data(n_samples=100, seed=8)

        assert not np.array_equal(first, second)
