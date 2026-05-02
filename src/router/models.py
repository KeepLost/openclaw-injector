from dataclasses import dataclass
from typing import Any, Literal


@dataclass
class SendRequest:
    session_key: str
    message: str
    system_input_provenance: dict[str, Any] | None = None


@dataclass
class SendResponse:
    run_id: str
    status: Literal["queued"]


@dataclass
class ErrorResponse:
    error: str
    detail: str | None = None
