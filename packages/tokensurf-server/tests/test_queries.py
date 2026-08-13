"""Tests for web/queries.py — read-only data layer (seeded in-test, no live rows)."""

from __future__ import annotations

import datetime
from zoneinfo import ZoneInfo

import pytest
from tokensurf.core.ids import new_id

from tokensurf_server.models import CaseResult, Project, Run, Score
from tokensurf_server.web.queries import (
    economics_overview,
    list_projects_with_summary,
    project_overview,
    run_detail,
    scorers_overview,
)

UTC = ZoneInfo("UTC")

_BASE_DT = datetime.datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)


def _project(slug: str, name: str = "Test Project") -> Project:
    return Project(id=new_id(), name=name, slug=slug)


def _run(
    project_id: str,
    *,
    pass_rate: float = 0.8,
    label: str | None = None,
    status: str = "done",
    n_cases: int = 4,
    error_count: int = 0,
    mean_score: float | None = None,
    offset_hours: int = 0,
) -> Run:
    return Run(
        id=new_id(),
        project_id=project_id,
        label=label,
        status=status,
        pass_rate=pass_rate,
        n_cases=n_cases,
        error_count=error_count,
        mean_score=mean_score,
        created_at=_BASE_DT + datetime.timedelta(hours=offset_hours),
    )


def _score(
    run_id: str,
    case_result_id: str,
    *,
    scorer: str = "accuracy",
    value: float | None = None,
    passed: bool | None = None,
    error: str | None = None,
) -> Score:
    return Score(
        id=new_id(),
        run_id=run_id,
        case_result_id=case_result_id,
        scorer=scorer,
        value=value,
        passed=passed,
        error=error,
    )


def _payment_span(
    *,
    usd: float | None = None,
    amount: str = "100",
    recipient: str = "merchant",
    success: bool = True,
) -> dict:
    attributes = {
        "payment.recorded": True,
        "payment.protocol": "x402",
        "payment.amount": amount,
        "payment.asset": "USDC",
        "payment.network": "eip155:8453",
        "payment.recipient": recipient,
        "payment.success": success,
    }
    if usd is not None:
        attributes["payment.amount_usd"] = usd
    return {"type": "custom", "name": "payment.x402", "attributes": attributes}


# ── economics_overview ───────────────────────────────────────────────────────


def test_economics_overview_aggregates_settled_failed_and_unpriced(db_session):
    project = _project("qry-economics", "Economic Agent")
    db_session.add(project)
    run = _run(project.id, label="pay-v1")
    db_session.add(run)
    db_session.add(
        CaseResult(
            id=new_id(),
            run_id=run.id,
            case_id="payments",
            trace={
                "spans": [
                    _payment_span(usd=0.25),
                    _payment_span(success=False),
                    _payment_span(amount="300"),
                    {"name": "ordinary", "attributes": {"cost": 999}},
                ]
            },
        )
    )
    db_session.flush()

    overview = economics_overview(db_session)
    project_summary = next(item for item in overview.projects if item.slug == "qry-economics")
    assert project_summary.total_usd == pytest.approx(0.25)
    assert project_summary.settled_payments == 2
    assert project_summary.failed_payments == 1
    assert project_summary.unpriced_settlements == 1
    assert len([p for p in overview.recent_payments if p.project_slug == "qry-economics"]) == 3


def test_economics_overview_applies_recent_limit_without_changing_totals(db_session):
    project = _project("qry-economics-limit")
    db_session.add(project)
    run = _run(project.id)
    db_session.add(run)
    db_session.add(
        CaseResult(
            id=new_id(),
            run_id=run.id,
            case_id="payments",
            trace={"spans": [_payment_span(usd=0.1), _payment_span(usd=0.2)]},
        )
    )
    db_session.flush()

    overview = economics_overview(db_session, recent_limit=1)
    assert len(overview.recent_payments) == 1
    assert overview.total_usd >= 0.3


# ── scorers_overview ─────────────────────────────────────────────────────────


def test_scorers_overview_aggregates_health_and_recent_problems(db_session):
    project = _project("qry-scorers", "Scored Agent")
    db_session.add(project)
    run = _run(project.id, label="scored-v1")
    db_session.add(run)
    case_one = CaseResult(id=new_id(), run_id=run.id, case_id="case-pass")
    case_two = CaseResult(id=new_id(), run_id=run.id, case_id="case-fail")
    db_session.add_all([case_one, case_two])
    db_session.add_all(
        [
            _score(run.id, case_one.id, scorer="ExactMatch", value=1.0, passed=True),
            _score(run.id, case_two.id, scorer="ExactMatch", value=0.0, passed=False),
            _score(
                run.id,
                case_two.id,
                scorer="custom-policy",
                value=None,
                passed=None,
                error="judge unavailable",
            ),
        ]
    )
    db_session.flush()

    overview = scorers_overview(db_session)
    exact = next(item for item in overview.scorers if item.name == "ExactMatch")
    custom = next(item for item in overview.scorers if item.name == "custom-policy")
    assert exact.family == "Deterministic"
    assert exact.total_scores == 2
    assert exact.pass_rate == pytest.approx(0.5)
    assert exact.mean_score == pytest.approx(0.5)
    assert exact.failed_scores == 1
    assert custom.family == "Custom"
    assert custom.pass_rate is None
    assert custom.errored_scores == 1
    assert overview.failed_scores >= 1
    assert overview.errored_scores >= 1
    assert {item.scorer for item in overview.recent_problems[:2]} == {
        "ExactMatch",
        "custom-policy",
    }


