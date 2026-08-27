"""UI-neutral application dependency construction and shutdown ownership."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from pathlib import Path
from typing import Any, Callable


LOGGER_NAME = "market_vault"


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
    """One process-wide backend/runner pair shared by a desktop UI."""

    settings_path: Path
    settings: Any
    backend: Any
    task_runner: Any
    logger: logging.Logger
    _closed: bool = field(default=False, init=False, repr=False)

    @property
    def closed(self) -> bool:
        return self._closed

    def shutdown(self) -> None:
        """Release process-owned resources exactly once."""

        if self._closed:
            return
        self.task_runner.close()
        self._closed = True


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
    backend = (backend_factory or _production_backend)(settings)
    logger = (logging_factory or configure_application_logging)()
    runner = (runner_factory or _production_task_runner)()
    return ApplicationContext(
        settings_path=resolved_settings,
        settings=settings,
        backend=backend,
        task_runner=runner,
        logger=logger,
    )
