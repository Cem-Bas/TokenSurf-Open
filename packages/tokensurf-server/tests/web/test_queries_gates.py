"""DB tests for the gate/channel query helpers added to web/queries.py in slice 2c."""

from __future__ import annotations

import datetime
from zoneinfo import ZoneInfo

import pytest
from tokensurf.core.ids import new_id

from tokensurf_server.models import (
    CaseResult,
    NotificationChannel,
    Project,
    QualityGate,
    Run,
    RunGateResult,
)
from tokensurf_server.web.queries import (
    ChannelView,
    GateResultView,
    GateView,
    RunDetail,
    gate_results_for_run,
    list_channels,
    list_gates,
    run_detail,
)

UTC = ZoneInfo("UTC")
_BASE_DT = datetime.datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)


def _project(slug: str, name: str = "Test") -> Project:
    return Project(id=new_id(), name=name, slug=slug)


def _run(project_id: str) -> Run:
    return Run(
        id=new_id(),
        project_id=project_id,
        label="v1",
        status="done",
        pass_rate=0.8,
        n_cases=5,
        error_count=0,
        created_at=_BASE_DT,
    )


def _gate(project_id: str, *, name: str = "PR gate", enabled: bool = True) -> QualityGate:
    return QualityGate(
        id=new_id(),
        project_id=project_id,
        name=name,
        metric="pass_rate",
        scorer=None,
        comparison="gte",
        threshold=0.9,
        enabled=enabled,
    )


def _channel(project_id: str, *, name: str = "Slack", type_: str = "slack") -> NotificationChannel:
    return NotificationChannel(
        id=new_id(),
        project_id=project_id,
        type=type_,
        name=name,
        secret_enc="encrypted-placeholder",
        config=None,
        enabled=True,
    )


def _run_gate_result(run_id: str, gate_id: str | None = None) -> RunGateResult:
    return RunGateResult(
        id=new_id(),
        run_id=run_id,
        gate_id=gate_id,
        gate_name="PR gate",
        metric="pass_rate",
        comparison="gte",
        threshold=0.9,
        actual=0.75,
        passed=False,
    )


# ── list_gates ────────────────────────────────────────────────────────────────


def test_list_gates_unknown_slug_returns_none(db_session) -> None:
    assert list_gates(db_session, "no-such-slug-dqg-1") is None


def test_list_gates_returns_gate_views(db_session) -> None:
    p = _project("dqg-gates-basic")
    g = _gate(p.id, name="My Gate")
    db_session.add(p)
    db_session.flush()
    db_session.add(g)
    db_session.flush()

    result = list_gates(db_session, "dqg-gates-basic")
    assert result is not None
    assert len(result) == 1
    gv = result[0]
    assert isinstance(gv, GateView)
    assert gv.id == g.id
    assert gv.name == "My Gate"
    assert gv.metric == "pass_rate"
    assert gv.scorer is None
    assert gv.comparison == "gte"
    assert gv.threshold == pytest.approx(0.9)
    assert gv.enabled is True


def test_list_gates_empty_project_returns_empty_list(db_session) -> None:
    p = _project("dqg-gates-empty")
    db_session.add(p)
    db_session.flush()

    result = list_gates(db_session, "dqg-gates-empty")
    assert result == []


def test_list_gates_multiple_projects_no_cross_contamination(db_session) -> None:
    p1 = _project("dqg-gates-p1")
    p2 = _project("dqg-gates-p2")
    g1 = _gate(p1.id, name="P1 Gate")
    g2 = _gate(p2.id, name="P2 Gate")
    db_session.add_all([p1, p2])
    db_session.flush()
    db_session.add_all([g1, g2])
    db_session.flush()

    result = list_gates(db_session, "dqg-gates-p1")
    assert result is not None
    names = [gv.name for gv in result]
    assert "P1 Gate" in names
    assert "P2 Gate" not in names


# ── list_channels ─────────────────────────────────────────────────────────────


def test_list_channels_unknown_slug_returns_none(db_session) -> None:
    assert list_channels(db_session, "no-such-slug-dqg-2") is None


def test_list_channels_returns_channel_views(db_session) -> None:
    p = _project("dqg-ch-basic")
    ch = _channel(p.id, name="My Slack", type_="slack")
    db_session.add(p)
    db_session.flush()
    db_session.add(ch)
    db_session.flush()

    result = list_channels(db_session, "dqg-ch-basic")
    assert result is not None
    assert len(result) == 1
    cv = result[0]
    assert isinstance(cv, ChannelView)
    assert cv.id == ch.id
    assert cv.name == "My Slack"
    assert cv.type == "slack"
    assert cv.enabled is True


