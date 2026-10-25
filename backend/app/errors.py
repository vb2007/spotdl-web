"""v46: user-facing API errors carry a stable machine `code` beside the English `detail`.

The frontend translates by `code` (never by matching `detail` text, which would break on any
wording change) and falls back to `detail` for a code it doesn't know. The backend stays
language-neutral: `detail` remains English, and `params` carries the values a translation
interpolates (a field name, a bound, a state), so no translation has to parse the sentence.

The response body is FastAPI's usual `{"detail": ...}` plus `code` (and `params` when there
are any), so every existing client that reads `detail` is unaffected.
"""

from typing import Any

from fastapi import HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ApiError(HTTPException):
    def __init__(
        self,
        status_code: int,
        code: str,
        detail: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=detail, headers=headers)
        self.code = code
        self.params = params or {}


async def api_error_handler(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, ApiError):  # registered for ApiError only; kept total anyway
        return await http_exception_handler(request, exc)  # type: ignore[arg-type]
    body: dict[str, Any] = {"detail": exc.detail, "code": exc.code}
    if exc.params:
        body["params"] = exc.params
    return JSONResponse(body, status_code=exc.status_code, headers=exc.headers)


def _safe(value: Any) -> Any:
    # Text the response can encode: a lone surrogate (a JSON `\ud800` escape) would otherwise
    # fail UTF-8 encoding and turn the 422 into a 500.
    if isinstance(value, str):
        return value.encode("utf-8", "backslashreplace").decode("utf-8")
    return value


async def validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """v53: a body FastAPI's own validation refuses answers 422 `request_invalid`, with each
    error's type, location and message only. FastAPI's default handler echoed the submitted
    `input` back, which (a) failed to encode a lone surrogate, so the 422 became a 500 whose
    traceback logged the whole body, a login's password included, and (b) has no `code`."""
    errors = exc.errors() if isinstance(exc, RequestValidationError) else []
    detail = [
        {
            "type": _safe(e.get("type")),
            "loc": [_safe(part) for part in e.get("loc", ())],
            "msg": _safe(e.get("msg")),
        }
        for e in errors
    ]
    return JSONResponse({"detail": detail, "code": "request_invalid"}, status_code=422)
