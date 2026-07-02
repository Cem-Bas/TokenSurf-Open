from tokensurf.scorers.llm import LLMJudge
from tokensurf.scorers.trajectory import (
    NoLoops,
    Recovery,
    StepBudget,
    TaskCompletion,
    ToolSequence,
)


def test_tool_sequence_subsequence(make_span, make_trace):
    trace = make_trace([make_span("search"), make_span("calc"), make_span("summarize")])
    assert ToolSequence(expected=["search", "summarize"]).score(trace=trace).passed is True
    assert ToolSequence(expected=["summarize", "search"]).score(trace=trace).passed is False


def test_tool_sequence_strict(make_span, make_trace):
    trace = make_trace([make_span("a"), make_span("b")])
    assert ToolSequence(expected=["a", "b"], strict=True).score(trace=trace).value == 1.0
    assert ToolSequence(expected=["a"], strict=True).score(trace=trace).value == 0.0


def test_no_loops(make_span, make_trace):
    looping = make_trace([make_span("x"), make_span("x"), make_span("x")])
    assert NoLoops(max_repeats=2).score(trace=looping).passed is False
    fine = make_trace([make_span("x"), make_span("y"), make_span("x")])
    assert NoLoops(max_repeats=2).score(trace=fine).passed is True


def test_step_budget(make_span, make_trace):
    trace = make_trace([make_span("a"), make_span("b"), make_span("c")])
    assert StepBudget(max_steps=3).score(trace=trace).passed is True
    assert StepBudget(max_steps=2).score(trace=trace).passed is False


def test_recovery(make_span, make_trace):
    recovered = make_trace([make_span("a", error="boom"), make_span("b")])
    assert Recovery().score(trace=recovered).passed is True
    stuck = make_trace([make_span("a"), make_span("b", error="boom")])
    assert Recovery().score(trace=stuck).passed is False
    clean = make_trace([make_span("a"), make_span("b")])
    assert Recovery().score(trace=clean).value == 1.0


def test_task_completion_delegates_to_judge(fake_llm, make_span, make_trace):
    judge = LLMJudge(client=fake_llm(responses=["9"]), threshold=0.7)
    result = TaskCompletion(judge=judge).score(trace=make_trace([make_span("a")]))
    assert result.scorer == "TaskCompletion"
    assert result.value == 0.9
    assert result.passed is True


def test_task_completion_propagates_judge_error(fake_llm, make_trace):
    judge = LLMJudge(client=fake_llm(raises=9), max_retries=0)
    result = TaskCompletion(judge=judge).score(trace=make_trace([]))
    assert result.scorer == "TaskCompletion"
    assert result.error is not None
    assert result.value is None
