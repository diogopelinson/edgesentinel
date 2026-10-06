"""
The CI workflow is configuration nobody runs locally: a mistake in it only
shows up after the push, and some mistakes never show up at all — they pass
green while verifying less than they should.

That is what this file demands: that the file be valid YAML, that the matrix
cover what pyproject.toml promises to support, and that the checkout bring the
full history, without which the check on the roadmap's delivery commits skips
itself and the job passes without checking anything.
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
    # 'on' becomes True in YAML 1.1, which is what PyYAML implements
    gatilhos = workflow.get("on") or workflow[True]

    assert "push" in gatilhos
    assert "pull_request" in gatilhos


def test_the_matrix_covers_the_minimum_supported_python(workflow):
    """
    requires-python is the promise; the matrix is the check on it. The minimum
    version is the one that breaks most, because it is where new syntax fails.
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
    """Derived from the file: a new job enters the check just by existing."""
    return sorted(carrega()["jobs"])


def comandos(workflow: dict, job: str) -> str:
    return "\n".join(str(passo.get("run", "")) for passo in workflow["jobs"][job]["steps"])


@pytest.mark.parametrize("job", jobs_do_workflow())
def test_every_job_checks_out_the_full_history(workflow, job):
    """
    Without fetch-depth 0 the clone is shallow, and tests/test_roadmap.py skips
    itself for not finding the old commits: the job would stay green while
    verifying less.
    """
    checkout = next(
        passo for passo in workflow["jobs"][job]["steps"]
        if str(passo.get("uses", "")).startswith("actions/checkout")
    )

    assert checkout.get("with", {}).get("fetch-depth") == 0


@pytest.mark.parametrize("job", jobs_do_workflow())
def test_every_job_that_runs_the_suite_installs_what_it_needs(workflow, job):
    """
    Without sklearn, skl2onnx, onnx and cv2, eighteen model and payload tests
    skip themselves — and a green job with 18 fewer tests warns nobody.
    """
    instalacao = comandos(workflow, job)
    if "pytest tests/" not in instalacao:
        pytest.skip(f"job '{job}' não roda a suíte")

    faltando = [
        pacote for pacote in ("scikit-learn", "skl2onnx", "onnx", "opencv-python-headless")
        if pacote not in instalacao
    ]

    assert faltando == [], f"job '{job}' não instala: {faltando}"


def test_some_job_runs_on_the_target_architecture(workflow):
    """
    The project's declared target is the Raspberry Pi. Testing only on x86_64
    leaves out exactly the difference that matters: a wheel that does not exist
    for arm64, a native library compiled another way.
    """
    arquiteturas = [str(job.get("runs-on", "")) for job in workflow["jobs"].values()]

    assert any("arm" in alvo for alvo in arquiteturas), (
        f"nenhum job roda em arm64: {arquiteturas}"
    )


def test_some_job_runs_ruff_and_mypy(workflow):
    """
    The style and type gate only counts if it runs by itself. Run by hand, it is
    a recommendation — and a lint recommendation is a lint turned off.
    """
    tudo = "\n".join(comandos(workflow, job) for job in workflow["jobs"])

    assert "ruff check" in tudo, "nenhum job roda o ruff"
    assert "mypy" in tudo, "nenhum job roda o mypy"


def test_some_job_boots_the_agent_as_a_process(workflow):
    """
    The suite covers functions; the smoke test covers the process. Without it,
    the class of defect that passes green and only shows up when you run the
    command has nothing to catch it — that is what happened with the
    'python -m' that executed nothing.
    """
    tudo = "\n".join(comandos(workflow, job) for job in workflow["jobs"])
    script = ROOT / "scripts" / "smoke.py"

    assert "scripts/smoke.py" in tudo, "nenhum job roda a verificação de fumaça"
    assert script.exists(), "o workflow chama um script que não existe"


