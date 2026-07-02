"""Jinja render tests for projects.html, project.html, and run.html.

Each template is loaded with a minimal fake context built from plain
SimpleNamespace objects (no DB). Tests assert key strings render and
that run labels containing '<script>' are escaped.
"""

from __future__ import annotations

import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import jinja2
import pytest

TEMPLATES_DIR = Path(__file__).parent.parent.parent / "src/tokensurf_server/web/templates"


@pytest.fixture
def env() -> jinja2.Environment:
    return jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=True,
    )


def _request(path: str = "/") -> SimpleNamespace:
    return SimpleNamespace(url=SimpleNamespace(path=path))


def _user() -> SimpleNamespace:
    return SimpleNamespace(email="alice@example.com")


def _project_summary(
    slug: str = "luna-support",
    name: str = "Luna Support",
    run_count: int = 10,
    latest_pass_rate: float | None = 0.87,
    last_run_at: datetime.datetime | None = None,
    sparkline: list[float] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        slug=slug,
        name=name,
        run_count=run_count,
        latest_pass_rate=latest_pass_rate,
        last_run_at=last_run_at or datetime.datetime(2026, 6, 28, 12, 0, 0),
        sparkline=sparkline or [0.7, 0.8, 0.75, 0.9, 0.87],
    )


def _run_row(
    run_id: str = "abc123",
    label: str | None = "v1.0.0",
    status: str = "passed",
    pass_rate: float = 0.87,
    n_cases: int = 8,
    error_count: int = 0,
    created_at: datetime.datetime | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        run_id=run_id,
        label=label,
        status=status,
        pass_rate=pass_rate,
        n_cases=n_cases,
        error_count=error_count,
        created_at=created_at or datetime.datetime(2026, 6, 28, 12, 0, 0),
    )


def _overview(
    slug: str = "luna-support",
    name: str = "Luna Support",
    runs: list[Any] | None = None,
    passrates: list[float] | None = None,
    latest_pass_rate: float | None = 0.87,
    mean_score: float | None = 0.83,
    run_count: int = 10,
) -> SimpleNamespace:
    return SimpleNamespace(
        slug=slug,
        name=name,
        run_count=run_count,
        latest_pass_rate=latest_pass_rate,
        mean_score=mean_score,
        passrates=passrates or [0.7, 0.8, 0.75, 0.9, 0.87],
        runs=runs or [_run_row()],
    )


