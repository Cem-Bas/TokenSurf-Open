"""Read-only query helpers for the web dashboard.

Returns plain dataclasses; no pydantic, no ORM objects escape this module.
All functions accept an open SQLAlchemy Session and issue synchronous selects
over the 2a tables (Project / Run / CaseResult / Score).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from tokensurf_server.models import (
    CaseResult,
    NotificationChannel,
    Project,
    ProjectSecret,
    QualityGate,
    Run,
    RunGateResult,
    Score,
)


@dataclass
class ProjectSummary:
    slug: str
    name: str
    run_count: int
    latest_pass_rate: float | None
    last_run_at: datetime | None
    sparkline: list[float]


@dataclass
class RunRow:
    run_id: str
    label: str | None
    status: str
    pass_rate: float
    n_cases: int
    error_count: int
    created_at: datetime


@dataclass
class ProjectOverview:
    slug: str
    name: str
    run_count: int
    latest_pass_rate: float | None
    mean_score: float | None
    passrates: list[float]  # oldest-first, for trend chart
    runs: list[RunRow]  # newest-first, for run list table


@dataclass
class ScoreView:
    scorer: str
    value: float | None
    passed: bool | None
    error: str | None


@dataclass
class SpanView:
    type: str
    name: str
    input: object
    output: object
    error: str | None


@dataclass
class CaseView:
    case_id: str
    input: object
    output: object
    scores: list[ScoreView] = field(default_factory=list)
    spans: list[SpanView] = field(default_factory=list)


@dataclass
class ScorerStat:
    scorer: str
    pass_rate: float
    distribution: list[int]  # 4 buckets: [0-.25, .25-.5, .5-.75, .75-1] over non-null values
    bars_html: str = ""  # filled by the route via charts.distribution_bars; rendered with | safe


@dataclass
class GateView:
    id: str
    name: str
    metric: str
    scorer: str | None
    comparison: str
    threshold: float
    enabled: bool


@dataclass
class ChannelView:
    """Never exposes secret_enc — only a boolean has_secret flag."""

    id: str
    type: str
    name: str
    enabled: bool
    has_secret: bool


@dataclass
class SecretView:
    """Never exposes key_enc / plaintext — only a boolean has_value flag."""

    provider: str
    has_value: bool


@dataclass
class GateResultView:
    name: str
    metric: str
    passed: bool
    actual: float | None
    threshold: float


@dataclass
class RunDetail:
    run: RunRow
    project_slug: str
    scorer_stats: list[ScorerStat]
    cases: list[CaseView]
    gate_results: list[GateResultView] = field(default_factory=list)


# ── helpers ───────────────────────────────────────────────────────────────────


def _to_run_row(r: Run) -> RunRow:
    return RunRow(
        run_id=r.id,
        label=r.label,
        status=r.status,
        pass_rate=r.pass_rate,
        n_cases=r.n_cases,
        error_count=r.error_count,
        created_at=r.created_at,
    )


def _distribution(values: list[float]) -> list[int]:
    """Map non-null score values into 4 equal-width buckets over [0, 1]."""
    dist = [0, 0, 0, 0]
    for v in values:
        if v < 0.25:
            dist[0] += 1
        elif v < 0.5:
            dist[1] += 1
        elif v < 0.75:
            dist[2] += 1
        else:
            dist[3] += 1
    return dist


# ── public API ────────────────────────────────────────────────────────────────


def list_projects_with_summary(session: Session) -> list[ProjectSummary]:
    """Return all projects with run count, latest pass-rate, and sparkline.

    Sparkline is pass-rates ordered oldest-first so the caller can pass it
    directly to charts.trend_svg.
    """
    projects = session.execute(select(Project).order_by(Project.created_at.asc())).scalars().all()

    result: list[ProjectSummary] = []
    for p in projects:
        runs = (
            session.execute(
                select(Run).where(Run.project_id == p.id).order_by(Run.created_at.asc())
            )
            .scalars()
            .all()
        )

        sparkline = [r.pass_rate for r in runs]
        latest = runs[-1] if runs else None
        result.append(
            ProjectSummary(
                slug=p.slug,
                name=p.name,
                run_count=len(runs),
                latest_pass_rate=latest.pass_rate if latest else None,
                last_run_at=latest.created_at if latest else None,
                sparkline=sparkline,
            )
        )
    return result


def project_overview(session: Session, slug: str) -> ProjectOverview | None:
    """Return project overview for *slug*, or None if the slug is unknown.

    `runs` is newest-first (for the run list table).
    `passrates` is oldest-first (for the trend chart).
    """
    project = session.execute(select(Project).where(Project.slug == slug)).scalar_one_or_none()
    if project is None:
        return None

    runs = (
        session.execute(
            select(Run).where(Run.project_id == project.id).order_by(Run.created_at.desc())
        )
        .scalars()
        .all()
    )

    run_rows = [_to_run_row(r) for r in runs]
    # passrates for trend: oldest-first (reverse of the desc-ordered list)
    passrates = [r.pass_rate for r in reversed(runs)]
    latest_pass_rate = runs[0].pass_rate if runs else None
    non_null_mean = [r.mean_score for r in runs if r.mean_score is not None]
    mean_score = sum(non_null_mean) / len(non_null_mean) if non_null_mean else None

    return ProjectOverview(
        slug=slug,
        name=project.name,
        run_count=len(runs),
        latest_pass_rate=latest_pass_rate,
        mean_score=mean_score,
        passrates=passrates,
        runs=run_rows,
    )


def run_detail(session: Session, run_id: str, slug: str) -> RunDetail | None:
    """Return full run detail, or None if the run is missing or belongs to a
    different project slug (prevents cross-project data leaks).
    """
    run = session.execute(select(Run).where(Run.id == run_id)).scalar_one_or_none()
    if run is None:
        return None

    project = session.execute(
        select(Project).where(Project.id == run.project_id)
    ).scalar_one_or_none()
    if project is None or project.slug != slug:
        return None

    run_row = _to_run_row(run)

    cases_db = (
        session.execute(select(CaseResult).where(CaseResult.run_id == run_id)).scalars().all()
    )

    scores_db = session.execute(select(Score).where(Score.run_id == run_id)).scalars().all()

    # ── scorer stats ──────────────────────────────────────────────────────────
    scorer_buckets: dict[str, list[Score]] = defaultdict(list)
    for s in scores_db:
        scorer_buckets[s.scorer].append(s)

    scorer_stats: list[ScorerStat] = []
    for scorer, scores in sorted(scorer_buckets.items()):
        non_null_values = [s.value for s in scores if s.value is not None]
        n_passed = sum(1 for s in scores if s.passed is True)
        pass_rate = n_passed / len(scores) if scores else 0.0
        scorer_stats.append(
            ScorerStat(
                scorer=scorer,
                pass_rate=pass_rate,
                distribution=_distribution(non_null_values),
            )
        )

    # ── case views ────────────────────────────────────────────────────────────
    scores_by_case: dict[str, list[Score]] = defaultdict(list)
    for s in scores_db:
        scores_by_case[s.case_result_id].append(s)

    case_views: list[CaseView] = []
    for c in cases_db:
        score_views = [
            ScoreView(scorer=s.scorer, value=s.value, passed=s.passed, error=s.error)
            for s in scores_by_case.get(c.id, [])
        ]
        spans: list[SpanView] = []
        if c.trace:
            for span_dict in c.trace.get("spans", []):
                spans.append(
                    SpanView(
                        type=span_dict.get("type", ""),
                        name=span_dict.get("name", ""),
                        input=span_dict.get("input"),
                        output=span_dict.get("output"),
                        error=span_dict.get("error"),
                    )
                )
        case_views.append(
            CaseView(
                case_id=c.case_id,
                input=c.input,
                output=c.output,
                scores=score_views,
                spans=spans,
            )
        )

    gate_results = gate_results_for_run(session, run_id)

    return RunDetail(
        run=run_row,
        project_slug=slug,
        scorer_stats=scorer_stats,
        cases=case_views,
        gate_results=gate_results,
    )


def list_gates(session: Session, slug: str) -> list[GateView] | None:
    """Return enabled quality gates for *slug*, or None if the slug is unknown."""
    project = session.execute(select(Project).where(Project.slug == slug)).scalar_one_or_none()
    if project is None:
        return None
    rows = (
        session.execute(
            select(QualityGate)
            .where(QualityGate.project_id == project.id)
            .order_by(QualityGate.created_at.asc())
        )
        .scalars()
        .all()
    )
    return [
        GateView(
            id=g.id,
            name=g.name,
            metric=g.metric,
            scorer=g.scorer,
            comparison=g.comparison,
            threshold=g.threshold,
            enabled=g.enabled,
        )
        for g in rows
    ]


def list_channels(session: Session, slug: str) -> list[ChannelView] | None:
    """Return notification channels for *slug*, or None if the slug is unknown.

    secret_enc is never included — only a boolean has_secret flag so the UI can
    show "•••• set" without ever rendering the ciphertext.
    """
    project = session.execute(select(Project).where(Project.slug == slug)).scalar_one_or_none()
    if project is None:
        return None
    rows = (
        session.execute(
            select(NotificationChannel)
            .where(NotificationChannel.project_id == project.id)
            .order_by(NotificationChannel.created_at.asc())
        )
        .scalars()
        .all()
    )
    return [
        ChannelView(
            id=ch.id,
            type=ch.type,
            name=ch.name,
            enabled=ch.enabled,
            has_secret=bool(ch.secret_enc),
        )
        for ch in rows
    ]


def gate_results_for_run(session: Session, run_id: str) -> list[GateResultView]:
    """Return gate evaluation results recorded for *run_id* (empty list if none)."""
    rows = (
        session.execute(
            select(RunGateResult)
            .where(RunGateResult.run_id == run_id)
            .order_by(RunGateResult.created_at.asc())
        )
        .scalars()
        .all()
    )
    return [
        GateResultView(
            name=r.gate_name,
            metric=r.metric,
            passed=r.passed,
            actual=r.actual,
            threshold=r.threshold,
        )
        for r in rows
    ]


def list_secrets(session: Session, slug: str) -> list[SecretView] | None:
    """Return provider+has_value pairs for *slug*, or None if the slug is unknown.

    key_enc is never included.  Sorted by provider.
    """
    project = session.execute(select(Project).where(Project.slug == slug)).scalar_one_or_none()
    if project is None:
        return None
    rows = (
        session.execute(
            select(ProjectSecret)
            .where(ProjectSecret.project_id == project.id)
            .order_by(ProjectSecret.provider.asc())
        )
        .scalars()
        .all()
    )
    return [SecretView(provider=row.provider, has_value=bool(row.key_enc)) for row in rows]


@dataclass
class RunListRow:
    run_id: str
    project_slug: str
    project_name: str
    label: str | None
    status: str
    pass_rate: float
    n_cases: int
    created_at: datetime
    gates_total: int
    gates_failed: int


def list_all_runs(
    session: Session,
    *,
    project_slug: str | None = None,
    gate_status: str | None = None,
    limit: int = 25,
    offset: int = 0,
) -> tuple[list[RunListRow], int]:
    """Cross-project run list with optional project + gate-status filters and pagination.

    gate_status: "failed" -> runs with >=1 failed gate; "passed" -> runs with gates,
    none failed. Returns (rows newest-first, total matching count).
    """
    gate_sub = (
        select(
            RunGateResult.run_id.label("rid"),
            func.count().label("gtotal"),
            func.sum(case((RunGateResult.passed.is_(False), 1), else_=0)).label("gfailed"),
        )
        .group_by(RunGateResult.run_id)
        .subquery()
    )
    gtotal = func.coalesce(gate_sub.c.gtotal, 0)
    gfailed = func.coalesce(gate_sub.c.gfailed, 0)
    base = (
        select(Run, Project.slug, Project.name, gtotal.label("gt"), gfailed.label("gf"))
        .join(Project, Run.project_id == Project.id)
        .outerjoin(gate_sub, gate_sub.c.rid == Run.id)
    )
    if project_slug:
        base = base.where(Project.slug == project_slug)
    if gate_status == "failed":
        base = base.where(gfailed > 0)
    elif gate_status == "passed":
        base = base.where((gtotal > 0) & (gfailed == 0))

    total = session.scalar(select(func.count()).select_from(base.subquery())) or 0
    result = session.execute(base.order_by(Run.created_at.desc()).limit(limit).offset(offset)).all()
    rows = [
        RunListRow(
            run_id=r.Run.id,
            project_slug=r.slug,
            project_name=r.name,
            label=r.Run.label,
            status=r.Run.status,
            pass_rate=r.Run.pass_rate,
            n_cases=r.Run.n_cases,
            created_at=r.Run.created_at,
            gates_total=int(r.gt),
            gates_failed=int(r.gf),
        )
        for r in result
    ]
    return rows, total
