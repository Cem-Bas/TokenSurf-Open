"""Smoke-check app.css contains required tokens and classes; drops third-party config."""

from pathlib import Path

CSS = Path(__file__).parent.parent.parent / "src/tokensurf_server/web/static/app.css"


def _css() -> str:
    return CSS.read_text()


def test_css_file_exists():
    assert CSS.exists(), "app.css not found"


def test_root_tokens():
    css = _css()
    assert "--accent: #4f6df5" in css
    assert "--green: #10a37f" in css
    assert "--red: #e53e3e" in css
    assert "--orange: #e8590c" in css
    assert "--card-bg: #fff" in css
    assert "--cream: #eee9de" in css
    assert "--dark: #1a1f3a" in css


def test_fonts_imported():
    css = _css()
    assert "Inter" in css
    assert "DM Sans" in css
    assert "JetBrains Mono" in css


def test_score_chip_classes():
    css = _css()
    assert ".score-chip" in css
    assert ".score-chip.pass" in css
    assert ".score-chip.fail" in css
    assert ".score-chip.errored" in css


def test_scorer_pill():
    css = _css()
    assert ".scorer-pill" in css


def test_stat_tile():
    css = _css()
    assert ".stat-card" in css
    assert ".stat-tile" in css


def test_distribution_bars():
    css = _css()
    assert ".dist-bars" in css
    assert ".bar-poor" in css
    assert ".bar-fair" in css
    assert ".bar-good" in css
    assert ".bar-excellent" in css


def test_no_firebase():
    css = _css()
    assert "firebase" not in css.lower()
    assert "firestore" not in css.lower()
    assert "billing" not in css.lower()
    assert "savings" not in css.lower()