def test_scorers_overview_recent_limit_does_not_change_totals(db_session):
    project = _project("qry-scorers-limit")
    db_session.add(project)
    run = _run(project.id)
    db_session.add(run)
    case_one = CaseResult(id=new_id(), run_id=run.id, case_id="one")
    case_two = CaseResult(id=new_id(), run_id=run.id, case_id="two")
    db_session.add_all([case_one, case_two])
    db_session.add_all(
        [
            _score(run.id, case_one.id, scorer="policy", value=0.0, passed=False),
            _score(run.id, case_two.id, scorer="policy", value=0.0, passed=False),
        ]
    )
    db_session.flush()

    overview = scorers_overview(db_session, recent_limit=1)
    policy = next(item for item in overview.scorers if item.name == "policy")
    assert len(overview.recent_problems) == 1
    assert policy.total_scores == 2


# ── list_projects_with_summary ────────────────────────────────────────────────


def test_list_projects_run_count(db_session):
    p = _project("qry-lp-count")
    db_session.add(p)
    db_session.add_all([_run(p.id, offset_hours=i, pass_rate=0.5 + i * 0.1) for i in range(3)])
    db_session.flush()

    summaries = list_projects_with_summary(db_session)
    match = next((s for s in summaries if s.slug == "qry-lp-count"), None)
    assert match is not None
    assert match.run_count == 3


def test_list_projects_sparkline_oldest_first(db_session):
    p = _project("qry-lp-spark")
    db_session.add(p)
    db_session.add_all(
        [
            _run(p.id, offset_hours=0, pass_rate=0.5),
            _run(p.id, offset_hours=1, pass_rate=0.7),
            _run(p.id, offset_hours=2, pass_rate=0.9),
        ]
    )
    db_session.flush()

    summaries = list_projects_with_summary(db_session)
    match = next(s for s in summaries if s.slug == "qry-lp-spark")
    assert match.sparkline == pytest.approx([0.5, 0.7, 0.9])
    assert match.latest_pass_rate == pytest.approx(0.9)
    assert match.last_run_at == _BASE_DT + datetime.timedelta(hours=2)


def test_list_projects_no_runs(db_session):
    p = _project("qry-lp-empty")
    db_session.add(p)
    db_session.flush()

    summaries = list_projects_with_summary(db_session)
    match = next(s for s in summaries if s.slug == "qry-lp-empty")
    assert match.run_count == 0
    assert match.latest_pass_rate is None
    assert match.sparkline == []


# ── project_overview ──────────────────────────────────────────────────────────


def test_project_overview_unknown_slug_returns_none(db_session):
    assert project_overview(db_session, "no-such-slug-xyz-b1") is None


def test_project_overview_passrates_oldest_first(db_session):
    p = _project("qry-po-passrates")
    db_session.add(p)
    db_session.add_all(
        [
            _run(p.id, offset_hours=0, pass_rate=0.4),
            _run(p.id, offset_hours=1, pass_rate=0.6),
            _run(p.id, offset_hours=2, pass_rate=0.8),
        ]
    )
    db_session.flush()

    overview = project_overview(db_session, "qry-po-passrates")
    assert overview is not None
    assert len(overview.passrates) == 3
    assert overview.passrates == pytest.approx([0.4, 0.6, 0.8])


def test_project_overview_runs_newest_first(db_session):
    p = _project("qry-po-order")
    db_session.add(p)
    db_session.add_all(
        [
            _run(p.id, offset_hours=0, pass_rate=0.4, label="v1"),
            _run(p.id, offset_hours=1, pass_rate=0.6, label="v2"),
            _run(p.id, offset_hours=2, pass_rate=0.8, label="v3"),
        ]
    )
    db_session.flush()

    overview = project_overview(db_session, "qry-po-order")
    assert overview is not None
    assert [r.label for r in overview.runs] == ["v3", "v2", "v1"]


def test_project_overview_counts_and_latest(db_session):
    p = _project("qry-po-counts")
    db_session.add(p)
    db_session.add_all(
        [
            _run(p.id, offset_hours=0, pass_rate=0.4),
            _run(p.id, offset_hours=1, pass_rate=0.6),
            _run(p.id, offset_hours=2, pass_rate=0.8),
        ]
    )
    db_session.flush()

    overview = project_overview(db_session, "qry-po-counts")
    assert overview is not None
    assert overview.run_count == 3
    assert overview.latest_pass_rate == pytest.approx(0.8)
    assert overview.slug == "qry-po-counts"


