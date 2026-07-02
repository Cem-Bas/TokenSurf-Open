"""Jinja render tests for the Judge Keys section of settings.html (Slice 2d)."""

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


def _request(path: str = "/settings/luna-support") -> SimpleNamespace:
    return SimpleNamespace(url=SimpleNamespace(path=path))


def _user() -> SimpleNamespace:
    return SimpleNamespace(email="alice@example.com")


def _secret_view(provider: str = "openai", has_value: bool = True) -> SimpleNamespace:
    return SimpleNamespace(provider=provider, has_value=has_value)


class TestJudgeKeysSection:
    """The real Judge Keys section replaces the 'soon' tile."""

    def _render(
        self,
        env: jinja2.Environment,
        secrets: list | None = None,
        csrf_token: str = "test-csrf-token",
        slug: str = "luna-support",
    ) -> str:
        tmpl = env.get_template("settings.html")
        return tmpl.render(
            request=_request(f"/settings/{slug}"),
            user=_user(),
            slug=slug,
            name="Luna Support",
            gates=[],
            channels=[],
            secrets=secrets if secrets is not None else [],
            csrf_token=csrf_token,
        )

    def test_judge_keys_heading_present(self, env: jinja2.Environment) -> None:
        html = self._render(env)
        assert "Judge Keys" in html

    def test_badge_soon_absent(self, env: jinja2.Environment) -> None:
        html = self._render(env)
        assert "badge-soon" not in html

    def test_add_key_form_posts_to_correct_action(self, env: jinja2.Environment) -> None:
        html = self._render(env)
        assert 'action="/settings/luna-support/secrets"' in html

    def test_add_key_form_has_hidden_csrf_field(self, env: jinja2.Environment) -> None:
        html = self._render(env)
        assert 'name="csrf_token"' in html
        assert 'value="test-csrf-token"' in html

    def test_secret_input_is_password_type_with_name_secret(self, env: jinja2.Environment) -> None:
        html = self._render(env)
        assert 'type="password"' in html
        assert 'name="secret"' in html

    def test_provider_select_has_known_options(self, env: jinja2.Environment) -> None:
        html = self._render(env)
        assert 'name="provider"' in html
        for provider in ("openai", "anthropic", "gemini"):
            assert f'value="{provider}"' in html

    def test_configured_provider_name_rendered(self, env: jinja2.Environment) -> None:
        html = self._render(env, secrets=[_secret_view(provider="anthropic")])
        assert "anthropic" in html

    def test_has_value_shows_set_indicator(self, env: jinja2.Environment) -> None:
        html = self._render(env, secrets=[_secret_view(has_value=True)])
        assert "•••• set" in html

    def test_no_value_shows_dash_not_set_indicator(self, env: jinja2.Environment) -> None:
        html = self._render(env, secrets=[_secret_view(has_value=False)])
        assert "•••• set" not in html

    def test_delete_form_posts_to_provider_delete_action(self, env: jinja2.Environment) -> None:
        html = self._render(env, secrets=[_secret_view(provider="openai")])
        assert 'action="/settings/luna-support/secrets/openai/delete"' in html

    def test_delete_form_has_csrf_field(self, env: jinja2.Environment) -> None:
        html = self._render(env, secrets=[_secret_view(provider="openai")])
        # csrf_token appears in both the add form and the delete mini-form
        assert html.count('name="csrf_token"') >= 2

    def test_provider_xss_escaped(self, env: jinja2.Environment) -> None:
        bad_provider = "<script>alert(1)</script>"
        html = self._render(env, secrets=[_secret_view(provider=bad_provider)])
        # autoescape ON: the raw tag must NOT appear; the escaped entity MUST appear
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_empty_secrets_shows_empty_state(self, env: jinja2.Environment) -> None:
        html = self._render(env, secrets=[])
        assert "No judge keys" in html

    def test_key_enc_never_in_html(self, env: jinja2.Environment) -> None:
        """has_value=True must show only the indicator; key_enc attribute not in output."""
        html = self._render(env, secrets=[_secret_view(provider="openai", has_value=True)])
        assert "key_enc" not in html
