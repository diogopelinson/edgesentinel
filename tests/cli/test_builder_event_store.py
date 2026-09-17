from cli.builder import build_event_store
from config.schema import EdgeSentinelConfig, EventStoreConfig


def make_config(event_store: EventStoreConfig) -> EdgeSentinelConfig:
    return EdgeSentinelConfig(
        sensors=[],
        rules=[],
        actions=[],
        event_store=event_store,
    )


class TestBuildEventStore:

    def test_returns_none_when_disabled(self):
        config = make_config(EventStoreConfig(enabled=False))

        assert build_event_store(config) is None

    def test_builds_a_store_at_the_configured_path(self, tmp_path):
        path   = tmp_path / "custom" / "events.db"
        config = make_config(EventStoreConfig(path=str(path)))

        store = build_event_store(config)
        store.start()
        store.close()

        assert path.exists()

    def test_does_not_touch_the_disk_before_start(self, tmp_path):
        """
        Construir não abre nada: quem controla quando o banco é criado é o
        MonitorLoop, junto com o resto do ciclo de vida.
        """
        path   = tmp_path / "events.db"
        config = make_config(EventStoreConfig(path=str(path)))

        build_event_store(config)

        assert not path.exists()
