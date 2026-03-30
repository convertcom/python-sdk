from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any
from urllib import error, request as urllib_request


@dataclass(frozen=True)
class HttpResponse:
    status: int
    data: Any
    headers: dict[str, str]


class HttpError(Exception):
    def __init__(self, status: int, data: Any, headers: dict[str, str]) -> None:
        super().__init__(f"HTTP request failed with status {status}")
        self.status = status
        self.data = data
        self.headers = headers


def _build_url(base_url: str, route: str) -> str:
    return f"{base_url.rstrip('/')}/{route.lstrip('/')}"


def _parse_body(raw_body: bytes, headers: dict[str, str]) -> Any:
    if not raw_body:
        return {}
    content_type = headers.get("Content-Type", headers.get("content-type", ""))
    text = raw_body.decode("utf-8")
    if "json" in content_type.lower():
        return json.loads(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def request(
    *,
    method: str,
    base_url: str,
    route: str,
    headers: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    timeout: float = 10.0,
    retries: int = 0,
    retry_backoff: float = 0.0,
) -> HttpResponse:
    attempts = max(0, retries) + 1
    last_error: Exception | None = None
    for attempt in range(attempts):
        body = None
        if method.upper() != "GET":
            body = json.dumps(data or {}).encode("utf-8")
        req = urllib_request.Request(
            _build_url(base_url, route),
            method=method.upper(),
            headers=dict(headers or {}),
            data=body,
        )
        try:
            with urllib_request.urlopen(req, timeout=timeout) as response:
                raw_body = response.read()
                parsed_headers = dict(response.headers.items())
                return HttpResponse(
                    status=response.status,
                    data=_parse_body(raw_body, parsed_headers),
                    headers=parsed_headers,
                )
        except error.HTTPError as exc:
            raw_body = exc.read()
            parsed_headers = dict(exc.headers.items())
            last_error = HttpError(
                status=exc.code,
                data=_parse_body(raw_body, parsed_headers),
                headers=parsed_headers,
            )
            if exc.code < 500 or attempt == attempts - 1:
                raise last_error from exc
        except error.URLError as exc:
            last_error = exc
            if attempt == attempts - 1:
                raise
        if retry_backoff > 0 and attempt < attempts - 1:
            time.sleep(retry_backoff)
    if last_error:
        raise last_error
    raise RuntimeError("HTTP request failed without an error")
