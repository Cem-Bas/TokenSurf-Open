from __future__ import annotations

import json
import re
from typing import Any

from tokensurf.core.models import Case, ScoreResult, Trace
from tokensurf.scorers.base import Scorer, register


def _get_field(trace: Trace, case: Case | None, field: str) -> Any:
    return getattr(trace, field, None)


def _json_type_ok(value: Any, json_type: str) -> bool:
    mapping: dict[str, type | tuple[type, ...]] = {
        "object": dict,
        "array": list,
        "string": str,
        "number": (int, float),
        "integer": int,
        "boolean": bool,
        "null": type(None),
    }
    expected = mapping.get(json_type)
    if expected is None:
        return True
    if json_type in ("integer", "number") and isinstance(value, bool):
        return False
    return isinstance(value, expected)


def _validate_json_schema(instance: Any, schema: dict) -> tuple[bool, str | None]:
    expected_type = schema.get("type")
    if expected_type is not None and not _json_type_ok(instance, expected_type):
        return False, f"expected type {expected_type!r}, got {type(instance).__name__}"
    if isinstance(instance, dict):
        for key in schema.get("required", []):
            if key not in instance:
                return False, f"missing required property {key!r}"
        for key, subschema in schema.get("properties", {}).items():
            if key in instance and isinstance(subschema, dict):
                ok, err = _validate_json_schema(instance[key], subschema)
                if not ok:
                    return False, f"{key}: {err}"
    if isinstance(instance, list):
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for idx, item in enumerate(instance):
                ok, err = _validate_json_schema(item, item_schema)
                if not ok:
                    return False, f"[{idx}]: {err}"
    return True, None


@register
class ExactMatch(Scorer):
    name = "ExactMatch"

    def __init__(self, expected: str | None = None, field: str = "output"):
        self.expected = expected
        self.field = field

    def score(self, *, trace: Trace, case: Case | None = None) -> ScoreResult:
        actual = _get_field(trace, case, self.field)
        expected = self.expected
        if expected is None and case is not None:
            expected = case.expected
        match = str(actual) == str(expected)
        return ScoreResult(
            scorer=self.name,
            value=1.0 if match else 0.0,
            passed=match,
            explanation=None if match else f"{actual!r} != {expected!r}",
        )


@register
class Contains(Scorer):
    name = "Contains"

    def __init__(self, substring: str, field: str = "output", case_sensitive: bool = False):
        self.substring = substring
        self.field = field
        self.case_sensitive = case_sensitive

    def score(self, *, trace: Trace, case: Case | None = None) -> ScoreResult:
        hay = str(_get_field(trace, case, self.field) or "")
        needle = self.substring
        if not self.case_sensitive:
            hay = hay.lower()
            needle = needle.lower()
        match = needle in hay
        return ScoreResult(scorer=self.name, value=1.0 if match else 0.0, passed=match)


@register
class Regex(Scorer):
    name = "Regex"

    def __init__(self, pattern: str, field: str = "output"):
        self.pattern = re.compile(pattern)
        self.field = field

    def score(self, *, trace: Trace, case: Case | None = None) -> ScoreResult:
        actual = str(_get_field(trace, case, self.field) or "")
        match = self.pattern.search(actual) is not None
        return ScoreResult(scorer=self.name, value=1.0 if match else 0.0, passed=match)


@register
class JSONSchemaValid(Scorer):
    name = "JSONSchemaValid"

    def __init__(self, schema: dict, field: str = "output"):
        self.schema = schema
        self.field = field

    def score(self, *, trace: Trace, case: Case | None = None) -> ScoreResult:
        value = _get_field(trace, case, self.field)
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError as exc:
                return ScoreResult(
                    scorer=self.name, value=0.0, passed=False, explanation=f"invalid JSON: {exc}"
                )
        ok, err = _validate_json_schema(value, self.schema)
        return ScoreResult(scorer=self.name, value=1.0 if ok else 0.0, passed=ok, explanation=err)


@register
class LatencyUnder(Scorer):
    name = "LatencyUnder"

    def __init__(self, seconds: float):
        self.seconds = seconds

    def score(self, *, trace: Trace, case: Case | None = None) -> ScoreResult:
        duration = trace.duration
        if duration is None:
            return ScoreResult(scorer=self.name, value=None, passed=None, explanation="no duration")
        ok = duration < self.seconds
        return ScoreResult(scorer=self.name, value=1.0 if ok else 0.0, passed=ok, latency=duration)


@register
class CostUnder(Scorer):
    name = "CostUnder"

    def __init__(self, usd: float):
        self.usd = usd

    def score(self, *, trace: Trace, case: Case | None = None) -> ScoreResult:
        total = sum(float(span.attributes.get("cost", 0) or 0) for span in trace.spans)
        ok = total < self.usd
        return ScoreResult(scorer=self.name, value=1.0 if ok else 0.0, passed=ok, cost=total)


@register
class ToolCalled(Scorer):
    name = "ToolCalled"

    def __init__(self, name: str):
        self.tool_name = name

    def score(self, *, trace: Trace, case: Case | None = None) -> ScoreResult:
        called = any(s.type == "tool" and s.name == self.tool_name for s in trace.spans)
        return ScoreResult(scorer=self.name, value=1.0 if called else 0.0, passed=called)
