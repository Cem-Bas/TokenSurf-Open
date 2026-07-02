from tokensurf.scorers import llm as llm_mod
from tokensurf.scorers.llm import LiteLLMClient, LLMClient, LLMJudge, LLMResponse


def test_llmresponse_defaults():
    resp = LLMResponse(text="8", model="gpt-4o-mini")
    assert resp.text == "8"
    assert resp.cost is None and resp.latency is None


def test_litellm_client_satisfies_protocol():
    assert isinstance(LiteLLMClient(), LLMClient)


def test_litellm_client_maps_response(monkeypatch):
    import litellm

    class _Msg:
        content = "hello"

    class _Choice:
        message = _Msg()

    class _Resp:
        choices = [_Choice()]
        _hidden_params = {"response_cost": 0.0023}

    monkeypatch.setattr(litellm, "completion", lambda **kw: _Resp())
    resp = LiteLLMClient().complete(
        model="gpt-4o-mini", messages=[{"role": "user", "content": "hi"}]
    )
    assert resp.text == "hello"
    assert resp.model == "gpt-4o-mini"
    assert resp.cost == 0.0023
    assert resp.latency is not None


def test_judge_happy_path(fake_llm, sample_trace):
    judge = LLMJudge(client=fake_llm(responses=["8"]), threshold=0.7)
    result = judge.score(trace=sample_trace)
    assert result.value == 0.8
    assert result.raw == 8
    assert result.passed is True
    assert result.threshold == 0.7
    assert result.judge_model == "gpt-4o-mini"


def test_judge_parses_embedded_integer(fake_llm, sample_trace):
    judge = LLMJudge(client=fake_llm(responses=["I rate this 9 out of 10."]))
    assert judge.score(trace=sample_trace).value == 0.9


def test_judge_threshold_fail(fake_llm, sample_trace):
    result = LLMJudge(client=fake_llm(responses=["5"]), threshold=0.7).score(trace=sample_trace)
    assert result.value == 0.5
    assert result.passed is False


def test_judge_retries_then_succeeds(fake_llm, sample_trace, monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr(llm_mod.time, "sleep", lambda s: sleeps.append(s))
    result = LLMJudge(client=fake_llm(responses=["8"], raises=1), max_retries=2).score(
        trace=sample_trace
    )
    assert result.value == 0.8
    assert len(sleeps) == 1  # one exponential backoff before the successful retry


def test_judge_exhausts_retries_to_errored(fake_llm, sample_trace, monkeypatch):
    monkeypatch.setattr(llm_mod.time, "sleep", lambda s: None)
    result = LLMJudge(client=fake_llm(raises=5), max_retries=2).score(trace=sample_trace)
    assert result.error is not None
    assert result.value is None
    assert result.passed is None


def test_judge_no_client_errors(sample_trace):
    result = LLMJudge(client=None).score(trace=sample_trace)
    assert result.error is not None
    assert result.value is None
