from __future__ import annotations

from tokensurf import EvalReport
from tokensurf.core.ids import new_id

from tokensurf_server.gates import GateResult
from tokensurf_server.models import CaseResult, Project, Run, Score
from tokensurf_server.schemas import GateResultOut, RunSummary


def summarize(report: EvalReport) -> dict:
    """Return a dict of run-level summary fields computed from report."""
    error_count = report.error_count()
    return {
        "status": "errored" if error_count > 0 else "completed",
        "n_cases": len(report.results),
        "pass_rate": report.pass_rate(),
        "mean_score": report.mean_score(),
        "error_count": error_count,
    }


def persist_run(
    session,
    *,
    project: Project,
    report: EvalReport,
    label: str | None,
    metadata: dict | None,
) -> Run:
    """Insert Run, one CaseResult per report.results entry, and Score rows.

    Flushes so IDs are available; does NOT commit — caller is responsible.
    """
    s = summarize(report)
    run = Run(
        id=new_id(),
        project_id=project.id,
        label=label,
        status=s["status"],
        n_cases=s["n_cases"],
        pass_rate=s["pass_rate"],
        mean_score=s["mean_score"],
        error_count=s["error_count"],
        source_metadata=metadata,
    )
    session.add(run)
    session.flush()

    for ecr in report.results:
        cr = CaseResult(
            id=new_id(),
            run_id=run.id,
            case_id=ecr.case.id,
            input=ecr.case.input,
            expected=ecr.case.expected,
            output=ecr.trace.output if ecr.trace is not None else None,
            trace=ecr.trace.model_dump(mode="json") if ecr.trace is not None else None,
        )
        session.add(cr)
        session.flush()

        for score in ecr.scores:
            session.add(
                Score(
                    id=new_id(),
                    run_id=run.id,
                    case_result_id=cr.id,
                    scorer=score.scorer,
                    value=score.value,
                    passed=score.passed,
                    error=score.error,
                    raw=score.raw,
                )
            )

    session.flush()
    return run


def run_to_summary(
    run: Run,
    project_slug: str,
    gate_results: list[GateResult] | None = None,
) -> RunSummary:
    """Convert an ORM Run row to a RunSummary response schema.

    ``gate_results`` is optional; existing callers that omit it receive an
    empty ``gate_results`` list in the response (backward-compatible).
    """
    return RunSummary(
        run_id=run.id,
        project=project_slug,
        status=run.status,
        n_cases=run.n_cases,
        pass_rate=run.pass_rate,
        mean_score=run.mean_score,
        error_count=run.error_count,
        created_at=run.created_at,
        gate_results=[
            GateResultOut(
                name=g.name,
                metric=g.metric,
                passed=g.passed,
                actual=g.actual,
                threshold=g.threshold,
            )
            for g in (gate_results or [])
        ],
    )
