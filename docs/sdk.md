# SDK reference

The `tokensurf` package has two halves: a capture SDK (`@track`, `span()`, sinks) that records each
agent run as a `Trace`, and an offline eval harness (`Dataset`, `evaluate()`, `assert_eval`) that
runs a task over a dataset and grades every captured trace with scorers. This page documents both,
plus the data models they share. For the scorer catalog see [Scorers](scorers.md); for the
`tokensurf eval` commands see [CLI](cli.md).

TokenSurf is not yet on PyPI. Install from source: clone the repository and run `uv sync`.

A complete example first:

```python
import tokensurf as ts
from tokensurf.scorers.deterministic import ExactMatch, ToolCalled


def my_agent(question: str) -> str:
    with ts.span("kb_lookup", type="tool", input=question) as sp:
        sp.output = ["doc1", "doc2"]
    return "Paris"


data = ts.Dataset.from_list([
    {"id": "c1", "input": "capital of France", "expected": "Paris"},
    {"id": "c2", "input": "capital of Japan", "expected": "Tokyo"},
])

report = ts.evaluate(
    task=my_agent,
    data=data,
    scorers=[ExactMatch(), ToolCalled(name="kb_lookup")],
)
print(report.pass_rate(), report.mean_score(), report.error_count())
ts.assert_eval(report, min_pass_rate=0.5)
```

## Import paths

The names below are importable directly from the top-level `tokensurf` namespace:

| Name | Kind |
| --- | --- |
| `track`, `span`, `current_trace` | capture SDK |
| `Dataset`, `evaluate` | eval harness |
| `assert_eval` | pytest helper |
| `Trace`, `Span`, `Case`, `ScoreResult`, `EvalReport` | data models |
| `Scorer` plus all concrete scorers | scorers (see [Scorers](scorers.md)) |

Everything else lives in submodules:

| Name | Import from |
| --- | --- |
| `Sink`, `SQLiteSink`, `JSONLSink` | `tokensurf.sdk.sinks` |
| `SpanType`, `EvalCaseResult` | `tokensurf.core.models` |

## Capturing runs

### `@track`

```python
def track(fn=None, *, name: str | None = None, sink: Sink | None = None)
```

Decorate your agent's entry point so each call is captured as a `Trace`. Works bare or
parameterized:

```python
import tokensurf as ts
from tokensurf.sdk.sinks import JSONLSink


@ts.track
def my_agent(question):
    ...


@ts.track(name="support-agent", sink=JSONLSink("traces.jsonl"))
def my_agent_persisted(question):
    ...
```

On each call (when no trace is already active), the wrapper:

