"""Tests for tokensurf.sdk.push — no live server required (httpx.MockTransport)."""

from __future__ import annotations

import json

import httpx
import pytest

from tokensurf.core.models import Case, EvalCaseResult, EvalReport, ScoreResult
from tokensurf.sdk import push as push_module
from tokensurf.sdk.push import PushError, RunRef, push_report

SERVER = "http://tokensurf.test"
KEY = "tsk_testkey"


def _minimal_report() -> EvalReport:
    case = Case(id="c1", input="hello", expected="world")
    score = ScoreResult(scorer="exact_match", value=1.0, passed=True)
    return EvalReport(results=[EvalCaseResult(case=case, scores=[score])])


def _run_ref_json() -> dict:
    return {"run_id": "r1", "project": "myproject", "pass_rate": 1.0, "n_cases": 1}


class _Capture:
    """Records every HTTP request the push client sends and returns a canned response."""

    def __init__(self, status: int, body: dict) -> None:
        self.requests: list[httpx.Request] = []
        self.status = status
        self.body = body

    def transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return httpx.Response(self.status, json=self.body)

        return httpx.MockTransport(handler)


def _patch(monkeypatch, capture: _Capture) -> None:
    """Replace push_module._make_client so the client uses MockTransport."""
    t = capture.transport()
    monkeypatch.setattr(
        push_module,
        "_make_client",
        lambda timeout: httpx.Client(transport=t, timeout=timeout),
    )


# ── tests ─────────────────────────────────────────────────────────────────────


def test_post_url(monkeypatch: pytest.MonkeyPatch) -> None:
    cap = _Capture(201, _run_ref_json())
    _patch(monkeypatch, cap)
    push_report(_minimal_report(), server_url=SERVER, api_key=KEY)
    assert len(cap.requests) == 1
    assert str(cap.requests[0].url) == f"{SERVER}/api/v1/runs"


def test_authorization_bearer_header(monkeypatch: pytest.MonkeyPatch) -> None:
    cap = _Capture(201, _run_ref_json())
    _patch(monkeypatch, cap)
    push_report(_minimal_report(), server_url=SERVER, api_key=KEY)
    assert cap.requests[0].headers["Authorization"] == f"Bearer {KEY}"


def test_json_body_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    cap = _Capture(201, _run_ref_json())
    _patch(monkeypatch, cap)
    report = _minimal_report()
    push_report(
        report, server_url=SERVER, api_key=KEY, label="nightly", metadata={"git_sha": "abc123"}
    )
    body = json.loads(cap.requests[0].content)
    assert body["label"] == "nightly"
    assert body["metadata"] == {"git_sha": "abc123"}
    # EvalReport.model_dump(mode="json") produces {"results": [...]}
    assert "results" in body["report"]


def test_json_body_null_optional_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    cap = _Capture(201, _run_ref_json())
    _patch(monkeypatch, cap)
    push_report(_minimal_report(), server_url=SERVER, api_key=KEY)
    body = json.loads(cap.requests[0].content)
    assert body["label"] is None
    assert body["metadata"] is None


def test_returns_run_ref_on_201(monkeypatch: pytest.MonkeyPatch) -> None:
    cap = _Capture(201, _run_ref_json())
    _patch(monkeypatch, cap)
    ref = push_report(_minimal_report(), server_url=SERVER, api_key=KEY)
    assert isinstance(ref, RunRef)
    assert ref.run_id == "r1"
    assert ref.project == "myproject"
    assert ref.pass_rate == 1.0
    assert ref.n_cases == 1


@pytest.mark.parametrize("status", [400, 401, 422, 500])
def test_push_error_on_non_2xx(monkeypatch: pytest.MonkeyPatch, status: int) -> None:
    cap = _Capture(status, {"detail": "server error"})
    _patch(monkeypatch, cap)
    with pytest.raises(PushError) as exc_info:
        push_report(_minimal_report(), server_url=SERVER, api_key=KEY)
    assert str(status) in str(exc_info.value)
