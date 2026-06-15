"""Abstract base class every processing module must implement."""

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional

from .config_manager import ConfigManager
from .logger import get_logger

logger = get_logger(__name__)


@dataclass
class ModuleResult:
    """Standardised return type for every module."""
    success: bool
    module: str
    data: Any = None
    error: Optional[str] = None
    warnings: List[str] = field(default_factory=list)
    processing_time: float = 0.0

    def raise_if_failed(self) -> None:
        if not self.success:
            raise RuntimeError(f"Module '{self.module}' failed: {self.error}")


class BaseModule(ABC):
    """
    Every module must inherit from BaseModule and implement `run()`.
    `run()` wraps `process()` with timing and error handling so that
    modules themselves only need to focus on their core logic.
    """

    MODULE_NAME: str = "base"

    def __init__(self, config: ConfigManager) -> None:
        self.config = config
        self.log = get_logger(self.MODULE_NAME)

    # ── Public contract ────────────────────────────────────────

    def run(self, video_path: Path, context: Optional[dict] = None, **kwargs) -> ModuleResult:
        """Entry point called by the pipeline. Do not override this."""
        if not self.is_enabled():
            self.log.info(f"[{self.MODULE_NAME}] skipped (disabled in config)")
            return ModuleResult(success=True, module=self.MODULE_NAME, data=None)

        self.log.info(f"[{self.MODULE_NAME}] starting → {video_path.name}")
        t0 = time.perf_counter()
        try:
            result = self.process(video_path, context=context or {}, **kwargs)
            result.processing_time = time.perf_counter() - t0
            if result.success:
                self.log.info(f"[{self.MODULE_NAME}] done in {result.processing_time:.1f}s")
            else:
                self.log.error(f"[{self.MODULE_NAME}] failed: {result.error}")
            return result
        except Exception as exc:
            elapsed = time.perf_counter() - t0
            self.log.exception(f"[{self.MODULE_NAME}] unhandled exception after {elapsed:.1f}s")
            return ModuleResult(
                success=False,
                module=self.MODULE_NAME,
                error=str(exc),
                processing_time=elapsed,
            )

    @abstractmethod
    def process(self, video_path: Path, context: dict, **kwargs) -> ModuleResult:
        """Core processing logic. Implement in subclass."""

    # ── Helpers ────────────────────────────────────────────────

    def is_enabled(self) -> bool:
        enabled = self.config.get("pipeline.enabled_modules", [])
        return self.MODULE_NAME in enabled

    def cfg(self, key: str, default: Any = None) -> Any:
        """Shorthand for module-scoped config lookup."""
        return self.config.get(f"{self.MODULE_NAME}.{key}", default)

    @staticmethod
    def fmt_time(seconds: float) -> str:
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h:02d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"
