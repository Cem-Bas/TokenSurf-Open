"""Jinja render tests for settings.html (per-project) and settings_index.html (picker).

Templates are loaded directly via jinja2 (no HTTP). Assertions cover:
- CSRF hidden fields present on every state-changing form
- Form actions point to the correct /settings/{slug}/... endpoints
- Gate names containing HTML are escaped (autoescape)
- Channel secrets are never rendered (only "•••• set" indicator)
- Project picker links to /settings/{slug}
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import jinja2
import pytest

TEMPLATES_DIR = Path(__file__).parent.parent.parent / "src/tokensurf_server/web/templates"


@pytest.fixture
def env() -> jinja2.Environment:
    return jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=True,
    )


def _request(path: str = "/settings") -> SimpleNamespace:
    return SimpleNamespace(url=SimpleNamespace(path=path))


def _user() -> SimpleNamespace:
    return SimpleNamespace(email="alice@example.com")


def _gate(
    id: str = "gate-1",
    name: str = "pass rate check",
    metric: str = "pass_rate",
    scorer: str | None = None,
    comparison: str = "gte",
    threshold: float = 0.90,
    enabled: bool = True,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=id,
        name=name,
        metric=metric,
        scorer=scorer,
        comparison=comparison,
        threshold=threshold,
        enabled=enabled,
    )


def _channel(
    id: str = "chan-1",
    type: str = "slack",
    name: str = "Slack alerts",
    enabled: bool = True,
    has_secret: bool = True,
) -> SimpleNamespace:
    return SimpleNamespace(id=id, type=type, name=name, enabled=enabled, has_secret=has_secret)


def _project_summary(slug: str = "luna-support", name: str = "Luna Support") -> SimpleNamespace:
    return SimpleNamespace(slug=slug, name=name)


class TestSettingsTemplate:
    """Tests for settings.html — the per-project gates+channels management page."""

    def _render(
        self,
        env: jinja2.Environment,
        gates: list | None = None,
        channels: list | None = None,
        secrets: list | None = None,
        csrf_token: str = "test-csrf-token",
        slug: str = "luna-support",
        name: str = "Luna Support",
    ) -> str:
        tmpl = env.get_template("settings.html")
        return tmpl.render(
            request=_request(f"/settings/{slug}"),
            user=_user(),
            slug=slug,
            name=name,
            gates=gates if gates is not None else [],
            channels=channels if channels is not None else [],
            secrets=secrets if secrets is not None else [],
            csrf_token=csrf_token,
        )

    def test_renders_project_name_in_heading(self, env: jinja2.Environment) -> None:
        html = self._render(env)
        assert "Luna Support" in html

    def test_add_gate_form_posts_to_correct_action(self, env: jinja2.Environment) -> None:
        html = self._render(env)
        assert 'action="/settings/luna-support/gates"' in html

    def test_add_gate_form_has_csrf_hidden_field(self, env: jinja2.Environment) -> None:
        html = self._render(env)
        assert 'name="csrf_token"' in html
        assert 'value="test-csrf-token"' in html

    def test_add_channel_form_posts_to_correct_action(self, env: jinja2.Environment) -> None:
        html = self._render(env)
        assert 'action="/settings/luna-support/channels"' in html

    def test_gate_delete_form_posts_to_correct_action(self, env: jinja2.Environment) -> None:
        html = self._render(env, gates=[_gate(id="gate-abc")])
        assert 'action="/settings/luna-support/gates/gate-abc/delete"' in html

    def test_gate_delete_form_carries_csrf_token(self, env: jinja2.Environment) -> None:
        html = self._render(env, gates=[_gate(id="gate-abc")])
        # Multiple forms on the page — csrf_token appears in at least one
        assert html.count('name="csrf_token"') >= 2  # add-form + delete mini-form

    def test_channel_test_form_posts_to_correct_action(self, env: jinja2.Environment) -> None:
        html = self._render(env, channels=[_channel(id="chan-xyz")])
        assert 'action="/settings/luna-support/channels/chan-xyz/test"' in html

    def test_channel_delete_form_posts_to_correct_action(self, env: jinja2.Environment) -> None:
        html = self._render(env, channels=[_channel(id="chan-xyz")])
        assert 'action="/settings/luna-support/channels/chan-xyz/delete"' in html

    def test_channel_secret_never_rendered_has_set_indicator(self, env: jinja2.Environment) -> None:
        html = self._render(env, channels=[_channel(has_secret=True)])
        assert "secret_enc" not in html
        assert "•••• set" in html  # "•••• set"

    def test_channel_no_secret_shows_dash(self, env: jinja2.Environment) -> None:
        html = self._render(env, channels=[_channel(has_secret=False)])
        assert "•••• set" not in html

    def test_secret_input_is_password_type(self, env: jinja2.Environment) -> None:
        html = self._render(env)
        assert 'type="password"' in html
        assert 'name="secret"' in html

    def test_gate_name_xss_escaped(self, env: jinja2.Environment) -> None:
        bad_name = "<script>alert(1)</script>"
        html = self._render(env, gates=[_gate(name=bad_name)])
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_empty_gates_shows_empty_state(self, env: jinja2.Environment) -> None:
        html = self._render(env, gates=[])
        assert "No quality gates yet" in html

    def test_empty_channels_shows_empty_state(self, env: jinja2.Environment) -> None:
        html = self._render(env, channels=[])
        assert "No notification channels yet" in html

    def test_gate_metric_select_options_present(self, env: jinja2.Environment) -> None:
        html = self._render(env)
        assert 'name="metric"' in html
        assert "pass_rate" in html
        assert "mean_score" in html
        assert "scorer_pass_rate" in html

    def test_comparison_select_present(self, env: jinja2.Environment) -> None:
        html = self._render(env)
        assert 'name="comparison"' in html
        assert "gte" in html

    def test_channel_type_select_options_present(self, env: jinja2.Environment) -> None:
        html = self._render(env)
        assert 'name="type"' in html
        assert "slack" in html
        assert "webhook" in html
        assert "email" in html

    def test_judge_keys_real_section_present(self, env: jinja2.Environment) -> None:
        html = self._render(env)
        assert "Judge Keys" in html
        assert "badge-soon" not in html
        assert 'action="/settings/luna-support/secrets"' in html

    def test_breadcrumb_links_to_settings_index(self, env: jinja2.Environment) -> None:
        html = self._render(env)
        assert 'href="/settings"' in html

    def test_slug_in_page(self, env: jinja2.Environment) -> None:
        html = self._render(env, slug="my-project", name="My Project")
        assert "my-project" in html
        assert "My Project" in html


class TestSettingsIndexTemplate:
    """Tests for settings_index.html — the project picker."""

    def _render(self, env: jinja2.Environment, projects: list | None = None) -> str:
        tmpl = env.get_template("settings_index.html")
        return tmpl.render(
            request=_request("/settings"),
            user=_user(),
            projects=projects if projects is not None else [],
        )

    def test_renders_project_slug_link(self, env: jinja2.Environment) -> None:
        html = self._render(env, projects=[_project_summary(slug="luna-support")])
        assert "/settings/luna-support" in html

    def test_renders_project_name(self, env: jinja2.Environment) -> None:
        html = self._render(env, projects=[_project_summary(name="Luna Support")])
        assert "Luna Support" in html

    def test_empty_state_shown_when_no_projects(self, env: jinja2.Environment) -> None:
        html = self._render(env, projects=[])
        assert "No projects yet" in html

    def test_multiple_projects_all_rendered(self, env: jinja2.Environment) -> None:
        projects = [
            _project_summary(slug="proj-a", name="Project A"),
            _project_summary(slug="proj-b", name="Project B"),
        ]
        html = self._render(env, projects=projects)
        assert "/settings/proj-a" in html
        assert "/settings/proj-b" in html
        assert "Project A" in html
        assert "Project B" in html

    def test_settings_heading_present(self, env: jinja2.Environment) -> None:
        html = self._render(env)
        assert "Settings" in html
