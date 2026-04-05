from __future__ import annotations
import logging
from pathlib import Path
import yaml

from core.base import BaseModel

logger = logging.getLogger("ai_service.registry")


class ModelRegistry:
    """
    Carrega e gerencia modelos definidos em models.yaml.
    Qualquer modelo novo é só um bloco no YAML — sem mudar código.
    """

    def __init__(self) -> None:
        self._models: dict[str, BaseModel] = {}

    def load_from_config(self, config_path: str | Path) -> None:
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"models.yaml não encontrado: {path}")

        with path.open("r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        for model_cfg in config.get("models", []):
            self._load_model(model_cfg)

        logger.info(f"Registry carregado: {len(self._models)} modelo(s).")

    def get(self, model_id: str) -> BaseModel:
        model = self._models.get(model_id)
        if model is None:
            available = ", ".join(self._models.keys())
            raise ValueError(
                f"Modelo '{model_id}' não encontrado. "
                f"Disponíveis: {available}"
            )
        return model

    def list_models(self) -> list[dict]:
        return [
            {
                "id":     model_id,
                "type":   type(model).__name__.lower().replace("model", ""),
                "status": "loaded" if model.is_loaded else "error",
            }
            for model_id, model in self._models.items()
        ]

    def _load_model(self, config: dict) -> None:
        model_id   = config["id"]
        model_type = config["type"]

        try:
            model = self._build_model(model_type, model_id, config)
            model.load(config)
            self._models[model_id] = model
            logger.info(f"Modelo '{model_id}' ({model_type}) carregado.")
        except Exception as e:
            logger.error(f"Falha ao carregar modelo '{model_id}': {e}")

    def _build_model(self, model_type: str, model_id: str, config: dict) -> BaseModel:
        threshold = float(config.get("confidence_threshold", 0.5))

        if model_type == "yolo":
            from models.yolo import YOLOModel
            return YOLOModel(model_id=model_id, confidence_threshold=threshold)

        if model_type == "onnx":
            from models.onnx import ONNXModel
            return ONNXModel(model_id=model_id, confidence_threshold=threshold)

        raise ValueError(
            f"Tipo de modelo desconhecido: '{model_type}'. "
            f"Suportados: yolo, onnx"
        )