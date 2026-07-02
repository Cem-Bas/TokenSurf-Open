from __future__ import annotations

import re
import time
from typing import Protocol, cast, runtime_checkable

from pydantic import BaseModel

from tokensurf.core.models import Case, ScoreResult, Trace
from tokensurf.scorers.base import Scorer, register


class LLMResponse(BaseModel):
    text: str
    model: str
    cost: float | None = None
    latency: float | None = None


@runtime_checkable
class LLMClient(Protocol):
    def complete(self, *, model: str, messages: list[dict[str, str]]) -> LLMResponse: ...


class LiteLLMClient:
    def __init__(self, *, api_base: str | None = None, api_key: str | None = None):
        self.api_base = api_base
        self.api_key = api_key

    def complete(self, *, model: str, messages: list[dict[str, str]]) -> LLMResponse:
        import litellm
        from litellm import ModelResponse

        start = time.perf_counter()
        resp = litellm.completion(
            model=model, messages=messages, api_base=self.api_base, api_key=self.api_key
        )
        latency = time.perf_counter() - start
        # litellm.completion is typed ModelResponse | CustomStreamWrapper; we never
        # stream, so treat the reply as a (non-streaming) ModelResponse before reading
        # .choices. cast (not isinstance) so duck-typed offline test doubles still work.
        completion = cast(ModelResponse, resp)
        text = completion.choices[0].message.content or ""
        cost = getattr(resp, "_hidden_params", {}).get("response_cost")
        return LLMResponse(text=text, model=model, cost=cost, latency=latency)


_RUBRIC_PROMPT = (
    "You are an expert evaluator. Rate the AI agent's response on a 1-10 integer scale\n"
    "considering accuracy, completeness, relevance, and helpfulness,"
    " where 1 is unusable and 10 is perfect.\n"
    "\n"
    "Criteria focus: {criteria}\n"
    "\n"
    "[TASK INPUT]\n"
    "{input}\n"
    "\n"
    "[AGENT OUTPUT]\n"
    "{output}\n"
    "\n"
    "Respond with ONLY a single integer from 1 to 10."
)


@register
class LLMJudge(Scorer):
    name = "LLMJudge"

    def __init__(
        self,
        criteria: str = "overall quality",
        model: str = "gpt-4o-mini",
        client: LLMClient | None = None,
        threshold: float = 0.7,
        prompt: str | None = None,
        max_retries: int = 2,
    ):
        self.criteria = criteria
        self.model = model
        self.client = client
        self.threshold = threshold
        self.prompt = prompt
        self.max_retries = max_retries
        self._backoff_base = 0.5

    def _build_messages(self, trace: Trace) -> list[dict[str, str]]:
        template = self.prompt or _RUBRIC_PROMPT
        content = template.format(criteria=self.criteria, input=trace.input, output=trace.output)
        return [{"role": "user", "content": content}]

    @staticmethod
    def _parse_score(text: str) -> int:
        match = re.search(r"\b(10|[1-9])\b", text)
        if match is None:
            raise ValueError(f"no 1-10 integer found in judge reply: {text!r}")
        return int(match.group(1))

    def score(self, *, trace: Trace, case: Case | None = None) -> ScoreResult:
        if self.client is None:
            return ScoreResult.errored(self.name, "no LLMClient configured")
        last_error = ""
        for attempt in range(self.max_retries + 1):
            try:
                resp = self.client.complete(model=self.model, messages=self._build_messages(trace))
                n = self._parse_score(resp.text)
                value = n / 10.0
                return ScoreResult(
                    scorer=self.name,
                    value=value,
                    raw=n,
                    passed=value >= self.threshold,
                    threshold=self.threshold,
                    cost=resp.cost,
                    latency=resp.latency,
                    judge_model=resp.model,
                    explanation=f"judge rated {n}/10",
                )
            except Exception as exc:  # noqa: BLE001 - judge is fail-safe
                last_error = f"{type(exc).__name__}: {exc}"
                if attempt < self.max_retries:
                    time.sleep(self._backoff_base * (2**attempt))
        return ScoreResult.errored(self.name, last_error)
