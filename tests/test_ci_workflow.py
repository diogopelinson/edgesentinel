"""
O workflow de CI é configuração que ninguém executa localmente: um erro nele
só aparece depois do push, e alguns erros não aparecem nunca — passam verde
verificando menos do que deveriam.

O que este arquivo cobra é isso: que o arquivo seja YAML válido, que a matriz
cubra o que o pyproject.toml promete suportar, e que o checkout traga o
histórico completo, sem o qual a verificação dos commits de entrega do
roadmap se ignora sozinha e o job passa sem checar nada.
"""
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "tests.yml"


def carrega() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def versao(texto: str) -> tuple[int, ...]:
    return tuple(int(parte) for parte in texto.strip().split("."))


def minimo_suportado() -> tuple[int, ...]:
    import tomli

    requires = tomli.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return versao(requires["project"]["requires-python"].lstrip(">=~^ "))


@pytest.fixture(scope="module")
def workflow() -> dict:
    return carrega()


def test_the_workflow_is_valid_yaml(workflow):
    assert isinstance(workflow, dict)
    assert workflow["jobs"], "nenhum job declarado"


def test_it_runs_on_push_and_on_pull_request(workflow):
    # 'on' vira True no YAML 1.1, que é o que o PyYAML implementa
    gatilhos = workflow.get("on") or workflow[True]

    assert "push" in gatilhos
    assert "pull_request" in gatilhos


def test_the_matrix_covers_the_minimum_supported_python(workflow):
    """
    requires-python é a promessa; a matriz é a verificação dela. A versão
    mínima é a que mais quebra, porque é nela que uma sintaxe nova falha.
    """
    matriz = [versao(v) for v in workflow["jobs"]["linux"]["strategy"]["matrix"]["python-version"]]

    assert minimo_suportado() in matriz, f"matriz {matriz} não inclui {minimo_suportado()}"
    assert len(matriz) >= 2, "uma versão só não é matriz"


def test_no_job_runs_a_python_older_than_supported(workflow):
    minimo = minimo_suportado()
    antigas = [
        v for v in workflow["jobs"]["linux"]["strategy"]["matrix"]["python-version"]
        if versao(v) < minimo
    ]

    assert antigas == [], f"matriz testa versões não suportadas: {antigas}"


@pytest.mark.parametrize("job", ["linux", "windows"])
def test_every_job_checks_out_the_full_history(workflow, job):
    """
    Sem fetch-depth 0 o clone é raso, e tests/test_roadmap.py se ignora por não
    achar os commits antigos: o job continuaria verde verificando menos.
    """
    checkout = next(
        passo for passo in workflow["jobs"][job]["steps"]
        if str(passo.get("uses", "")).startswith("actions/checkout")
    )

    assert checkout.get("with", {}).get("fetch-depth") == 0


@pytest.mark.parametrize("job", ["linux", "windows"])
def test_every_job_installs_the_optional_dependencies_the_tests_need(workflow, job):
    """
    Sem sklearn, skl2onnx, onnx e cv2, dezoito testes de modelo e de payload
    se ignoram — e um job verde com 18 testes a menos não avisa ninguém.
    """
    instalacao = "\n".join(
        str(passo.get("run", "")) for passo in workflow["jobs"][job]["steps"]
    )
    faltando = [
        pacote for pacote in ("scikit-learn", "skl2onnx", "onnx", "opencv-python-headless")
        if pacote not in instalacao
    ]

    assert faltando == [], f"job '{job}' não instala: {faltando}"


def test_the_readmes_point_at_this_workflow():
    """Badge apontando para workflow inexistente é pior que badge nenhum."""
    nome = WORKFLOW.name
    for readme in ("README.md", "README-BR.md"):
        texto = (ROOT / readme).read_text(encoding="utf-8")

        assert f"workflows/{nome}" in texto, f"{readme} não cita o workflow {nome}"
