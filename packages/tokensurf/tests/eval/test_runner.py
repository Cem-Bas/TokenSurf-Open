from tokensurf.core.models import ScoreResult
from tokensurf.eval.dataset import Dataset
from tokensurf.eval.runner import evaluate
from tokensurf.scorers.base import Scorer
from tokensurf.scorers.trajectory import ToolSequence
from tokensurf.sdk.track import span, track


class _Pass(Scorer):
    name = "pass"

    def score(self, *, trace, case=None):
        return ScoreResult(scorer=self.name, value=1.0, passed=True)


class _Boom(Scorer):
    name = "boom"

    def score(self, *, trace, case=None):
        raise RuntimeError("scorer exploded")


class _AsyncPass(Scorer):
    name = "async_pass"

    async def score(self, *, trace, case=None):
        return ScoreResult(scorer=self.name, value=1.0, passed=True)


def echo_task(question):
    return f"answer: {question}"


def boom_task(question):
    raise ValueError("task failed")


def test_evaluate_runs_task_and_captures_trace():
    data = Dataset.from_list([{"id": "c1", "input": "hi"}])
    report = evaluate(task=echo_task, data=data, scorers=[_Pass()])
    assert len(report.results) == 1
    result = report.results[0]
    assert result.case.id == "c1"
    assert result.trace is not None
    assert result.trace.output == "answer: hi"
    assert result.scores[0].passed is True


def test_evaluate_marks_raising_scorer_as_errored_and_keeps_going():
    data = Dataset.from_list([{"id": "c1", "input": "hi"}])
    report = evaluate(task=echo_task, data=data, scorers=[_Boom(), _Pass()])
    scores = report.results[0].scores
    assert scores[0].error is not None
    assert "scorer exploded" in scores[0].error
    assert scores[0].value is None
    assert scores[0].passed is None
    # the second scorer still ran
    assert scores[1].passed is True


def test_evaluate_awaits_coroutine_scorers():
    data = Dataset.from_list([{"id": "c1", "input": "hi"}])
    report = evaluate(task=echo_task, data=data, scorers=[_AsyncPass()])
    score = report.results[0].scores[0]
    assert isinstance(score, ScoreResult)
    assert score.passed is True
    assert score.value == 1.0


def test_evaluate_does_not_abort_when_task_raises():
    data = Dataset.from_list([{"id": "c1", "input": "x"}, {"id": "c2", "input": "y"}])
    report = evaluate(task=boom_task, data=data, scorers=[_Pass()])
    # both cases produced results despite the task raising
    assert len(report.results) == 2
    assert report.results[0].trace is not None
    assert report.results[0].trace.error is not None
    # scorers still ran on every case
    assert report.results[1].scores[0].passed is True


def test_evaluate_captures_spans_from_tracked_task():
    """A tool span emitted inside an @track task must reach the scorers.

    Regression for nested-@track span orphaning: when the user's task is itself
    @track-decorated, the runner wraps it again. The inner frame must reuse the
    runner's Trace (not hijack _CURRENT) so emitted spans land on the captured
    trajectory the scorers see.
    """

    @track
    def agent(question):
        with span("lookup", type="tool", input=question):
            return f"answer: {question}"

    data = Dataset.from_list([{"id": "c1", "input": "hi"}])
    report = evaluate(task=agent, data=data, scorers=[ToolSequence(expected=["lookup"])])

    result = report.results[0]
    assert result.trace is not None
    assert [s.name for s in result.trace.spans] == ["lookup"]
    assert result.scores[0].passed is True


def test_evaluate_writes_each_trace_to_sink():
    data = Dataset.from_list([{"id": "c1", "input": "a"}, {"id": "c2", "input": "b"}])
    written = []

    class _ListSink:
        def write(self, trace):
            written.append(trace)

    evaluate(task=echo_task, data=data, scorers=[_Pass()], sink=_ListSink())
    assert len(written) == 2
    assert {t.output for t in written} == {"answer: a", "answer: b"}
