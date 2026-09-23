"""
docs/roadmap.json é fonte de verdade do backlog, e fonte de verdade que
ninguém verifica vira ficção: status que não corresponde ao grafo, aresta
que só existe num sentido, commit de entrega que não existe no repositório.

O que este arquivo cobra é a coerência interna. Se uma feature está 'done',
suas dependências também estão e o delivered_in aponta para um commit real;
se está 'ready', nada pendente a segura.

Cada teste avalia as 48 features de uma vez e nomeia todas as que falham:
uma linha por feature quebrada é pior de ler que uma lista.
"""
import json
import subprocess
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ROADMAP = json.loads((ROOT / "docs" / "roadmap.json").read_text(encoding="utf-8"))

FEATURES = ROADMAP["features"]
BY_ID = {f["id"]: f for f in FEATURES}
MILESTONE_ORDER = {m["id"]: i for i, m in enumerate(ROADMAP["milestones"])}
IDS = [f["id"] for f in FEATURES]

REQUIRED = (
    "title", "does", "adds", "milestone", "status", "effort", "portfolio_value",
    "testable_now", "rationale", "depends_on", "unlocks", "touches",
    "design_notes", "acceptance", "tests",
)
STATUSES = ("ready", "planned", "blocked", "done")

# does e adds existem para serem lidos de relance na listagem do backlog
RESUMO_MAX = 400


def pending(feature: dict) -> list[str]:
    """Dependências da feature que ainda não foram entregues."""
    return [d for d in feature["depends_on"] if BY_ID[d]["status"] != "done"]


