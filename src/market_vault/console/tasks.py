from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Callable


@dataclass(frozen=True)
class TaskState:
    name: str = ""
    status: str = "IDLE"
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str = ""


class SerialTaskRunner:
    """Run at most one Console operation at a time off the Tk event loop."""

    def __init__(self):
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="market-vault-console")
        self._lock = Lock()
        self._state = TaskState()

    @property
    def state(self) -> TaskState:
        with self._lock:
            return self._state

    def submit(self, name: str, operation: Callable[[], Any]) -> Future[Any]:
        with self._lock:
            if self._state.status == "RUNNING":
                raise RuntimeError(f"Operation already running: {self._state.name}")
            self._state = TaskState(name=name, status="RUNNING", started_at=datetime.now(timezone.utc))
        future = self._executor.submit(operation)
        future.add_done_callback(self._finish)
        return future

    def _finish(self, future: Future[Any]) -> None:
        error = ""
        status = "SUCCESS"
        try:
            future.result()
        except Exception as exc:
            status = "FAILED"
            error = str(exc)
        with self._lock:
            self._state = TaskState(
                name=self._state.name,
                status=status,
                started_at=self._state.started_at,
                finished_at=datetime.now(timezone.utc),
                error=error,
            )

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
