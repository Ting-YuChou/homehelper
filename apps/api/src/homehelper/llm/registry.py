from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

DEFAULT_MODELS_PATH = Path(__file__).with_name("models.yaml")


class TaskConfig(BaseModel):
    model: str
    fallbacks: list[str] = Field(default_factory=list)
    timeout_s: float = 30
    max_tokens: int = 1024


class EmbeddingConfig(BaseModel):
    model: str
    dimensions: int


class ModelRegistry(BaseModel):
    tasks: dict[str, TaskConfig]
    embedding: EmbeddingConfig

    @classmethod
    def load(
        cls,
        path: Path = DEFAULT_MODELS_PATH,
        overrides: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> "ModelRegistry":
        """Load the mapping, applying per-task overrides (e.g. from a release manifest)."""
        data = yaml.safe_load(path.read_text())
        for task, override in (overrides or {}).items():
            if task not in data["tasks"]:
                raise ValueError(f"override for unknown task: {task}")
            data["tasks"][task] = {**data["tasks"][task], **override}
        return cls.model_validate(data)

    def for_task(self, task: str) -> TaskConfig:
        try:
            return self.tasks[task]
        except KeyError:
            raise ValueError(f"unknown LLM task: {task}") from None
