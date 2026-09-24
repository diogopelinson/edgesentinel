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
WORKFLOWS = ROOT / ".github" / "workflows"
WORKFLOW = WORKFLOWS / "tests.yml"
DEPENDABOT = ROOT / ".github" / "dependabot.yml"


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


def jobs_do_workflow() -> list[str]:
    """Derivado do arquivo: job novo entra na verificação por existir."""
    return sorted(carrega()["jobs"])


def comandos(workflow: dict, job: str) -> str:
    return "\n".join(str(passo.get("run", "")) for passo in workflow["jobs"][job]["steps"])


@pytest.mark.parametrize("job", jobs_do_workflow())
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


@pytest.mark.parametrize("job", jobs_do_workflow())
def test_every_job_that_runs_the_suite_installs_what_it_needs(workflow, job):
    """
    Sem sklearn, skl2onnx, onnx e cv2, dezoito testes de modelo e de payload
    se ignoram — e um job verde com 18 testes a menos não avisa ninguém.
    """
    instalacao = comandos(workflow, job)
    if "pytest tests/" not in instalacao:
        pytest.skip(f"job '{job}' não roda a suíte")

    faltando = [
        pacote for pacote in ("scikit-learn", "skl2onnx", "onnx", "opencv-python-headless")
        if pacote not in instalacao
    ]

    assert faltando == [], f"job '{job}' não instala: {faltando}"


def test_some_job_runs_ruff_and_mypy(workflow):
    """
    O gate de estilo e de tipos só vale se rodar sozinho. Rodado à mão, ele é
    uma recomendação — e recomendação de lint é lint desligado.
    """
    tudo = "\n".join(comandos(workflow, job) for job in workflow["jobs"])

    assert "ruff check" in tudo, "nenhum job roda o ruff"
    assert "mypy" in tudo, "nenhum job roda o mypy"


def test_some_job_boots_the_agent_as_a_process(workflow):
    """
    A suíte cobre funções; o smoke cobre o processo. Sem ele, a classe de
    defeito que passa verde e só aparece rodando o comando não tem quem pegue —
    foi assim com o 'python -m' que não executava nada.
    """
    tudo = "\n".join(comandos(workflow, job) for job in workflow["jobs"])
    script = ROOT / "scripts" / "smoke.py"

    assert "scripts/smoke.py" in tudo, "nenhum job roda a verificação de fumaça"
    assert script.exists(), "o workflow chama um script que não existe"


class TestOutrosWorkflows:
    """
    Todo arquivo em .github/workflows é configuração que só executa no GitHub.
    Um erro de YAML ali não aparece em nenhum comando local.
    """

    def test_every_workflow_file_parses(self):
        arquivos = sorted(WORKFLOWS.glob("*.yml"))

        assert len(arquivos) >= 2, f"esperava mais de um workflow, achei {arquivos}"
        for arquivo in arquivos:
            conteudo = yaml.safe_load(arquivo.read_text(encoding="utf-8"))
            assert isinstance(conteudo, dict), f"{arquivo.name} não é um mapeamento"
            assert conteudo.get("jobs"), f"{arquivo.name} não declara job"

    def test_the_audit_never_gates_a_pull_request(self):
        """
        Auditoria é aviso, não portão: uma CVE numa dependência transitiva não
        pode travar um pull request que não tem nada a ver com ela. Por isso o
        gatilho é agendado e manual — e precisa continuar assim.
        """
        audit = yaml.safe_load((WORKFLOWS / "audit.yml").read_text(encoding="utf-8"))
        gatilhos = audit.get("on") or audit[True]

        assert "schedule" in gatilhos, "a auditoria não roda sozinha"
        assert "workflow_dispatch" in gatilhos, "a auditoria não pode ser disparada à mão"
        assert "push" not in gatilhos and "pull_request" not in gatilhos, (
            "a auditoria passaria a bloquear pull request"
        )

    def test_dependabot_watches_the_code_and_the_actions(self):
        """
        As actions entram junto com o pip porque foi nelas que a primeira
        defasagem apareceu: Node 20 depreciado sob checkout@v4.
        """
        config = yaml.safe_load(DEPENDABOT.read_text(encoding="utf-8"))
        vigiados = {(u["package-ecosystem"], u["directory"]) for u in config["updates"]}

        assert ("pip", "/") in vigiados
        assert ("pip", "/ai-inference-service") in vigiados
        assert ("github-actions", "/") in vigiados

    def test_dependabot_groups_its_pull_requests(self):
        """Pull request demais vira pull request ignorado."""
        config = yaml.safe_load(DEPENDABOT.read_text(encoding="utf-8"))
        sem_grupo = [u["directory"] for u in config["updates"] if not u.get("groups")]

        assert sem_grupo == [], f"atualizações sem agrupamento: {sem_grupo}"


def test_the_readmes_point_at_this_workflow():
    """Badge apontando para workflow inexistente é pior que badge nenhum."""
    nome = WORKFLOW.name
    for readme in ("README.md", "README-BR.md"):
        texto = (ROOT / readme).read_text(encoding="utf-8")

        assert f"workflows/{nome}" in texto, f"{readme} não cita o workflow {nome}"
