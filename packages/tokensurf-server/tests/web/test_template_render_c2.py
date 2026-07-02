"""Jinja render tests for base.html and login.html.

These tests load templates directly via jinja2 (no HTTP) and assert
key strings are present and that autoescape prevents injection.
"""

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


def _fake_request(path: str = "/") -> SimpleNamespace:
    return SimpleNamespace(
        url=SimpleNamespace(path=path),
        state=SimpleNamespace(csrf_token="csrf-test-token"),
    )


class TestBase:
    def test_base_renders_with_user(self, env: jinja2.Environment):
        tmpl = env.get_template("base.html")
        user = SimpleNamespace(email="alice@example.com")
        html = tmpl.render(request=_fake_request(), user=user)
        assert "TokenSurf" in html
        assert "alice@example.com" in html
        assert "/static/app.css" in html
        # Google Fonts CSS2 API requires +-encoded family names to actually load.
        assert "JetBrains+Mono" in html

    def test_base_renders_without_user(self, env: jinja2.Environment):
        tmpl = env.get_template("base.html")
        html = tmpl.render(request=_fake_request(), user=None)
        assert "TokenSurf" in html
        # no user email leaks into page
        assert "@example.com" not in html

    def test_base_content_block_present(self, env: jinja2.Environment):
        # base.html must define a block named 'content'
        assert env.loader is not None
        src = env.loader.get_source(env, "base.html")[0]
        assert "block content" in src


class TestLogin:
    def test_login_renders_form(self, env: jinja2.Environment):
        tmpl = env.get_template("login.html")
        html = tmpl.render(request=_fake_request("/login"), error=None)
        assert 'action="/login"' in html
        assert 'name="email"' in html
        assert 'name="password"' in html
        assert "TokenSurf" in html

    def test_login_shows_error(self, env: jinja2.Environment):
        tmpl = env.get_template("login.html")
        html = tmpl.render(request=_fake_request("/login"), error="Invalid email or password")
        assert "Invalid email or password" in html
        assert "error-msg" in html

    def test_login_no_error_no_error_block(self, env: jinja2.Environment):
        tmpl = env.get_template("login.html")
        html = tmpl.render(request=_fake_request("/login"), error=None)
        assert "error-msg" not in html

    def test_login_escapes_xss_in_error(self, env: jinja2.Environment):
        """autoescape must prevent raw HTML in the error message."""
        tmpl = env.get_template("login.html")
        html = tmpl.render(
            request=_fake_request("/login"),
            error="<script>alert(1)</script>",
        )
        assert "<script>" not in html  # raw tag removed by autoescape
        assert "&lt;script&gt;" in html  # escaped entity present