def test_list_channels_has_secret_true_when_secret_enc_set(db_session) -> None:
    p = _project("dqg-ch-secret")
    ch = _channel(p.id)
    ch.secret_enc = "some-encrypted-value"
    db_session.add(p)
    db_session.flush()
    db_session.add(ch)
    db_session.flush()

    result = list_channels(db_session, "dqg-ch-secret")
    assert result is not None
    cv = result[0]
    assert cv.has_secret is True


def test_list_channels_secret_enc_never_exposed(db_session) -> None:
    """ChannelView must not have a secret_enc attribute — raw ciphertext must never leak."""
    p = _project("dqg-ch-nosecret-attr")
    ch = _channel(p.id)
    db_session.add(p)
    db_session.flush()
    db_session.add(ch)
    db_session.flush()

    result = list_channels(db_session, "dqg-ch-nosecret-attr")
    assert result is not None
    cv = result[0]
    assert not hasattr(cv, "secret_enc"), "ChannelView must not expose secret_enc"


def test_list_channels_empty_project_returns_empty_list(db_session) -> None:
    p = _project("dqg-ch-empty")
    db_session.add(p)
    db_session.flush()

    result = list_channels(db_session, "dqg-ch-empty")
    assert result == []


def test_list_channels_cross_slug_none(db_session) -> None:
    p = _project("dqg-ch-cross-a")
    ch = _channel(p.id)
    db_session.add(p)
    db_session.flush()
    db_session.add(ch)
    db_session.flush()

    assert list_channels(db_session, "dqg-ch-cross-b-nonexistent") is None


# ── gate_results_for_run ──────────────────────────────────────────────────────


def test_gate_results_for_run_returns_empty_list_when_no_results(db_session) -> None:
    p = _project("dqg-grr-empty")
    r = _run(p.id)
    db_session.add_all([p, r])
    db_session.flush()

    result = gate_results_for_run(db_session, r.id)
    assert result == []


def test_gate_results_for_run_returns_gate_result_views(db_session) -> None:
    p = _project("dqg-grr-basic")
    r = _run(p.id)
    db_session.add_all([p, r])
    db_session.flush()

    grr = _run_gate_result(r.id)
    db_session.add(grr)
    db_session.flush()

    result = gate_results_for_run(db_session, r.id)
    assert len(result) == 1
    gv = result[0]
    assert isinstance(gv, GateResultView)
    assert gv.name == "PR gate"
    assert gv.metric == "pass_rate"
    assert gv.passed is False
    assert gv.actual == pytest.approx(0.75)
    assert gv.threshold == pytest.approx(0.9)


def test_gate_results_for_run_only_returns_own_run_results(db_session) -> None:
    p = _project("dqg-grr-isolation")
    r1 = _run(p.id)
    r2 = _run(p.id)
    db_session.add_all([p, r1, r2])
    db_session.flush()

    grr1 = _run_gate_result(r1.id)
    grr2 = _run_gate_result(r2.id)
    grr2.gate_name = "Other Gate"
    db_session.add_all([grr1, grr2])
    db_session.flush()

    result = gate_results_for_run(db_session, r1.id)
    assert len(result) == 1
    assert result[0].name == "PR gate"


# ── RunDetail.gate_results via run_detail() ───────────────────────────────────


def test_run_detail_includes_gate_results_field() -> None:
    """RunDetail dataclass must have a gate_results field (dataclass field, not dynamic)."""
    import dataclasses

    field_names = [f.name for f in dataclasses.fields(RunDetail)]
    assert "gate_results" in field_names


def test_run_detail_gate_results_populated(db_session) -> None:
    p = _project("dqg-rd-gates")
    r = _run(p.id)
    db_session.add_all([p, r])
    db_session.flush()

    grr = _run_gate_result(r.id)
    db_session.add(grr)
    db_session.flush()

    detail = run_detail(db_session, r.id, "dqg-rd-gates")
    assert detail is not None
    assert len(detail.gate_results) == 1
    gv = detail.gate_results[0]
    assert gv.name == "PR gate"
    assert gv.passed is False


def test_run_detail_gate_results_empty_when_no_gate_results(db_session) -> None:
    p = _project("dqg-rd-nogates")
    r = _run(p.id)
    cr = CaseResult(id=new_id(), run_id=r.id, case_id="c1")
    db_session.add_all([p, r, cr])
    db_session.flush()

    detail = run_detail(db_session, r.id, "dqg-rd-nogates")
    assert detail is not None
    assert detail.gate_results == []
