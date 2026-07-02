"""Identifier generation for traces, spans, and cases."""

from __future__ import annotations

import uuid


def new_id() -> str:
    """Return a fresh unique identifier (uuid4 hex, 32 lowercase chars).

    Thin wrapper around ``uuid.uuid4`` so tests can monkeypatch
    ``tokensurf.core.ids.uuid.uuid4`` for deterministic output.
    """
    return uuid.uuid4().hex
