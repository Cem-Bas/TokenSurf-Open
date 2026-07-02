"""Dataset loaders for the eval harness."""

from __future__ import annotations

import csv
import json
import os
from collections.abc import Iterator
from pathlib import Path

from tokensurf.core.ids import new_id
from tokensurf.core.models import Case


class Dataset:
    """An ordered collection of eval Cases."""

    def __init__(self, cases: list[Case] | None = None) -> None:
        self.cases: list[Case] = list(cases or [])

    @classmethod
    def from_list(cls, rows: list[dict]) -> Dataset:
        cases: list[Case] = []
        for row in rows:
            raw_id = row.get("id")
            cases.append(
                Case(
                    id=str(raw_id) if raw_id is not None else new_id(),
                    input=row.get("input"),
                    expected=row.get("expected"),
                    metadata=row.get("metadata") or {},
                )
            )
        return cls(cases=cases)

    @classmethod
    def from_jsonl(cls, path: str | os.PathLike[str]) -> Dataset:
        rows: list[dict] = []
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            rows.append(json.loads(stripped))
        return cls.from_list(rows)

    @classmethod
    def from_csv(cls, path: str | os.PathLike[str]) -> Dataset:
        with Path(path).open(encoding="utf-8", newline="") as fh:
            rows = [dict(row) for row in csv.DictReader(fh)]
        return cls.from_list(rows)

    def __iter__(self) -> Iterator[Case]:
        return iter(self.cases)

    def __len__(self) -> int:
        return len(self.cases)