1. Creates a `Trace` with a fresh id, `name` (the `name` argument, or the function's `__name__`),
   and `start` set to the current time.
2. Sets `trace.input` to the first positional argument, if any. Keyword arguments are not
   captured as input.
3. Runs your function and sets `trace.output` to its return value.
4. On an exception, sets `trace.error = repr(exc)` and re-raises — `@track` never suppresses your
   function's errors when you call it directly.
5. In all cases, sets `trace.end` and, if a `sink` was given, calls `sink.write(trace)`.

The sink write is best-effort: any exception raised by the sink is swallowed, so capture can never
break your application code.

**Nesting.** If a trace is already active — an outer `@track`-decorated function is running, or the
eval runner wrapped your task — the inner wrapper is transparent: it just calls your function, so
any `span()` calls inside it land on the outer trace. The outermost frame owns the trace's
timing, input, output, error, and the sink write.

### `span()`

```python
@contextmanager
def span(name: str, *, type: SpanType = "custom", input: Any = None) -> Iterator[Span]
```

Record one step (an LLM call, tool call, sub-agent, ...) inside a tracked run. `SpanType` is the
literal type `Literal["llm", "tool", "agent", "custom"]`.

```python
with ts.span("retrieval", type="tool", input=query) as sp:
    sp.output = search(query)
```

The context manager creates a `Span` with a fresh id and `start` timestamp and yields it so you can
set `output` (or `attributes`) on it. If a trace is active, the span's `parent_id` is set to the
trace id and the span is appended to `trace.spans`. If no trace is active, the span is still
created and yielded but attached nowhere — a safe orphan, so instrumented library code does not
need to know whether it runs under `@track`.

On an exception inside the block, `sp.error = repr(exc)` is set and the exception re-raised;
`sp.end` is set in all cases.

Scorers that match on tool spans — `ToolCalled` (deterministic family) and trajectory scorers
such as `ToolSequence` — match on span `type` and `name`, so give tool spans `type="tool"` and
stable names.

### `current_trace()`

```python
def current_trace() -> Trace | None
```

Returns the currently active `Trace` (from anywhere inside a tracked call), or `None` when no
trace is active. Useful for attaching metadata mid-run:

```python
trace = ts.current_trace()
if trace is not None:
    trace.metadata["user_tier"] = "pro"
```

## Sinks

A sink is anywhere a finished `Trace` gets written. The `Sink` protocol (in
`tokensurf.sdk.sinks`) is a `runtime_checkable` `Protocol` with a single method:

```python
@runtime_checkable
class Sink(Protocol):
    def write(self, trace: Trace) -> None: ...
```

Any object with a matching `write` method works — no subclassing required. Two built-ins ship
with the SDK:

| Sink | Constructor | Behavior |
| --- | --- | --- |
| `JSONLSink` | `JSONLSink(path)` | Appends one JSON line per trace (`trace.model_dump_json()`) to the file. |
| `SQLiteSink` | `SQLiteSink(path)` | The constructor creates a `traces` table (`id TEXT PRIMARY KEY, name TEXT, json TEXT, created REAL`) if missing; each write does `INSERT OR REPLACE` of one row per trace. |

Both accept `str | os.PathLike` paths. Remember that `@track` (and `evaluate()` for its optional
`sink`) swallow sink exceptions — a broken sink loses traces silently rather than crashing your
code.

## Data models

All models below are pydantic v2 `BaseModel`s, so `model_dump()` / `model_dump_json()` /
`model_validate()` work as usual.

### `Span`

One step in an agent run.

| Field | Type | Default |
| --- | --- | --- |
| `id` | `str` | required |
| `parent_id` | `str \| None` | `None` |
| `type` | `SpanType` | `"custom"` |
| `name` | `str` | required |
| `input` | `Any` | `None` |
| `output` | `Any` | `None` |
| `start` | `float` | required |
| `end` | `float \| None` | `None` |
| `error` | `str \| None` | `None` |
| `attributes` | `dict[str, Any]` | `{}` |

`attributes` is a free-form bag; for example, the `CostUnder` scorer sums
`span.attributes["cost"]` over spans.

### `Trace`

One full agent run: ordered spans plus top-level input/output/timing.

| Field | Type | Default |
| --- | --- | --- |
| `id` | `str` | required |
| `name` | `str` | required |
| `input` | `Any` | `None` |
| `output` | `Any` | `None` |
| `spans` | `list[Span]` | `[]` |
| `start` | `float` | required |
| `end` | `float \| None` | `None` |
| `error` | `str \| None` | `None` |
| `metadata` | `dict[str, Any]` | `{}` |

Helpers:

- `duration` (property) `-> float | None` — wall-clock seconds (`end - start`), or `None` if the
  run has not ended.
- `spans_of(type: SpanType) -> list[Span]` — spans of the given type, in their original order.

### `Case`

One eval input with an optional reference value.

| Field | Type | Default |
| --- | --- | --- |
| `id` | `str` | required |
| `input` | `Any` | required |
| `expected` | `Any` | `None` |
| `metadata` | `dict[str, Any]` | `{}` |

### `ScoreResult`

A single scorer's verdict. `value` is normalized to 0.0..1.0 (or `None`).

| Field | Type | Default |
| --- | --- | --- |
| `scorer` | `str` | required |
| `value` | `float \| None` | required |
| `raw` | `Any` | `None` |
| `passed` | `bool \| None` | `None` |
| `threshold` | `float \| None` | `None` |
| `explanation` | `str \| None` | `None` |
| `error` | `str \| None` | `None` |
| `cost` | `float \| None` | `None` |
| `latency` | `float \| None` | `None` |
| `judge_model` | `str \| None` | `None` |

Factory:

```python
ScoreResult.errored(scorer: str, error: str) -> ScoreResult
```

Builds an errored result: `value=None`, `passed=None`, `error` set. Errored results are excluded
from `pass_rate` and counted by `error_count`.

### `EvalCaseResult`

One case's outcome. Available from `tokensurf.core.models` (intentionally not re-exported at the
top level).

| Field | Type | Default |
| --- | --- | --- |
| `case` | `Case` | required |
| `trace` | `Trace \| None` | `None` |
| `scores` | `list[ScoreResult]` | `[]` |

