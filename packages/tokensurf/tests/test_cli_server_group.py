"""Tests for the dynamic `tokensurf server` sub-app attachment.

This monorepo dev environment always has both `tokensurf` and `tokensurf-server`
installed (uv workspace sync), so `server` must always appear here. The
ModuleNotFoundError guard itself (no `tokensurf_server` installed -> no `server`
group) is exercised structurally by inspecting the guard's source, since building
a second venv without tokensurf-server is out of scope for this test suite.
"""

from __future__ import annotations

import inspect

from typer.testing import CliRunner

from tokensurf import cli
from tokensurf.cli import app

runner = CliRunner()


def test_server_group_appears_when_tokensurf_server_installed() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0, result.output
    assert "server" in result.output


def test_server_subcommands_are_reachable() -> None:
    result = runner.invoke(app, ["server", "--help"])
    assert result.exit_code == 0, result.output
    for cmd in ("migrate", "create-user", "create-project", "create-key"):
        assert cmd in result.output


def test_attach_guard_only_swallows_module_not_found_error() -> None:
    source = inspect.getsource(cli)
    assert "except ModuleNotFoundError:" in source
    # Guards against a future edit widening this to a bare `except Exception:`,
    # which would silently hide real bugs in tokensurf_server.admin_cli.
    assert "except Exception:" not in source
