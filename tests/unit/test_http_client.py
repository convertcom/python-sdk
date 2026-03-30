from __future__ import annotations

from io import BytesIO
from urllib import error

import pytest

from convertcom_sdk.utils.http_client import HttpError, request


class FakeHeaders:
    def items(self):
        return [("Content-Type", "application/json")]


class FakeResponse:
    def __init__(self, status: int, payload: bytes) -> None:
        self.status = status
        self._payload = payload
        self.headers = FakeHeaders()

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_http_client_retries_server_errors(monkeypatch):
    attempts = {"count": 0}

    def fake_urlopen(req, timeout):  # noqa: ARG001
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise error.HTTPError(
                req.full_url,
                500,
                "server error",
                hdrs=FakeHeaders(),
                fp=BytesIO(b"{}"),
            )
        return FakeResponse(200, b'{"ok": true}')

    monkeypatch.setattr("convertcom_sdk.utils.http_client.urllib_request.urlopen", fake_urlopen)

    response = request(
        method="GET",
        base_url="https://example.com",
        route="/config",
        retries=1,
    )

    assert attempts["count"] == 2
    assert response.data == {"ok": True}


def test_http_client_does_not_retry_client_errors(monkeypatch):
    attempts = {"count": 0}

    def fake_urlopen(req, timeout):  # noqa: ARG001
        attempts["count"] += 1
        raise error.HTTPError(
            req.full_url,
            404,
            "not found",
            hdrs=FakeHeaders(),
            fp=BytesIO(b"{}"),
        )

    monkeypatch.setattr("convertcom_sdk.utils.http_client.urllib_request.urlopen", fake_urlopen)

    with pytest.raises(HttpError) as exc_info:
        request(
            method="GET",
            base_url="https://example.com",
            route="/missing",
            retries=3,
        )

    assert attempts["count"] == 1
    assert exc_info.value.status == 404