class TestOutrosWorkflows:
    """
    Every file in .github/workflows is configuration that only runs on GitHub.
    A YAML mistake there shows up in no local command.
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
        An audit is a warning, not a gate: a CVE in a transitive dependency must
        not block a pull request that has nothing to do with it. That is why the
        trigger is scheduled and manual — and it has to stay that way.
        """
        audit = yaml.safe_load((WORKFLOWS / "audit.yml").read_text(encoding="utf-8"))
        gatilhos = audit.get("on") or audit[True]

        assert "schedule" in gatilhos, "a auditoria não roda sozinha"
        assert "workflow_dispatch" in gatilhos, "a auditoria não pode ser disparada à mão"
        assert "push" not in gatilhos and "pull_request" not in gatilhos, (
            "a auditoria passaria a bloquear pull request"
        )

    def test_code_scanning_can_write_its_alerts(self):
        """
        Without the security-events permission CodeQL runs and cannot publish
        anything: green job, empty security tab. It is the quietest possible
        failure in an analysis workflow.
        """
        codeql = yaml.safe_load((WORKFLOWS / "codeql.yml").read_text(encoding="utf-8"))
        job = codeql["jobs"]["codeql"]

        assert job.get("permissions", {}).get("security-events") == "write"

    def test_code_scanning_runs_on_pull_request_and_on_a_schedule(self):
        """
        On the pull request to catch the new code; on a schedule because the
        CodeQL rules change without the code changing.
        """
        codeql = yaml.safe_load((WORKFLOWS / "codeql.yml").read_text(encoding="utf-8"))
        gatilhos = codeql.get("on") or codeql[True]

        assert "pull_request" in gatilhos
        assert "schedule" in gatilhos

    def test_dependabot_watches_the_code_and_the_actions(self):
        """
        The actions go in alongside pip because they are where the first drift
        showed up: Node 20 deprecated under checkout@v4.
        """
        config = yaml.safe_load(DEPENDABOT.read_text(encoding="utf-8"))
        vigiados = {(u["package-ecosystem"], u["directory"]) for u in config["updates"]}

        assert ("pip", "/") in vigiados
        assert ("pip", "/ai-inference-service") in vigiados
        assert ("github-actions", "/") in vigiados

    def test_dependabot_groups_its_pull_requests(self):
        """Too many pull requests become ignored pull requests."""
        config = yaml.safe_load(DEPENDABOT.read_text(encoding="utf-8"))
        sem_grupo = [u["directory"] for u in config["updates"] if not u.get("groups")]

        assert sem_grupo == [], f"atualizações sem agrupamento: {sem_grupo}"


class TestPisoDeCobertura:
    """
    The floor exists so the numbers written in the README do not rot in
    silence. That only works if it is measured by someone who can fail the
    build, and if it is declared in a single place.
    """

    def piso(self) -> float:
        import tomli

        config = tomli.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        return float(config["tool"]["coverage"]["report"]["fail_under"])

    def test_a_job_measures_the_core_coverage(self, workflow):
        tudo = "\n".join(comandos(workflow, job) for job in workflow["jobs"])

        assert "--cov=core" in tudo and "--cov=application" in tudo, (
            "nenhum job mede a cobertura do núcleo"
        )

    def test_the_floor_is_below_what_the_core_has_today(self):
        """
        A floor equal to the current coverage turns any legitimate refactor into
        an argument over half a point.
        """
        assert 50 <= self.piso() <= 97, f"piso implausível: {self.piso()}"

    @pytest.mark.parametrize("readme", ["README.md", "README-BR.md"])
    def test_the_readmes_cite_the_declared_floor(self, readme):
        texto = (ROOT / readme).read_text(encoding="utf-8")
        piso = f"{self.piso():g}%"

        assert piso in texto, f"{readme} não cita o piso declarado ({piso})"


def test_the_readmes_point_at_this_workflow():
    """A badge pointing at a workflow that does not exist is worse than no badge."""
    nome = WORKFLOW.name
    for readme in ("README.md", "README-BR.md"):
        texto = (ROOT / readme).read_text(encoding="utf-8")

        assert f"workflows/{nome}" in texto, f"{readme} não cita o workflow {nome}"
