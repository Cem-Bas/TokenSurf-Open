"""Console + JSONL reporting for EvalReports."""

from __future__ import annotations

import os
from pathlib import Path

from tokensurf.core.models import EvalReport


def render_console(report: EvalReport) -> str:
    lines: list[str] = [f"Cases: {len(report.results)}"]
    header = f"{'scorer':<24} {'pass_rate':>10} {'mean':>8} {'errors':>8}"
    lines.append(header)
    lines.append("-" * len(header))
    for name in report.scorer_names():
        pass_rate = report.pass_rate(name)
        mean = report.mean_score(name)
        errors = sum(
            1
            for result in report.results
            for score in result.scores
            if score.scorer == name and score.error is not None
        )
        mean_str = f"{mean:.3f}" if mean is not None else "n/a"
        lines.append(f"{name:<24} {pass_rate:>10.3f} {mean_str:>8} {errors:>8}")
    lines.append(f"Total errors: {report.error_count()}")
    return "\n".join(lines)


def write_jsonl(report: EvalReport, path: str | os.PathLike[str]) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for result in report.results:
            fh.write(result.model_dump_json())
            fh.write("\n")
