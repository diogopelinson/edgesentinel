import sys
import socket
import importlib
import logging
from pathlib import Path

logger = logging.getLogger("edgesentinel.doctor")

GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
RESET  = "\033[0m"
BOLD   = "\033[1m"


def ok(msg: str)   -> str: return f"{GREEN}OK{RESET}      {msg}"
def warn(msg: str) -> str: return f"{YELLOW}AVISO{RESET}   {msg}"
def fail(msg: str) -> str: return f"{RED}FALHOU{RESET}  {msg}"


def run_doctor(config_path: str) -> None:
    print(f"\n{BOLD}edgesentinel doctor{RESET}")
    print("=" * 52)

    results = [
        _check_python(),
        _check_dependencies(),
        _check_config(config_path),
        _check_sensors(),
        _check_inference_backends(),
        _check_camera_backends(),
        _check_yolo(config_path),
        _check_exporter_port(config_path),
    ]

    errors   = sum(r[0] for r in results)
    warnings = sum(r[1] for r in results)

    print("=" * 52)
    if errors == 0 and warnings == 0:
        print(f"\n{GREEN}Tudo certo — sistema pronto para rodar.{RESET}\n")
    elif errors == 0:
        print(f"\n{YELLOW}{warnings} aviso(s) — sistema funcional, alguns recursos indisponíveis.{RESET}\n")
    else:
        print(f"\n{RED}{errors} erro(s) crítico(s) encontrado(s).{RESET}\n")


def _check_python() -> tuple[int, int]:
    print(f"\n{BOLD}Python{RESET}")
    version = sys.version_info
    label = f"{version.major}.{version.minor}.{version.micro}"
    if version >= (3, 10):
        print(f"  {ok('Python ' + label)}")
        return (0, 0)
    print(f"  {fail('Python ' + label + ' — requer 3.10+')}")
    return (1, 0)


def _check_dependencies() -> tuple[int, int]:
    print(f"\n{BOLD}Dependências{RESET}")
    errors = warnings = 0
    deps = [
        ("yaml",              "pyyaml",           True),
        ("prometheus_client", "prometheus-client", True),
        ("numpy",             "numpy",             False),
        ("onnxruntime",       "onnxruntime",       False),
        ("tflite_runtime",    "tflite-runtime",    False),
        ("gpiozero",          "gpiozero",          False),
    ]
    for import_name, pip_name, required in deps:
        try:
            mod = importlib.import_module(import_name)
            version = getattr(mod, "__version__", "?")
            print(f"  {ok(pip_name + ' ' + version)}")
        except ImportError:
            if required:
                print(f"  {fail(pip_name + ' — não instalado (obrigatório)')}")
                print(f"         instale com: pip install {pip_name}")
                errors += 1
            else:
                print(f"  {warn(pip_name + ' — não instalado (opcional)')}")
                warnings += 1
    return (errors, warnings)


def _check_config(config_path: str) -> tuple[int, int]:
    print(f"\n{BOLD}Configuração{RESET}")
    path = Path(config_path).resolve()
    if not path.exists():
        print(f"  {fail('config.yaml não encontrado em: ' + str(path))}")
        return (1, 0)
    print(f"  {ok('config.yaml encontrado em ' + str(path))}")
    try:
        from config.loader import load
        config = load(path)
        print(f"  {ok(str(len(config.sensors)) + ' sensor(es) configurado(s)')}")
        print(f"  {ok(str(len(config.rules)) + ' regra(s) configurada(s)')}")
        print(f"  {ok(str(len(config.actions)) + ' ação(ões) configurada(s)')}")
        print(f"  {ok('backend de inferência: ' + config.inference.backend)}")
        return (0, 0)
    except Exception as e:
        print(f"  {fail('erro ao carregar config: ' + str(e))}")
        return (1, 0)


def _check_sensors() -> tuple[int, int]:
    print(f"\n{BOLD}Sensores{RESET}")
    warnings = 0
    sensors_to_check = [
        ("cpu_temperature", "adapters.sensors.cpu_temp",     "CpuTemperatureSensor"),
        ("cpu_usage",       "adapters.sensors.cpu_usage",    "CpuUsageSensor"),
        ("memory_usage",    "adapters.sensors.memory_usage", "MemoryUsageSensor"),
    ]
    for sensor_type, module_path, class_name in sensors_to_check:
        try:
            module = importlib.import_module(module_path)
            cls    = getattr(module, class_name)
            sensor = cls(sensor_id=sensor_type)
            if sensor.is_available():
                reading = sensor.read()
                print(f"  {ok(sensor_type.ljust(20) + ' ' + str(reading.value) + ' ' + reading.unit)}")
            else:
                print(f"  {warn(sensor_type.ljust(20) + ' indisponível nesse hardware')}")
                warnings += 1
        except Exception as e:
            print(f"  {warn(sensor_type.ljust(20) + ' indisponível (' + e.__class__.__name__ + ')')}")
            warnings += 1
    return (0, warnings)


