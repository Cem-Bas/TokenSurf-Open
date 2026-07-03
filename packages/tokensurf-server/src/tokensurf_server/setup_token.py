"""First-run admin setup token: a Jenkins-`initialAdminPassword`-style file.

Generated once (the first time no dashboard user exists yet) and required by
GET/POST /setup, so an operator with filesystem/log access to the running server
proves they're the one completing setup — not whoever reaches the port first.
"""

from __future__ import annotations

import os
from pathlib import Path

from tokensurf.core.ids import new_id


def get_or_create_token(path: Path) -> str:
    """Return the setup token at `path`, creating it (mode 0600) if it doesn't exist yet."""
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    token = new_id()
    path.write_text(token + "\n", encoding="utf-8")
    os.chmod(path, 0o600)
    return token