def _score_view(
    scorer: str = "accuracy",
    value: float | None = 0.9,
    passed: bool | None = True,
    error: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(scorer=scorer, value=value, passed=passed, error=error)


def _span_view(
    type: str = "llm",
    name: str = "generate",
    input: object = "hello",
    output: object = "world",
    error: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(type=type, name=name, input=input, output=output, error=error)


def _case_view(case_id: str = "case-1") -> SimpleNamespace:
    return SimpleNamespace(
        case_id=case_id,
        input="What is 2+2?",
        output="4",
        scores=[_score_view()],
        spans=[_span_view()],
    )


def _scorer_stat(scorer: str = "accuracy") -> SimpleNamespace:
    # bars_html is the string produced by charts.distribution_bars — safe HTML
    return SimpleNamespace(
        scorer=scorer,
        pass_rate=0.87,
        distribution=[2, 1, 4, 3],
        bars_html=(
            '<div class="dist-bars">'
            '<div class="dist-col">'
            '<div class="dist-bar bar-poor" style="height:20%"></div>'
            '<div class="dist-label">0-.25</div>'
            "</div></div>"
        ),
    )


def _run_detail(label: str = "v1.0.0", gate_results: list | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        run=_run_row(label=label),
        project_slug="luna-support",
        scorer_stats=[_scorer_stat()],
        cases=[_case_view()],
        gate_results=gate_results if gate_results is not None else [],
    )


# ── projects.html ─────────────────────────────────────────────────────────────


class TestProjectsTemplate:
    def test_renders_project_name(self, env: jinja2.Environment):
        tmpl = env.get_template("projects.html")
        html = tmpl.render(
            request=_request("/"),
            user=_user(),
            projects=[_project_summary()],
        )
        assert "Luna Support" in html

    def test_renders_pass_rate_chip(self, env: jinja2.Environment):
        tmpl = env.get_template("projects.html")
        html = tmpl.render(
            request=_request("/"),
            user=_user(),
            projects=[_project_summary(latest_pass_rate=0.87)],
        )
        assert "score-chip" in html
        assert "87" in html

    def test_project_link(self, env: jinja2.Environment):
        tmpl = env.get_template("projects.html")
        html = tmpl.render(
            request=_request("/"),
            user=_user(),
            projects=[_project_summary(slug="luna-support")],
        )
        assert "/projects/luna-support" in html

    def test_empty_state_shown_when_no_projects(self, env: jinja2.Environment):
        tmpl = env.get_template("projects.html")
        html = tmpl.render(request=_request("/"), user=_user(), projects=[])
        assert "empty-state" in html
        assert "create-project" in html

    def test_sparkline_rendered(self, env: jinja2.Environment):
        tmpl = env.get_template("projects.html")
        html = tmpl.render(
            request=_request("/"),
            user=_user(),
            projects=[_project_summary(sparkline=[0.6, 0.8, 0.9])],
        )
        assert "sparkline" in html

    def test_xss_in_project_name_escaped(self, env: jinja2.Environment):
        tmpl = env.get_template("projects.html")
        html = tmpl.render(
            request=_request("/"),
            user=_user(),
            projects=[_project_summary(name="<script>alert(1)</script>")],
        )
        assert "<script>" not in html  # raw tag removed by autoescape
        assert "&lt;script&gt;" in html  # escaped entity present


# ── project.html ──────────────────────────────────────────────────────────────


class TestProjectTemplate:
    def _render(
        self,
        env: jinja2.Environment,
        overview: Any | None = None,
        trend_svg: str = '<svg><polyline points="0,0 10,10"/></svg>',
        gates: list | None = None,
    ) -> str:
        tmpl = env.get_template("project.html")
        ov = overview or _overview()
        ctx: dict[str, Any] = {
            "request": _request(f"/projects/{ov.slug}"),
            "user": _user(),
            "overview": ov,
            "trend_svg": trend_svg,
        }
        if gates is not None:
            ctx["gates"] = gates
        return tmpl.render(**ctx)

    def test_renders_project_name(self, env: jinja2.Environment):
        html = self._render(env)
        assert "Luna Support" in html

    def test_renders_stat_tiles(self, env: jinja2.Environment):
        html = self._render(env)
        assert "stat-tile" in html or "stat-card" in html
        # latest pass rate visible
        assert "87" in html

    def test_trend_svg_rendered_safe(self, env: jinja2.Environment):
        svg = '<svg><polyline points="0,0 10,5"/></svg>'
        html = self._render(env, trend_svg=svg)
        # svg rendered as raw markup (via |safe), not escaped
        assert "<svg>" in html
        assert "<polyline" in html

    def test_run_rows_in_table(self, env: jinja2.Environment):
        ov = _overview(runs=[_run_row(label="v1.2.0", pass_rate=0.9)])
        html = self._render(env, overview=ov)
        assert "v1.2.0" in html
        assert "score-chip" in html

    def test_run_links_to_run_detail(self, env: jinja2.Environment):
        ov = _overview(runs=[_run_row(run_id="abc123")])
        html = self._render(env, overview=ov)
        assert "/projects/luna-support/runs/abc123" in html

    def test_xss_in_run_label_escaped(self, env: jinja2.Environment):
        bad_label = "<script>alert(1)</script>"
        ov = _overview(runs=[_run_row(label=bad_label)])
        html = self._render(env, overview=ov)
        assert "<script>" not in html  # raw tag removed by autoescape
        assert "&lt;script&gt;" in html  # escaped entity present

    def test_gates_summary_shown_when_gates_provided(self, env: jinja2.Environment) -> None:
        gate = SimpleNamespace(
            id="g1",
            name="pass rate check",
            metric="pass_rate",
            scorer=None,
            comparison="gte",
            threshold=0.9,
            enabled=True,
        )
        html = self._render(env, gates=[gate])
        assert "pass rate check" in html
        assert "Quality Gates" in html
        assert "scorer-pill" in html

    def test_gates_summary_absent_when_no_gates_key(self, env: jinja2.Environment) -> None:
        # When the route does not pass `gates`, the section must be silently absent.
        html = self._render(env, gates=None)
        assert "Quality Gates" not in html


# ── run.html ──────────────────────────────────────────────────────────────────


class TestRunTemplate:
    def _render(self, env: jinja2.Environment, detail: Any | None = None) -> str:
        tmpl = env.get_template("run.html")
        d = detail or _run_detail()
        return tmpl.render(
            request=_request(f"/projects/{d.project_slug}/runs/{d.run.run_id}"),
            user=_user(),
            detail=d,
        )

    def test_renders_run_label(self, env: jinja2.Environment):
        html = self._render(env)
        assert "v1.0.0" in html

    def test_renders_scorer_pill(self, env: jinja2.Environment):
        html = self._render(env)
        assert "scorer-pill" in html
        assert "accuracy" in html

    def test_distribution_bars_rendered_safe(self, env: jinja2.Environment):
        html = self._render(env)
        # bars_html is injected via |safe; the dist-bars class must appear
        assert "dist-bars" in html

    def test_case_expandable_details(self, env: jinja2.Environment):
        html = self._render(env)
        assert "<details" in html
        assert "case-details" in html

    def test_score_chip_in_case(self, env: jinja2.Environment):
        html = self._render(env)
        assert "score-chip" in html
        assert "pass" in html

    def test_span_row_rendered(self, env: jinja2.Environment):
        html = self._render(env)
        assert "span-row" in html
        assert "llm" in html

    def test_xss_in_run_label_escaped(self, env: jinja2.Environment):
        bad_label = "<script>alert(1)</script>"
        detail = _run_detail(label=bad_label)
        html = self._render(env, detail=detail)
        assert "<script>" not in html  # raw tag removed by autoescape
        assert "&lt;script&gt;" in html  # escaped entity present

    def test_xss_in_case_output_escaped(self, env: jinja2.Environment):
        tmpl = env.get_template("run.html")
        case = SimpleNamespace(
            case_id="c1",
            input="prompt",
            output="<img src=x onerror=alert(1)>",
            scores=[_score_view()],
            spans=[],
        )
        detail = SimpleNamespace(
            run=_run_row(),
            project_slug="luna-support",
            scorer_stats=[_scorer_stat()],
            cases=[case],
        )
        html = tmpl.render(request=_request(), user=_user(), detail=detail)
        assert "<img" not in html  # raw tag removed by autoescape
        assert "&lt;img" in html  # escaped entity present

    def test_breadcrumb_links(self, env: jinja2.Environment):
        html = self._render(env)
        assert "/projects/luna-support" in html


class TestRunGateChips:
    """Run page renders per-gate pass/fail chips from detail.gate_results."""

    def _gate_result(
        self,
        name: str = "pass rate check",
        metric: str = "pass_rate",
        passed: bool = True,
        actual: float | None = 0.92,
        threshold: float = 0.90,
    ) -> SimpleNamespace:
        return SimpleNamespace(
            name=name, metric=metric, passed=passed, actual=actual, threshold=threshold
        )

    def _render(self, env: jinja2.Environment, gate_results: list) -> str:
        tmpl = env.get_template("run.html")
        return tmpl.render(
            request=SimpleNamespace(url=SimpleNamespace(path="/projects/luna-support/runs/abc")),
            user=SimpleNamespace(email="alice@example.com"),
            detail=_run_detail(gate_results=gate_results),
        )

    def test_passed_gate_renders_pass_chip(self, env: jinja2.Environment) -> None:
        gate = self._gate_result(name="pass rate check", passed=True)
        html = self._render(env, gate_results=[gate])
        assert "pass rate check" in html
        assert "score-chip pass" in html

    def test_failed_gate_renders_fail_chip(self, env: jinja2.Environment) -> None:
        gate = self._gate_result(name="accuracy gate", passed=False, actual=0.78)
        html = self._render(env, gate_results=[gate])
        assert "accuracy gate" in html
        assert "score-chip fail" in html

    def test_gate_chip_shows_actual_percentage(self, env: jinja2.Environment) -> None:
        html = self._render(env, gate_results=[self._gate_result(actual=0.924, passed=True)])
        assert "92" in html  # (0.924 * 100)|round(1) = 92.4

    def test_gate_chip_shows_threshold_on_failure(self, env: jinja2.Environment) -> None:
        gate = self._gate_result(passed=False, actual=0.78, threshold=0.90)
        html = self._render(env, gate_results=[gate])
        # Failed chip must show the threshold to let the user know how far off they are
        assert "90" in html  # (0.90 * 100)|round(1) = 90.0

    def test_no_gate_results_section_absent(self, env: jinja2.Environment) -> None:
        html = self._render(env, gate_results=[])
        # With an empty list the section label "Gates" must not appear
        # (avoids a floating label with no chips)
        assert ">Gates<" not in html

    def test_none_actual_chip_omits_percentage(self, env: jinja2.Environment) -> None:
        html = self._render(env, gate_results=[self._gate_result(actual=None, passed=True)])
        # Gate name still appears; no division-by-zero or crash
        assert "pass rate check" in html

    def test_multiple_gate_chips_all_rendered(self, env: jinja2.Environment) -> None:
        results = [
            self._gate_result(name="gate-alpha", passed=True),
            self._gate_result(name="gate-beta", passed=False),
        ]
        html = self._render(env, gate_results=results)
        assert "gate-alpha" in html
        assert "gate-beta" in html
        assert "score-chip pass" in html
        assert "score-chip fail" in html