### `EvalReport`

The return value of `evaluate()`. Its only stored field is `results: list[EvalCaseResult]`; all
aggregates are computed methods:

| Method | Returns |
| --- | --- |
| `pass_rate(scorer: str \| None = None) -> float` | Fraction of non-errored scores whose `passed` is `True`; `0.0` if there are none. |
| `mean_score(scorer: str \| None = None) -> float \| None` | Mean `value` over scores with a numeric value; `None` if there are none. |
| `error_count() -> int` | Number of errored scores across all cases. |
| `scorer_names() -> list[str]` | Sorted, de-duplicated scorer names seen in the report. |

Pass `scorer` (a scorer's `name` string, e.g. `"ExactMatch"`) to restrict `pass_rate` /
`mean_score` to one scorer; omit it to aggregate over all scores.

## Datasets

`Dataset` (in `tokensurf.eval.dataset`, exported at top level) is an ordered collection of
`Case`s. It is a plain class, not a pydantic model.

```python
class Dataset:
    def __init__(self, cases: list[Case] | None = None) -> None

    @classmethod
    def from_list(cls, rows: list[dict]) -> Dataset

    @classmethod
    def from_jsonl(cls, path: str | os.PathLike[str]) -> Dataset

    @classmethod
    def from_csv(cls, path: str | os.PathLike[str]) -> Dataset

    def __iter__(self) -> Iterator[Case]
    def __len__(self) -> int
```

The parsed cases are on `dataset.cases`. Iterating a `Dataset` yields `Case` objects.

### Row keys

`from_list` reads these keys from each row dict (the same keys apply to JSONL objects and CSV
columns, since both loaders delegate to `from_list`):

| Key | Used as | If missing |
| --- | --- | --- |
| `id` | `Case.id` (stringified via `str(...)`) | a fresh generated id |
| `input` | `Case.input` | `None` |
| `expected` | `Case.expected` | `None` |
| `metadata` | `Case.metadata` | `{}` |

- `from_jsonl(path)` parses one JSON object per non-blank line.
- `from_csv(path)` uses `csv.DictReader`, so every value is a string — fine for text
  inputs/expectations; use JSONL for structured inputs.

```python
data = ts.Dataset.from_jsonl("cases.jsonl")
print(len(data))
```

## Running evaluations

### `evaluate()`

```python
def evaluate(
    *,
    task: Callable[[Any], Any],
    data: Dataset,
    scorers: list[Scorer],
    sink: Sink | None = None,
) -> EvalReport
```

All arguments are keyword-only. For each `Case` in `data`, the runner:

1. Wraps `task` with `track()` (using the task's `__name__`, or `"task"`), so you do not need to
   decorate the task yourself — but `span()` calls inside it are captured either way, thanks to
   `@track`'s nesting transparency.
2. Calls the tracked task with `case.input` as its single positional argument.
3. If the task raises, the exception is swallowed — it is recorded as `trace.error` on the
   captured trace, and the run moves on to scoring. An eval run never aborts because one case
   crashed.
4. If you passed a `sink`, writes the captured trace to it (best-effort; sink errors are
   swallowed).
5. Runs every scorer against the trace. Scorers returning a coroutine are executed with
   `asyncio.run`. A scorer that raises never crashes the run: its exception becomes
   `ScoreResult.errored(name, str(exc))` in the report.

Returns an `EvalReport` with one `EvalCaseResult` per case.

```python
report = ts.evaluate(task=my_agent, data=data, scorers=[ExactMatch()])
for scorer in report.scorer_names():
    print(scorer, report.pass_rate(scorer))
```

### `assert_eval`

```python
def assert_eval(report: EvalReport, *, min_pass_rate: float, scorer: str | None = None) -> None
```

The pytest bridge (from `tokensurf.pytest_plugin`, exported at top level). Raises
`AssertionError` — with a rendered console summary of the report attached — if
`report.pass_rate(scorer) < min_pass_rate`. Pass `scorer` to gate on a single scorer's pass rate
instead of the overall one.

```python
def test_agent_quality():
    report = ts.evaluate(task=my_agent, data=data, scorers=[ExactMatch()])
    ts.assert_eval(report, min_pass_rate=0.9, scorer="ExactMatch")
```

Because errored scores are excluded from `pass_rate`, check `report.error_count()` (or gate on it
in your test) if you also want scorer failures to fail CI.
