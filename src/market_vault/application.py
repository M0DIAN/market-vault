"""UI-neutral application dependency construction and shutdown ownership."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from pathlib import Path
import sys
from threading import Lock
from typing import Any, Callable


LOGGER_NAME = "market_vault"


def resolve_application_settings_path(
    explicit: str | None = None,
    *,
    frozen: bool = False,
    executable: str | None = None,
    source_default: str | Path = "config/settings.yaml",
) -> Path:
    """Resolve external settings without importing either desktop toolkit."""

    if frozen:
        application_root = Path(executable or sys.executable).resolve().parent
        if explicit:
            candidate = Path(explicit).expanduser()
            return (
                candidate.resolve()
                if candidate.is_absolute()
                else (application_root / candidate).resolve()
            )
        return (application_root / "config" / "settings.yaml").resolve()
    if explicit:
        return Path(explicit).expanduser().resolve()
    return Path(source_default).expanduser().resolve()


def configure_application_logging() -> logging.Logger:
    """Initialize the application logger without creating runtime files."""

    logger = logging.getLogger(LOGGER_NAME)
    if not logger.handlers:
        logger.addHandler(logging.NullHandler())
    logger.setLevel(logging.INFO)
    return logger


def _production_backend(settings: Any) -> Any:
    from market_vault.api import MarketVault
    from market_vault.console.backend import ConsoleBackend

    return ConsoleBackend(MarketVault(settings))


def _production_task_runner() -> Any:
    from market_vault.console.tasks import SerialTaskRunner

    return SerialTaskRunner()


@dataclass
class ApplicationContext:
    """One process-wide lazy backend/runner pair shared by a desktop UI."""

    settings_path: Path
    settings: Any
    logger: logging.Logger
    backend_factory: Callable[[Any], Any] = field(repr=False)
    runner_factory: Callable[[], Any] = field(repr=False)
    _backend: Any | None = field(default=None, init=False, repr=False)
    _task_runner: Any | None = field(default=None, init=False, repr=False)
    _closed: bool = field(default=False, init=False, repr=False)
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    @property
    def backend_if_initialized(self) -> Any | None:
        with self._lock:
            return self._backend

    @property
    def task_runner_if_initialized(self) -> Any | None:
        with self._lock:
            return self._task_runner

    def get_backend(self) -> Any:
        """Create the process backend on first explicit business access."""

        with self._lock:
            if self._closed:
                raise RuntimeError("Application context is closed.")
            if self._backend is None:
                self._backend = self.backend_factory(self.settings)
            return self._backend

    def get_task_runner(self) -> Any:
        """Create the process task runner on first explicit business access."""

        with self._lock:
            if self._closed:
                raise RuntimeError("Application context is closed.")
            if self._task_runner is None:
                self._task_runner = self.runner_factory()
            return self._task_runner

    def shutdown(self) -> None:
        """Release process-owned resources exactly once."""

        with self._lock:
            if self._closed:
                return
            self._closed = True
            task_runner = self._task_runner
        if task_runner is not None:
            task_runner.close()


def build_application_context(
    settings_path: str | Path,
    *,
    settings_loader: Callable[[Path], Any] | None = None,
    backend_factory: Callable[[Any], Any] | None = None,
    runner_factory: Callable[[], Any] | None = None,
    logging_factory: Callable[[], logging.Logger] | None = None,
) -> ApplicationContext:
    """Build the shared application context without connecting to OpenD."""

    from market_vault.config import load_settings

    resolved_settings = Path(settings_path).expanduser().resolve()
    loader = settings_loader or load_settings
    settings = loader(resolved_settings)
    logger = (logging_factory or configure_application_logging)()
    return ApplicationContext(
        settings_path=resolved_settings,
        settings=settings,
        logger=logger,
        backend_factory=backend_factory or _production_backend,
        runner_factory=runner_factory or _production_task_runner,
    )
