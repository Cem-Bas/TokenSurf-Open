from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_license_is_apache_2_0():
    text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "Apache License" in text
    assert "Version 2.0" in text


def test_gitignore_blocks_secrets_and_local_artifacts():
    text = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for pattern in [".env", ".venv", "__pycache__", "*.sqlite", "results.jsonl"]:
        assert pattern in text, f".gitignore must ignore {pattern}"


def test_env_example_has_placeholders_only():
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    for key in [
        "OPENAI_API_KEY=",
        "ANTHROPIC_API_KEY=",
        "GEMINI_API_KEY=",
        "TOKENSURF_JUDGE_MODEL=gpt-4o-mini",
    ]:
        assert key in text, f".env.example must declare {key}"
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        assert value in ("", "gpt-4o-mini"), f"{key} must be a placeholder, got {value!r}"
        assert "sk-" not in value


def test_readme_is_gate_safe():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "Apache-2.0" in text
    assert "launching soon" in text.lower()


def test_internal_engineering_docs_not_tracked():
    """SDD plans/specs and design notes are internal — they must never ship in the public repo.

    This guards the pre-publish audit's one blocking finding: docs/superpowers/ and
    docs/design/ leaked business strategy, the private cloud repo path, and the security
    gate. They belong in the private planning repo only.
    """
    import subprocess

    result = subprocess.run(
        ["git", "ls-files", "docs/superpowers", "docs/design"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    tracked = [line for line in result.stdout.splitlines() if line.strip()]
    assert not tracked, f"internal engineering docs must not be tracked: {tracked[:5]}"
