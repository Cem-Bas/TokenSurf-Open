# Scorers

Scorers grade a single agent run — a `Trace` — and return a `ScoreResult` with a value normalized
to 0–1. You attach a list of scorers to `evaluate()` and every case in your dataset is graded by
every scorer. TokenSurf ships 14 built-in scorers in four families, and you can write your own.

```python
import tokensurf as ts

data = ts.Dataset.from_list([{"id": "c1", "input": "capital of France", "expected": "Paris"}])
report = ts.evaluate(task=my_agent, data=data, scorers=[ts.ExactMatch(), ts.LatencyUnder(2.0)])
print(report.pass_rate())
```

All scorer classes are exported at the top level (`import tokensurf as ts`, then `ts.ExactMatch`
and so on). Support classes such as `LiteLLMClient` live in submodules — import paths are given
in each section below.

## How scoring works

Every scorer subclasses the abstract base in `tokensurf.scorers.base`:

```python
class Scorer(ABC):
    name: str

    @abstractmethod
    def score(
        self, *, trace: Trace, case: Case | None = None
    ) -> ScoreResult | Awaitable[ScoreResult]: ...
```

`score()` takes keyword-only arguments: the `trace` captured for the run, and the `case` it was
run against (which carries the optional `expected` reference value). It returns a `ScoreResult`:

