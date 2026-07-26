from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .config import STAGE_ORDER, StrictMemoryEngineConfig
from .errors import StrictConfigurationError, StrictStageUnavailableError


@dataclass(frozen=True)
class RegisteredModule:
    stage: str
    module_id: str
    implementation: Any


class StrictModuleRegistry:
    """Exact module registry. It never aliases or falls back to baseline code."""

    def __init__(self) -> None:
        self._modules: dict[tuple[str, str], RegisteredModule] = {}

    def register(self, stage: str, module_id: str, implementation: Any) -> None:
        if stage not in STAGE_ORDER:
            raise StrictConfigurationError(f"unknown strict stage: {stage}")
        key = (stage, module_id)
        if key in self._modules:
            raise StrictConfigurationError(
                f"duplicate strict module registration: {stage}={module_id}"
            )
        self._modules[key] = RegisteredModule(stage, module_id, implementation)

    def resolve(self, stage: str, module_id: str) -> Any:
        registered = self._modules.get((stage, module_id))
        if registered is None:
            raise StrictStageUnavailableError(
                f"strict stage {stage!r} requires unregistered module {module_id!r}"
            )
        return registered.implementation

    def validate(
        self,
        config: StrictMemoryEngineConfig,
        stages: Iterable[str],
    ) -> None:
        for stage in stages:
            self.resolve(stage, config.modules[stage])

    def validate_full(self, config: StrictMemoryEngineConfig) -> None:
        self.validate(config, STAGE_ORDER)

    def manifest(self) -> dict[str, str]:
        return {
            stage: module_id
            for stage, module_id in sorted(self._modules)
        }
