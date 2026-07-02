from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class IngestRunRequest(BaseModel):
    label: str | None = None
    report: dict
    metadata: dict | None = None


class GateResultOut(BaseModel):
    name: str
    metric: str
    passed: bool
    actual: float | None
    threshold: float


class RunSummary(BaseModel):
    run_id: str
    project: str
    status: str
    n_cases: int
    pass_rate: float
    mean_score: float | None
    error_count: int
    created_at: datetime
    gate_results: list[GateResultOut] = []


class ConfigResponse(BaseModel):
    judge_keys: dict[str, str] = {}
