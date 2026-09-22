"""
Contrato do StatePort, parametrizado por implementação.

O RedisState da v0.6 entra em IMPLEMENTATIONS e passa pelos mesmos testes:
é o que garante que trocar estado local por distribuído seja um adapter, e
não uma reescrita do que usa o estado.
"""
import threading
import time

import pytest

from adapters.state.memory import InMemoryState

IMPLEMENTATIONS = {"memory": InMemoryState}


@pytest.fixture(params=sorted(IMPLEMENTATIONS))
def state(request):
    return IMPLEMENTATIONS[request.param]()


class TestTryAcquire:
    """
    try_acquire(key, ttl) toma a chave por ttl segundos. Não expõe
    timestamp nenhum: o relógio monotônico de um processo não tem
    significado em outro, e é o Redis que expira a chave no caso distribuído.
    """

    def test_first_acquire_succeeds(self, state):
        assert state.try_acquire("cooldown:alta_temp", 60.0) is True

    def test_second_acquire_within_the_ttl_fails(self, state):
        state.try_acquire("cooldown:alta_temp", 60.0)

        assert state.try_acquire("cooldown:alta_temp", 60.0) is False

    def test_acquire_succeeds_again_after_the_ttl(self, state):
        state.try_acquire("cooldown:alta_temp", 0.1)
        time.sleep(0.15)

        assert state.try_acquire("cooldown:alta_temp", 0.1) is True

    def test_keys_are_independent(self, state):
        state.try_acquire("cooldown:alta_temp", 60.0)

        assert state.try_acquire("cooldown:uso_alto_cpu", 60.0) is True

    @pytest.mark.parametrize("ttl", [0.0, -5.0])
    def test_a_ttl_of_zero_or_less_always_succeeds(self, state, ttl):
        """Regra sem cooldown dispara sempre — nada é guardado."""
        assert [state.try_acquire("cooldown:sem_cooldown", ttl) for _ in range(3)] == [True] * 3

    def test_exactly_one_caller_wins_a_concurrent_acquire(self, state):
        """
        Os pipelines rodam em threads do executor e compartilham o engine.
        A versão anterior comparava e escrevia o timestamp em passos
        separados, então duas threads podiam disparar a mesma regra.
        """
        threads_count = 20
        ready = threading.Barrier(threads_count)
        results = []
        lock = threading.Lock()

        def attempt():
            ready.wait()
            acquired = state.try_acquire("cooldown:corrida", 60.0)
            with lock:
                results.append(acquired)

        threads = [threading.Thread(target=attempt) for _ in range(threads_count)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert results.count(True) == 1, results


class TestValues:
    """get/set guardam o estado que o ciclo de incidente (v0.4) vai precisar."""

    def test_an_unset_key_reads_as_none(self, state):
        assert state.get("incident:alta_temp") is None

    def test_set_then_get(self, state):
        state.set("incident:alta_temp", "TRIGGERED")

        assert state.get("incident:alta_temp") == "TRIGGERED"

    def test_set_overwrites(self, state):
        state.set("incident:alta_temp", "TRIGGERED")
        state.set("incident:alta_temp", "ACKNOWLEDGED")

        assert state.get("incident:alta_temp") == "ACKNOWLEDGED"

    def test_values_and_cooldowns_do_not_share_a_namespace(self, state):
        """Um valor guardado não pode consumir o cooldown da mesma chave."""
        state.set("alta_temp", "TRIGGERED")

        assert state.try_acquire("alta_temp", 60.0) is True
        assert state.get("alta_temp") == "TRIGGERED"
