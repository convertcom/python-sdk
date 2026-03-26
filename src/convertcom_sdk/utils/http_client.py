from __future__ import annotations

import json
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
) -> HttpResponse:
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
        raise HttpError(
            status=exc.code,
            data=_parse_body(raw_body, parsed_headers),
            headers=parsed_headers,
        ) from exc
