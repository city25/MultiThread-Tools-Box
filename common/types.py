from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class Status(Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    ERROR = "ERROR"


@dataclass
class TaskConfig:
    url: str = ""
    save_path: str = "."
    threads: int = 4
    name: Optional[str] = None
    timeout: int = 10
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Progress:
    percent: float = 0.0  # 0.0 - 100.0
    message: str = ""
    status: Status = Status.PENDING
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Result:
    success: bool
    data: Optional[Any] = None
    error_message: Optional[str] = None