def git_repo_is_complete() -> bool:
    """Clone raso não tem os commits antigos; ali a verificação não vale."""
    try:
        shallow = subprocess.run(
            ["git", "rev-parse", "--is-shallow-repository"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return False

    return shallow.stdout.strip() == "false"


class TestShape:
    """Cada feature declara o mínimo para ser lida sem abrir o código."""

    def test_ids_are_unique(self):
        duplicados = [i for i, n in Counter(IDS).items() if n > 1]

        assert duplicados == [], f"ids repetidos: {duplicados}"

    def test_every_feature_declares_the_required_fields(self):
        faltando = {
            f["id"]: [k for k in REQUIRED if k not in f]
            for f in FEATURES
            if any(k not in f for k in REQUIRED)
        }

        assert faltando == {}, f"campos ausentes: {faltando}"

    def test_milestones_and_statuses_are_known(self):
        erradas = {
            f["id"]: (f.get("milestone"), f.get("status"))
            for f in FEATURES
            if f.get("milestone") not in MILESTONE_ORDER or f.get("status") not in STATUSES
        }

        assert erradas == {}, f"marco ou status inválido: {erradas}"

    def test_the_summary_fields_stay_short(self):
        """does e adds são resumo: passando disso, viram o rationale de novo."""
        longos = {
            f["id"]: {k: len(f[k]) for k in ("does", "adds") if len(f.get(k, "")) > RESUMO_MAX}
            for f in FEATURES
            if any(len(f.get(k, "")) > RESUMO_MAX for k in ("does", "adds"))
        }

        assert longos == {}, f"resumos acima de {RESUMO_MAX} caracteres: {longos}"


class TestGraph:
    """As dependências formam um grafo navegável nos dois sentidos."""

    def test_every_reference_points_at_an_existing_feature(self):
        desconhecidas = {
            f["id"]: [r for r in f["depends_on"] + f["unlocks"] if r not in BY_ID]
            for f in FEATURES
            if any(r not in BY_ID for r in f["depends_on"] + f["unlocks"])
        }

        assert desconhecidas == {}, f"referências inexistentes: {desconhecidas}"

    def test_dependencies_are_mirrored_by_unlocks(self):
        """
        As duas arestas existem para ler o grafo nos dois sentidos, e uma
        delas escrita sozinha é pior que nenhuma: some da leitura oposta.
        """
        quebradas = []
        for f in FEATURES:
            quebradas += [
                f"{f['id']} depende de {d}, que não o destrava"
                for d in f["depends_on"] if f["id"] not in BY_ID[d]["unlocks"]
            ]
            quebradas += [
                f"{f['id']} destrava {u}, que não depende dele"
                for u in f["unlocks"] if f["id"] not in BY_ID[u]["depends_on"]
            ]

        assert quebradas == [], f"arestas em um sentido só: {quebradas}"

    def test_no_feature_depends_on_a_later_milestone(self):
        """
        Dependência em marco posterior é marco que não fecha: para entregar
        o de agora seria preciso entregar antes o que vem depois.
        """
        invertidas = [
            f"{f['id']} ({f['milestone']}) depende de {d} ({BY_ID[d]['milestone']})"
            for f in FEATURES
            for d in f["depends_on"]
            if MILESTONE_ORDER[BY_ID[d]["milestone"]] > MILESTONE_ORDER[f["milestone"]]
        ]

        assert invertidas == [], f"dependência em marco posterior: {invertidas}"

    def test_the_dependency_graph_is_acyclic(self):
        cor = dict.fromkeys(IDS, 0)
        ciclos: list[str] = []

        def visita(node: str, caminho: list[str]) -> None:
            cor[node] = 1
            for dep in BY_ID[node]["depends_on"]:
                if cor[dep] == 1:
                    ciclos.append(" -> ".join(caminho + [node, dep]))
                elif cor[dep] == 0:
                    visita(dep, caminho + [node])
            cor[node] = 2

        for fid in IDS:
            if cor[fid] == 0:
                visita(fid, [])

        assert ciclos == [], f"ciclos no grafo: {ciclos}"


class TestStatus:
    """Status é derivado do grafo, não é opinião sobre a feature."""

    def test_delivered_features_have_no_pending_dependency(self):
        impossiveis = {
            f["id"]: pending(f) for f in FEATURES
            if f["status"] == "done" and pending(f)
        }

        assert impossiveis == {}, f"done dependendo do que não foi entregue: {impossiveis}"

    def test_ready_means_nothing_is_holding_it(self):
        travadas = {
            f["id"]: pending(f) for f in FEATURES
            if f["status"] == "ready" and pending(f)
        }

        assert travadas == {}, f"ready com dependência pendente: {travadas}"

    def test_planned_means_something_is_holding_it(self):
        livres = [f["id"] for f in FEATURES if f["status"] == "planned" and not pending(f)]

        assert livres == [], f"planned sem dependência pendente (deveriam ser ready): {livres}"

    def test_blocked_features_say_what_blocks_them(self):
        mudas = [f["id"] for f in FEATURES if f["status"] == "blocked" and not f.get("blocked_by")]

        assert mudas == [], f"blocked sem blocked_by: {mudas}"

    def test_only_delivered_features_name_a_commit(self):
        sem_commit = [f["id"] for f in FEATURES if f["status"] == "done" and not f.get("delivered_in")]
        commit_a_mais = [f["id"] for f in FEATURES if f["status"] != "done" and "delivered_in" in f]

        assert sem_commit == [], f"done sem delivered_in: {sem_commit}"
        assert commit_a_mais == [], f"delivered_in em feature não entregue: {commit_a_mais}"

    @pytest.mark.skipif(not git_repo_is_complete(), reason="sem repositório git completo")
    def test_delivered_commits_exist_in_this_repository(self):
        ausentes = [
            f"{f['id']} ({f['delivered_in']})"
            for f in FEATURES
            if f["status"] == "done" and subprocess.run(
                ["git", "cat-file", "-e", f"{f['delivered_in']}^{{commit}}"],
                cwd=ROOT, capture_output=True,
            ).returncode != 0
        ]

        assert ausentes == [], f"delivered_in que não existe neste repositório: {ausentes}"
