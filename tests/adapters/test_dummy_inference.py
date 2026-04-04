from adapters.inference.dummy import DummyInferenceAdapter


class TestDummyInferenceAdapter:

    def test_always_returns_zero_score(self, cpu_reading):
        adapter = DummyInferenceAdapter()
        score = adapter.predict(cpu_reading)
        assert score.score == 0.0

    def test_is_never_anomaly(self, cpu_reading):
        adapter = DummyInferenceAdapter()
        score = adapter.predict(cpu_reading)
        assert score.is_anomaly is False

    def test_model_id_is_dummy(self, cpu_reading):
        adapter = DummyInferenceAdapter()
        score = adapter.predict(cpu_reading)
        assert score.model_id == "dummy"

    def test_load_does_nothing(self, cpu_reading):
        """load() do dummy não deve lançar erro."""
        adapter = DummyInferenceAdapter()
        adapter.load("qualquer/caminho.onnx")   # não deve explodir
        score = adapter.predict(cpu_reading)
        assert score.score == 0.0

    def test_carries_original_reading(self, cpu_reading):
        adapter = DummyInferenceAdapter()
        score = adapter.predict(cpu_reading)
        assert score.reading is cpu_reading

    def test_custom_threshold(self, cpu_reading):
        adapter = DummyInferenceAdapter(threshold=0.5)
        score = adapter.predict(cpu_reading)
        assert score.threshold == 0.5