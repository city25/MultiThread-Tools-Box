from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from typing import Callable, Optional

from common.types import Progress, TaskConfig


ProgressCallback = Callable[[Progress], None]
ErrorCallback = Callable[[str], None]


class BaseTool(ABC):
    """Abstract base tool with unified callback interface."""

    def __init__(self, config: TaskConfig) -> None:
        self.config = config
        self._progress_cb: Optional[ProgressCallback] = None
        self._error_cb: Optional[ErrorCallback] = None
        self._stopped = False
        self._paused = False
        self._lock = threading.Lock()

    @abstractmethod
    def start(self):
        """Start the tool (blocking). Must return a result-like object."""

    def stop(self) -> None:
        with self._lock:
            self._stopped = True

    def pause(self) -> None:
        with self._lock:
            self._paused = True

    def resume(self) -> None:
        with self._lock:
            self._paused = False

    def set_progress_callback(self, cb: ProgressCallback) -> "BaseTool":
        self._progress_cb = cb
        return self

    def set_error_callback(self, cb: ErrorCallback) -> "BaseTool":
        self._error_cb = cb
        return self

    def _notify_progress(self, progress: Progress) -> None:
        cb = self._progress_cb
        if cb:
            try:
                cb(progress)
            except Exception:
                # callbacks should not break tool execution
                pass

    def _notify_error(self, message: str) -> None:
        cb = self._error_cb
        if cb:
            try:
                cb(message)
            except Exception:
                pass

    def _is_stopped(self) -> bool:
        with self._lock:
            return self._stopped
