from __future__ import annotations

import os
import sqlite3
import time
from contextlib import closing
from typing import Protocol, runtime_checkable

from tokensurf.core.models import Trace


@runtime_checkable
class Sink(Protocol):
    def write(self, trace: Trace) -> None: ...


class SQLiteSink:
    def __init__(self, path: str | os.PathLike) -> None:
        self.path = os.fspath(path)
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS traces ("
                "id TEXT PRIMARY KEY, name TEXT, json TEXT, created REAL)"
            )

    def write(self, trace: Trace) -> None:
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute(
                "INSERT OR REPLACE INTO traces (id, name, json, created) VALUES (?, ?, ?, ?)",
                (trace.id, trace.name, trace.model_dump_json(), time.time()),
            )


class JSONLSink:
    def __init__(self, path: str | os.PathLike) -> None:
        self.path = os.fspath(path)

    def write(self, trace: Trace) -> None:
        line = trace.model_dump_json()
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
