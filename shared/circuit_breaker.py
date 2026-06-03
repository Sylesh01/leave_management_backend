import os

import pybreaker
import requests
from requests import RequestException
from tenacity import (
    Retrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)
import logging

logger = logging.getLogger(__name__)


class CircuitOpenError(pybreaker.CircuitBreakerError):
    pass


class TransientHTTPError(RequestException):
    pass


_BREAKERS: dict[str, pybreaker.CircuitBreaker] = {}


def _retry_max_attempts() -> int:
    return int(os.environ.get("HTTP_RETRY_MAX_ATTEMPTS", "3"))


def _retry_base_wait_seconds() -> float:
    return int(os.environ.get("HTTP_RETRY_BASE_WAIT_MS", "500")) / 1000.0


def _retry_multiplier() -> int:
    return int(os.environ.get("HTTP_RETRY_MULTIPLIER", "2"))


def get_circuit_breaker(
    service_name: str,
    fail_max: int = 3,
    reset_timeout: int = 10,
) -> pybreaker.CircuitBreaker:
    if service_name not in _BREAKERS:
        _BREAKERS[service_name] = pybreaker.CircuitBreaker(
            fail_max=fail_max,
            reset_timeout=reset_timeout,
        )
    return _BREAKERS[service_name]


def _is_retryable_exception(exc: BaseException) -> bool:
    if isinstance(exc, TransientHTTPError):
        return True
    if isinstance(exc, requests.RequestException):
        return True
    return False


def _single_http_attempt(
    service_name: str,
    method: str,
    url: str,
    **kwargs,
) -> requests.Response:
    response = requests.request(method, url, **kwargs)
    if response.status_code in (502, 503, 504):
        raise TransientHTTPError(
            f"{service_name} returned {response.status_code}"
        )
    if response.status_code >= 500:
        raise RequestException(
            f"{service_name} returned {response.status_code}"
        )
    return response


def _execute_with_retry(
    service_name: str,
    method: str,
    url: str,
    **kwargs,
) -> requests.Response:
    max_attempts = _retry_max_attempts()
    retrying = Retrying(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(
            multiplier=_retry_base_wait_seconds(),
            exp_base=_retry_multiplier(),
        ),
        retry=retry_if_exception(_is_retryable_exception),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )

    def attempt() -> requests.Response:
        return _single_http_attempt(service_name, method, url, **kwargs)

    return retrying(attempt)


def resilient_request(
    service_name: str,
    method: str,
    url: str,
    **kwargs,
) -> requests.Response:
    breaker = get_circuit_breaker(service_name)

    def request_fn() -> requests.Response:
        return _execute_with_retry(service_name, method, url, **kwargs)

    try:
        return breaker.call(request_fn)
    except pybreaker.CircuitBreakerError as exc:
        raise CircuitOpenError(str(exc)) from exc
