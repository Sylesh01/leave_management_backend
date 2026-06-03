import requests
from fastapi import FastAPI, HTTPException, Request
from shared.eureka_lookup import get_service_url as lookup_service_url
from shared.circuit_breaker import resilient_request, CircuitOpenError
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

SKIP_PATH_PREFIXES = ("/health", "/docs", "/redoc", "/openapi.json")


def _should_log(path: str) -> bool:
    return not any(path.startswith(prefix) for prefix in SKIP_PATH_PREFIXES)


async def get_notification_service_url(eureka_server: str) -> str | None:
    return await lookup_service_url(
        eureka_server,
        "NOTIFICATION-SERVICE",
        required=False,
    )


def _format_error_log(
    service: str,
    message: str,
    status_code: int | None = None,
    path: str | None = None,
    context: dict | None = None,
) -> str:
    parts = [f"ERROR [{service}]"]
    if status_code is not None:
        parts.append(str(status_code))
    if path:
        parts.append(path)
    parts.append(f": {message}")
    if context:
        parts.append(str(context))
    return " ".join(parts)


async def log_error(
    eureka_server: str,
    service: str,
    message: str,
    status_code: int | None = None,
    path: str | None = None,
    context: dict | None = None,
) -> None:
    fallback = _format_error_log(service, message, status_code, path, context)
    notification_service_url = await get_notification_service_url(eureka_server)
    if notification_service_url is None:
        print(fallback)
        return

    try:
        resilient_request(
            "NOTIFICATION-SERVICE",
            "post",
            f"{notification_service_url}/notify/error",
            json={
                "service": service,
                "message": message,
                "status_code": status_code,
                "path": path,
                "context": context,
            },
            timeout=5,
        )
    except CircuitOpenError:
        print(
            f"Notification service circuit open while logging error for {service}: {message}"
        )
    except Exception:
        print(fallback)


def register_error_logging(
    app: FastAPI,
    service_name: str,
    eureka_server: str,
) -> None:
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        if _should_log(request.url.path):
            detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
            await log_error(
                eureka_server,
                service_name,
                detail,
                exc.status_code,
                request.url.path,
            )
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request,
        exc: RequestValidationError,
    ):
        if _should_log(request.url.path):
            errors = "; ".join(
                f"{err.get('loc', [])}: {err.get('msg', '')}"
                for err in exc.errors()
            )
            await log_error(
                eureka_server,
                service_name,
                errors or "Validation error",
                422,
                request.url.path,
            )
        return JSONResponse(status_code=422, content={"detail": exc.errors()})

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        if _should_log(request.url.path):
            await log_error(
                eureka_server,
                service_name,
                str(exc),
                500,
                request.url.path,
            )
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )
