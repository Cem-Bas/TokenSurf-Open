"""Tests for tokensurf.sdk.config — no live server required (httpx.MockTransport)."""

from __future__ import annotations

import httpx
import pytest

from tokensurf.sdk import config as config_module
from tokensurf.sdk.config import ConfigError, fetch_config

SERVER = "http://tokensurf.test"
KEY = "tsk_testkey"


class _Capture:
    """Records requests and returns a canned response."""

    def __init__(self, status: int, body: dict) -> None:
        self.requests: list[httpx.Request] = []
        self.status = status
        self.body = body

    def transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return httpx.Response(self.status, json=self.body)

        return httpx.MockTransport(handler)


def _patch(monkeypatch: pytest.MonkeyPatch, capture: _Capture) -> None:
    t = capture.transport()
    monkeypatch.setattr(
        config_module,
        "_make_client",
        lambda timeout: httpx.Client(transport=t, timeout=timeout),
    )


def test_fetch_config_get_url(monkeypatch: pytest.MonkeyPatch) -> None:
    cap = _Capture(200, {"judge_keys": {"openai": "sk-test"}})
    _patch(monkeypatch, cap)
    fetch_config(server_url=SERVER, api_key=KEY)
    assert len(cap.requests) == 1
    assert str(cap.requests[0].url) == f"{SERVER}/api/v1/config"


def test_fetch_config_uses_get_method(monkeypatch: pytest.MonkeyPatch) -> None:
    cap = _Capture(200, {"judge_keys": {}})
    _patch(monkeypatch, cap)
    fetch_config(server_url=SERVER, api_key=KEY)
    assert cap.requests[0].method == "GET"


def test_fetch_config_bearer_header(monkeypatch: pytest.MonkeyPatch) -> None:
    cap = _Capture(200, {"judge_keys": {}})
    _patch(monkeypatch, cap)
    fetch_config(server_url=SERVER, api_key=KEY)
    assert cap.requests[0].headers["Authorization"] == f"Bearer {KEY}"


def test_fetch_config_returns_parsed_dict(monkeypatch: pytest.MonkeyPatch) -> None:
    body = {"judge_keys": {"openai": "sk-open", "anthropic": "sk-anth"}}
    cap = _Capture(200, body)
    _patch(monkeypatch, cap)
    result = fetch_config(server_url=SERVER, api_key=KEY)
    assert result == body


def test_fetch_config_empty_judge_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    body = {"judge_keys": {}}
    cap = _Capture(200, body)
    _patch(monkeypatch, cap)
    result = fetch_config(server_url=SERVER, api_key=KEY)
    assert result == body


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422, 500])
def test_config_error_on_non_2xx(monkeypatch: pytest.MonkeyPatch, status: int) -> None:
    cap = _Capture(status, {"detail": "server error"})
    _patch(monkeypatch, cap)
    with pytest.raises(ConfigError) as exc_info:
        fetch_config(server_url=SERVER, api_key=KEY)
    assert str(status) in str(exc_info.value)