def _check_inference_backends() -> tuple[int, int]:
    print(f"\n{BOLD}Backends de inferência{RESET}")
    errors = warnings = 0
    backends = [
        ("dummy",  None,             "adapters.inference.dummy",  "DummyInferenceAdapter"),
        ("onnx",   "onnxruntime",    "adapters.inference.onnx",   "ONNXInferenceAdapter"),
        ("tflite", "tflite_runtime", "adapters.inference.tflite", "TFLiteInferenceAdapter"),
    ]
    for name, dep, module_path, class_name in backends:
        if dep is not None:
            try:
                importlib.import_module(dep)
            except ImportError:
                print(f"  {warn(name.ljust(10) + ' não disponível — instale: pip install edgesentinel[' + name + ']')}")
                warnings += 1
                continue
        try:
            module = importlib.import_module(module_path)
            cls    = getattr(module, class_name)
            cls()
            print(f"  {ok(name.ljust(10) + ' disponível')}")
        except Exception as e:
            print(f"  {fail(name.ljust(10) + ' erro: ' + str(e))}")
            errors += 1
    return (errors, warnings)


def _check_camera_backends() -> tuple[int, int]:
    print(f"\n{BOLD}Câmera{RESET}")
    warnings = 0
    for lib, pip_name in [("cv2", "opencv-python"), ("ultralytics", "ultralytics")]:
        try:
            mod     = importlib.import_module(lib)
            version = getattr(mod, "__version__", "?")
            print(f"  {ok(pip_name + ' ' + version)}")
        except ImportError:
            print(f"  {warn(pip_name + ' — não instalado (necessário para câmera)')}")
            print(f"         instale com: pip install edgesentinel[camera]")
            warnings += 1
    return (0, warnings)


def _check_yolo(config_path: str) -> tuple[int, int]:
    print(f"\n{BOLD}YOLO{RESET}")

    try:
        from config.loader import load
        config = load(Path(config_path))
    except Exception:
        print(f"  {warn('config.yaml inválido — pulando verificação YOLO')}")
        return (0, 1)

    if not config.yolo.enabled:
        print(f"  {warn('YOLO desabilitado no config')}")
        return (0, 0)

    model_path = Path(config.yolo.model_path)
    if not model_path.exists():
        print(f"  {warn('modelo não encontrado: ' + str(model_path))}")
        print(f"         o modelo será baixado automaticamente na primeira execução")
        return (0, 1)

    print(f"  {ok('modelo encontrado: ' + str(model_path))}")

    classes = config.yolo.target_classes
    if classes:
        print(f"  {ok('classes alvo: ' + ', '.join(classes))}")
    else:
        print(f"  {warn('target_classes vazio — detectará todas as classes')}")

    if not config.cameras:
        print(f"  {warn('nenhuma câmera configurada em config.yaml')}")
        return (0, 1)

    print(f"  {ok(str(len(config.cameras)) + ' câmera(s) configurada(s)')}")
    for cam in config.cameras:
        mode = "simulada (" + cam.simulated_mode + ")" if cam.simulated else "RTSP: " + cam.source
        print(f"  {ok(cam.sensor_id + ' — ' + mode)}")

    return (0, 0)


def _check_exporter_port(config_path: str) -> tuple[int, int]:
    print(f"\n{BOLD}Exporter{RESET}")
    port = 8000
    try:
        from config.loader import load
        config = load(Path(config_path))
        port   = config.exporter.port
    except Exception:
        pass
    sock   = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1)
    result = sock.connect_ex(("localhost", port))
    sock.close()
    if result == 0:
        print(f"  {warn('porta ' + str(port) + ' em uso — exporter já rodando ou outra aplicação')}")
        return (0, 1)
    print(f"  {ok('porta ' + str(port) + ' livre — exporter pode subir normalmente')}")
    return (0, 0)