| Field         | Type            | Meaning                                                      |
|---------------|-----------------|--------------------------------------------------------------|
| `scorer`      | `str`           | Scorer name as it appears in reports                         |
| `value`       | `float \| None` | Normalized score, 0.0–1.0, or `None` when there is no verdict |
| `raw`         | `Any`           | Un-normalized detail (e.g. the judge's 1–10 integer)         |
| `passed`      | `bool \| None`  | Pass/fail verdict, or `None` when undecidable                |
| `threshold`   | `float \| None` | The pass threshold used, if any                              |
| `explanation` | `str \| None`   | Human-readable reason                                        |
| `error`       | `str \| None`   | Set when the scorer could not run                            |
| `cost`        | `float \| None` | USD cost observed (judge call or summed span costs)          |
| `latency`     | `float \| None` | Seconds observed (trace duration or judge call latency)      |
| `judge_model` | `str \| None`   | Model that produced a judge verdict                          |

`ScoreResult.errored(scorer, error)` builds a no-verdict result: `value=None`, `passed=None`,
with `error` set. Built-in scorers never raise from `score()` for expected failure modes — a
missing client, a missing reference, or repeated judge errors all come back as errored results.

### Normalization to 0–1

Every built-in scorer returns `value` in 0.0–1.0 (or `None`):

- Binary checks (all deterministic scorers, most trajectory scorers) return `1.0` on pass and
  `0.0` on fail.
- `LLMJudge` and `TaskCompletion` map the judge's 1–10 rubric integer to `n / 10.0`; the raw
  integer is kept in `raw`.
- `EmbeddingSimilarity` clamps cosine similarity into 0–1; the unclamped similarity is in `raw`.
- `value=None` with `passed=None` means "no verdict": either `error` is set, or the check was
  inapplicable (e.g. `LatencyUnder` on a trace with no recorded duration).

`EvalReport.pass_rate()` counts only non-errored scores; a non-errored result with `passed=None`
stays in the denominator and therefore lowers the pass rate.

## Scorer reference

| Family        | Scorer                | Constructor                                                              | Passes when                                              |
|---------------|-----------------------|--------------------------------------------------------------------------|----------------------------------------------------------|
| Deterministic | `ExactMatch`          | `ExactMatch(expected=None, field="output")`                              | field equals `expected` (or `case.expected`) as strings  |
| Deterministic | `Contains`            | `Contains(substring, field="output", case_sensitive=False)`              | substring found in the field                             |
| Deterministic | `Regex`               | `Regex(pattern, field="output")`                                         | pattern matches anywhere in the field                    |
| Deterministic | `JSONSchemaValid`     | `JSONSchemaValid(schema, field="output")`                                | field is valid JSON matching the schema subset           |
| Deterministic | `LatencyUnder`        | `LatencyUnder(seconds)`                                                  | `trace.duration < seconds`                               |
| Deterministic | `CostUnder`           | `CostUnder(usd)`                                                         | summed span costs `< usd`                                |
| Deterministic | `ToolCalled`          | `ToolCalled(name)`                                                       | a tool span with that name exists                        |
| LLM judge     | `LLMJudge`            | `LLMJudge(criteria="overall quality", model="gpt-4o-mini", client=None, threshold=0.7, prompt=None, max_retries=2)` | judge rating / 10 `>= threshold` |
| Reference     | `EmbeddingSimilarity` | `EmbeddingSimilarity(model="text-embedding-3-small", client=None, threshold=0.8)` | clamped cosine similarity `>= threshold`      |
| Trajectory    | `ToolSequence`        | `ToolSequence(expected, strict=False)`                                   | expected tool names appear in order (or exactly)         |
| Trajectory    | `NoLoops`             | `NoLoops(max_repeats=2)`                                                 | longest same-tool run `<= max_repeats`                   |
| Trajectory    | `StepBudget`          | `StepBudget(max_steps)`                                                  | `len(trace.spans) <= max_steps`                          |
| Trajectory    | `TaskCompletion`      | `TaskCompletion(judge=None, threshold=0.7)`                              | delegated `LLMJudge` verdict passes                      |
| Trajectory    | `Recovery`            | `Recovery()`                                                             | no error spans, or a clean span after the first error    |

## Deterministic scorers

Code-based assertions with no model call: reproducible, fast, and free. All live in
`tokensurf.scorers.deterministic` and are exported at the top level. The `field` parameter names
the `Trace` attribute to check — usually `"output"` (the default) or `"input"`.

### ExactMatch

```python
ExactMatch(expected: str | None = None, field: str = "output")
```

Compares `str(trace.<field>)` to `str(expected)`. When `expected` is `None`, it falls back to
`case.expected`, so the common form takes no arguments at all. Passes on exact string equality;
on failure, `explanation` shows both values.

```python
ts.ExactMatch()                      # compare trace.output to case.expected
ts.ExactMatch(expected="Paris")      # or pin the expected value in the scorer
```

### Contains

```python
Contains(substring: str, field: str = "output", case_sensitive: bool = False)
```

Substring membership on the stringified field. Case-insensitive by default; pass
`case_sensitive=True` for an exact-case check. Passes when the substring is found.

```python
ts.Contains("paris")
```

### Regex

```python
Regex(pattern: str, field: str = "output")
```

Compiles `pattern` and passes when `re.search` finds a match anywhere in the stringified field
(search, not full match).

```python
ts.Regex(r"\b\d{4}-\d{2}-\d{2}\b")   # output mentions an ISO date
```

### JSONSchemaValid

```python
JSONSchemaValid(schema: dict, field: str = "output")
```

If the field is a string, it is parsed as JSON first (unparseable JSON fails with the parse error
in `explanation`). The value is then validated against a deliberately minimal, dependency-free
subset of JSON Schema: `type` (`object`, `array`, `string`, `number`, `integer`, `boolean`,
`null` — booleans are rejected for `integer`/`number`), `required`, `properties`, and `items`,
applied recursively. Passes on validity; `explanation` carries the first failure reason.

```python
ts.JSONSchemaValid({"type": "object", "required": ["answer"],
                    "properties": {"answer": {"type": "string"}}})
```

### LatencyUnder

```python
LatencyUnder(seconds: float)
```

Passes when `trace.duration < seconds`, and records the duration in `ScoreResult.latency`. If
the trace has no duration (the run never ended), the result is `value=None`, `passed=None` with
explanation `"no duration"`.

```python
ts.LatencyUnder(2.0)
```

### CostUnder

```python
CostUnder(usd: float)
```

Sums `span.attributes["cost"]` across all spans in the trace and passes when the total is below
`usd`. The total is recorded in `ScoreResult.cost`. Your instrumentation must set the `cost`
attribute on spans for this to measure anything — spans without it count as zero.

```python
ts.CostUnder(0.01)                   # whole run under one cent
```

### ToolCalled

```python
ToolCalled(name: str)
```

Passes when any span with `type == "tool"` and a matching `name` exists in the trace. The name
is stored on the scorer as `self.tool_name`.

```python
ts.ToolCalled(name="kb_lookup")
```

## LLM-judge scorer

An LLM grades the response against your criteria on a 1–10 rubric. Lives in
`tokensurf.scorers.llm`.

### LLMJudge

```python
LLMJudge(
    criteria: str = "overall quality",
    model: str = "gpt-4o-mini",
    client: LLMClient | None = None,
    threshold: float = 0.7,
    prompt: str | None = None,
    max_retries: int = 2,
)
```

Builds a rubric prompt from `criteria`, `trace.input`, and `trace.output`, asks the client for a
single 1–10 integer, and normalizes it: `value = n / 10.0`, `passed = value >= threshold`. The
result carries `raw` (the integer), `threshold`, `cost`, `latency`, `judge_model`, and an
explanation like `"judge rated 8/10"`.

- **Client required.** If `client` is `None`, `score()` returns an errored result
  (`"no LLMClient configured"`) rather than raising. Pass a client explicitly.
- **Custom prompt.** `prompt` overrides the default rubric template; it is formatted with
  `.format(criteria=..., input=..., output=...)`, so use `{criteria}`, `{input}`, and `{output}`
  placeholders. The judge's reply must still contain a standalone 1–10 integer.
- **Retries.** Any client exception or unparseable reply is retried up to `max_retries` more
  times (default 2, so 3 attempts total) with exponential backoff starting at 0.5 s. If every
  attempt fails, the result is errored with the last error message.

```python
from tokensurf.scorers.llm import LiteLLMClient
judge = ts.LLMJudge(criteria="answers the question correctly", client=LiteLLMClient())
```

### The LLMClient protocol and LiteLLMClient

`LLMClient` is a `runtime_checkable` Protocol — any object with the right method works, no
inheritance required (handy for offline test doubles):

```python
class LLMClient(Protocol):
    def complete(self, *, model: str, messages: list[dict[str, str]]) -> LLMResponse: ...
```

`LLMResponse` is a pydantic model with fields `text: str`, `model: str`, `cost: float | None`,
and `latency: float | None`.

The bundled implementation is `LiteLLMClient` (also in `tokensurf.scorers.llm`):

```python
LiteLLMClient(*, api_base: str | None = None, api_key: str | None = None)
```

It delegates to `litellm.completion`, so the judge is provider-agnostic — set `model` to any
litellm model string. litellm is imported lazily inside `complete()`, and it is a core dependency
of the `tokensurf` package, so no extra install is needed for the judge.

### Judge API keys via environment variables

litellm reads provider API keys from the standard environment variables, so exporting the right
key is enough — or pass `api_key=` to `LiteLLMClient` directly.

When you run an eval through the CLI against a self-hosted TokenSurf Server
(`tokensurf eval run FILE --server URL --key KEY`), the CLI first pulls the project's stored
judge keys from the server and exports them, mapped by provider name. A variable is only set if
it is not already present — your local environment always wins. Pass `--no-config-pull` to skip
the pull entirely.

| Provider (server-side name) | Environment variable |
|-----------------------------|----------------------|
| `openai`                    | `OPENAI_API_KEY`     |
| `anthropic`                 | `ANTHROPIC_API_KEY`  |
| `gemini`                    | `GEMINI_API_KEY`     |

## Reference-based scorer

Compares the output against a labeled expected answer using embedding similarity. Lives in
`tokensurf.scorers.reference`.

### EmbeddingSimilarity

```python
EmbeddingSimilarity(
    model: str = "text-embedding-3-small",
    client: LLMClient | None = None,
    threshold: float = 0.8,
)
```

Requires a reference: `case.expected` must be set, otherwise the result is errored
(`"no reference (case.expected) to compare against"`). It embeds `str(trace.output)` and
`str(case.expected)`, computes cosine similarity, and clamps it into 0–1:
`passed = value >= threshold`, `raw` keeps the unclamped similarity, and `explanation` reads
`"cosine similarity 0.912"`.

Embeddings come from one of two places:

- If the injected `client` has an `embed()` method (the `EmbeddingClient` Protocol:
  `embed(*, model: str, texts: list[str]) -> list[list[float]]`), it is used.
- Otherwise `litellm.embedding` is called (lazy import). If litellm is not importable, the
  score errors with a clear message.

`litellm` is a core dependency, so embeddings work out of the box — no optional extra is needed.
The scorer is always importable; only `score()` can fail, and failures come back as errored
results, never exceptions.

```python
ts.EmbeddingSimilarity(threshold=0.85)   # needs case.expected on each case
```

## Trajectory scorers

These grade the whole multi-step run — the sequence of spans your agent produced — rather than
just the final answer. All live in `tokensurf.scorers.trajectory`. "Tool spans" below means
spans with `type == "tool"`, in their original order.

### ToolSequence

```python
ToolSequence(expected: list[str], strict: bool = False)
```

Collects the names of the trace's tool spans. With `strict=False` (default), passes when
`expected` is an in-order subsequence of the actual tool names (other tools may appear between
them). With `strict=True`, the actual list must equal `expected` exactly. On failure,
`explanation` shows both lists.

```python
ts.ToolSequence(expected=["search", "fetch", "summarize"])
```

### NoLoops

```python
NoLoops(max_repeats: int = 2)
```

Finds the longest run of consecutive identical tool names and passes when it is at most
`max_repeats`. Catches agents stuck calling the same tool over and over.

```python
ts.NoLoops(max_repeats=3)
```

### StepBudget

```python
StepBudget(max_steps: int)
```

Passes when `len(trace.spans) <= max_steps`. Counts all spans, not just tool spans. The
explanation always reports the count, e.g. `"7 steps (budget 10)"`.

```python
ts.StepBudget(max_steps=10)
```

### TaskCompletion

```python
TaskCompletion(judge: LLMJudge | None = None, threshold: float = 0.7)
```

An LLM-judge over the whole trajectory: it serializes every span (name, type, input, output,
error) plus the final output into the judge's input, then delegates to an `LLMJudge` and
propagates its full result (`value`, `raw`, `passed`, `threshold`, `cost`, `latency`,
`judge_model`, `explanation`, `error`). The default judge uses the criteria
`"task completion: did the agent fully accomplish the user's task?"` — but it has no client, so
in practice pass a judge with a configured client:

```python
from tokensurf.scorers.llm import LiteLLMClient
completion_judge = ts.LLMJudge(
    criteria="task completion: did the agent fully accomplish the user's task?",
    client=LiteLLMClient(),
)
ts.TaskCompletion(judge=completion_judge)
```

### Recovery

```python
Recovery()
```

No constructor parameters. Passes with `value=1.0` when the trace has no error spans. If any
span has an error, it passes only when some later span completed without an error — the agent
recovered instead of dying on the failure. Explanations: `"no error spans"`,
`"recovered after error"`, or `"no successful span after error"`.

```python
ts.Recovery()
```

## Writing a custom scorer

Subclass `Scorer`, set a unique `name`, implement the keyword-only `score()` method, and return
a `ScoreResult`. Decorate with `@register` to add the class to the scorer registry.

```python
from tokensurf import Case, ScoreResult, Scorer, Trace
from tokensurf.scorers.base import register


@register
class WordBudget(Scorer):
    name = "WordBudget"

    def __init__(self, max_words: int):
        self.max_words = max_words

    def score(self, *, trace: Trace, case: Case | None = None) -> ScoreResult:
        words = len(str(trace.output or "").split())
        ok = words <= self.max_words
        return ScoreResult(
            scorer=self.name,
            value=1.0 if ok else 0.0,
            passed=ok,
            explanation=f"{words} words (budget {self.max_words})",
        )
```

The contract:

- `name` is the string that appears in reports and is the registry key. `register` (from
  `tokensurf.scorers.base`) stores the class in `REGISTRY` keyed by `name`; `get(name)` looks it
  up. Registration is how built-in scorers are cataloged; it is optional for private scorers.
- `score()` must accept keyword-only `trace` and `case` and return a `ScoreResult`. Keep `value`
  normalized to 0.0–1.0 (or `None`), so report aggregates like `mean_score()` stay comparable
  across scorers. Put un-normalized detail in `raw`.
- When you cannot produce a verdict, return `ScoreResult.errored(self.name, "reason")` instead
  of raising — errored results are excluded from `pass_rate()` and surfaced by `error_count()`.
- Async is allowed: the base class signature permits returning an `Awaitable[ScoreResult]`, so
  you can declare `async def score(...)`. The eval runner detects the awaitable and runs it with
  `asyncio.run`.
- The runner is fail-safe regardless: if your `score()` raises, `evaluate()` converts the
  exception into `ScoreResult.errored(name, str(exc))` — one broken scorer never aborts a run.

See the [docs index](index.md) for the rest of the documentation set.
