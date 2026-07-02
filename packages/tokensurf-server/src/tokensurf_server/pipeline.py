"""Gate-evaluation + notification pipeline, called after every successful ingest.

Best-effort: the entire function is wrapped in try/except so it can never raise
into the ingest handler. A failure here is logged and returns []; the 201 is
always returned to the caller regardless.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session
from tokensurf.core.ids import new_id

from tokensurf_server.gates import GateResult, evaluate_gates
from tokensurf_server.models import NotificationChannel, QualityGate, RunGateResult

logger = logging.getLogger(__name__)


def evaluate_and_notify(
    session: Session,
    *,
    project,
    run,
    report,
) -> list[GateResult]:
    """Evaluate enabled quality gates for *project* against *report*, persist
    RunGateResult rows, and fire notifications for any breach or errored run.

    Always returns a (possibly empty) list and never raises.
    """
    try:
        gates = list(
            session.scalars(
                select(QualityGate).where(
                    QualityGate.project_id == project.id,
                    QualityGate.enabled == True,  # noqa: E712
                )
            )
        )
        results = evaluate_gates(report, gates)

        for r in results:
            session.add(
                RunGateResult(
                    id=new_id(),
                    run_id=run.id,
                    gate_id=r.gate_id,
                    gate_name=r.name,
                    metric=r.metric,
                    comparison=r.comparison,
                    threshold=r.threshold,
                    actual=r.actual,
                    passed=r.passed,
                )
            )
        session.commit()

        failed = [r for r in results if not r.passed]
        if failed or run.status == "errored":
            channels = list(
                session.scalars(
                    select(NotificationChannel).where(
                        NotificationChannel.project_id == project.id,
                        NotificationChannel.enabled == True,  # noqa: E712
                    )
                )
            )
            if channels:
                from tokensurf_server.notify import send_for_run

                send_for_run(session, channels, run, failed)

        return results

    except Exception:
        logger.exception(
            "evaluate_and_notify failed for run=%s project=%s; skipping (best-effort)",
            run.id,
            project.id,
        )
        return []
