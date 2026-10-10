"""Error types and the JSON error envelope required by the contract.

The contract requires ``{"error": ..., "run_id": ...}`` for a missing or empty
run. FastAPI's default handler wraps a message in ``{"detail": ...}``, so the
run endpoints raise :class:`RunNotFoundError` and a dedicated handler renders the
contract body. Validation errors (HTTP 422) keep FastAPI's default shape.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class RunNotFoundError(Exception):
    """Raised when a run id is unknown, or its manifest is unreadable.

    A corrupt manifest is treated as "this run does not exist" rather than as a
    server fault: the id cannot be resolved, so there is nothing to serve, and a
    404 keeps a half-written run from being mistaken for a result of zero.
    """

    def __init__(
        self,
        run_id: str,
        message: str | None = None,
        *,
        category: str = "not_found",
        state: str | None = None,
        reason: str | None = None,
        artefact: str | None = None,
    ) -> None:
        self.run_id = run_id
        self.message = message or f"run not found: {run_id}"
        self.category = category
        self.state = state
        self.reason = reason or self.message
        self.artefact = artefact
        super().__init__(self.message)


class BadRequestError(Exception):
    """Raised for a malformed query the service can describe precisely."""

    def __init__(self, message: str, run_id: str | None = None) -> None:
        self.message = message
        self.run_id = run_id
        super().__init__(message)


def install_error_handlers(app: FastAPI) -> None:
    """Attach the contract error envelope to ``app``."""

    @app.exception_handler(RunNotFoundError)
    async def _run_not_found(
        request: Request, exc: RunNotFoundError
    ) -> JSONResponse:
        body: dict[str, Any] = {"error": exc.message, "run_id": exc.run_id}
        return JSONResponse(status_code=404, content=body)

    @app.exception_handler(BadRequestError)
    async def _bad_request(request: Request, exc: BadRequestError) -> JSONResponse:
        body: dict[str, Any] = {"error": exc.message, "run_id": exc.run_id}
        return JSONResponse(status_code=400, content=body)