# ── run_detail ────────────────────────────────────────────────────────────────


def test_run_detail_missing_run_returns_none(db_session):
    assert run_detail(db_session, "nonexistent-run-id-b1", "any-slug") is None


def test_run_detail_cross_slug_returns_none(db_session):
    p1 = _project("qry-rd-proj-alpha")
    p2 = _project("qry-rd-proj-beta")
    db_session.add_all([p1, p2])
    r = _run(p1.id, offset_hours=0)
    db_session.add(r)
    db_session.flush()

    # r belongs to p1; querying with p2's slug must return None (no cross-project leak)
    assert run_detail(db_session, r.id, "qry-rd-proj-beta") is None


def test_run_detail_correct_slug_returns_detail(db_session):
    p = _project("qry-rd-ok")
    db_session.add(p)
    r = _run(p.id, offset_hours=0, label="v9", n_cases=1)
    db_session.add(r)
    cr = CaseResult(id=new_id(), run_id=r.id, case_id="c1")
    db_session.add(cr)
    db_session.flush()

    detail = run_detail(db_session, r.id, "qry-rd-ok")
    assert detail is not None
    assert detail.project_slug == "qry-rd-ok"
    assert detail.run.label == "v9"
    assert len(detail.cases) == 1
    assert detail.cases[0].case_id == "c1"


def test_run_detail_scorer_stats_distribution(db_session):
    p = _project("qry-rd-dist")
    db_session.add(p)
    r = _run(p.id, offset_hours=0, n_cases=4)
    db_session.add(r)
    cr1 = CaseResult(id=new_id(), run_id=r.id, case_id="c1")
    cr2 = CaseResult(id=new_id(), run_id=r.id, case_id="c2")
    cr3 = CaseResult(id=new_id(), run_id=r.id, case_id="c3")
    cr4 = CaseResult(id=new_id(), run_id=r.id, case_id="c4")
    db_session.add_all([cr1, cr2, cr3, cr4])
    # 0.1 → bucket[0]; 0.3 → bucket[1]; 0.6 → bucket[2]; 0.9 → bucket[3]
    db_session.add_all(
        [
            _score(r.id, cr1.id, scorer="acc", value=0.1, passed=False),
            _score(r.id, cr2.id, scorer="acc", value=0.3, passed=False),
            _score(r.id, cr3.id, scorer="acc", value=0.6, passed=True),
            _score(r.id, cr4.id, scorer="acc", value=0.9, passed=True),
        ]
    )
    db_session.flush()

    detail = run_detail(db_session, r.id, "qry-rd-dist")
    assert detail is not None
    assert len(detail.scorer_stats) == 1
    stat = detail.scorer_stats[0]
    assert stat.scorer == "acc"
    assert stat.distribution == [1, 1, 1, 1]  # one score per bucket
    assert stat.pass_rate == pytest.approx(0.5)  # 2 passed out of 4


def test_run_detail_trace_spans(db_session):
    p = _project("qry-rd-trace")
    db_session.add(p)
    r = _run(p.id, offset_hours=0, n_cases=1)
    db_session.add(r)
    cr = CaseResult(
        id=new_id(),
        run_id=r.id,
        case_id="c1",
        input={"prompt": "hello"},
        output={"text": "world"},
        trace={
            "spans": [
                {
                    "type": "llm",
                    "name": "gpt-4o",
                    "input": {"messages": [{"role": "user", "content": "hi"}]},
                    "output": {"content": "hello"},
                    "error": None,
                }
            ]
        },
    )
    db_session.add(cr)
    db_session.flush()

    detail = run_detail(db_session, r.id, "qry-rd-trace")
    assert detail is not None
    assert len(detail.cases) == 1
    case = detail.cases[0]
    assert len(case.spans) == 1
    span = case.spans[0]
    assert span.type == "llm"
    assert span.name == "gpt-4o"
    assert span.output == {"content": "hello"}
    assert span.error is None


def test_run_detail_null_scores_excluded_from_distribution(db_session):
    """Null value scores are excluded from distribution buckets but count toward pass_rate."""
    p = _project("qry-rd-null")
    db_session.add(p)
    r = _run(p.id, offset_hours=0, n_cases=2)
    db_session.add(r)
    cr1 = CaseResult(id=new_id(), run_id=r.id, case_id="c1")
    cr2 = CaseResult(id=new_id(), run_id=r.id, case_id="c2")
    db_session.add_all([cr1, cr2])
    db_session.add_all(
        [
            _score(r.id, cr1.id, scorer="clarity", value=0.8, passed=True),
            _score(r.id, cr2.id, scorer="clarity", value=None, passed=None, error="timeout"),
        ]
    )
    db_session.flush()

    detail = run_detail(db_session, r.id, "qry-rd-null")
    assert detail is not None
    stat = detail.scorer_stats[0]
    # Only 1 non-null value → distribution total = 1, in bucket[3]
    assert stat.distribution == [0, 0, 0, 1]
