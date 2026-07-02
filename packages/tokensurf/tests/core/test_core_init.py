def test_core_package_reexports_public_symbols():
    from tokensurf.core import (
        Case,
        EvalCaseResult,
        EvalReport,
        ScoreResult,
        Span,
        SpanType,
        Trace,
        new_id,
    )

    assert callable(new_id)
    assert Span.__name__ == "Span"
    assert Trace.__name__ == "Trace"
    assert Case.__name__ == "Case"
    assert ScoreResult.__name__ == "ScoreResult"
    assert EvalCaseResult.__name__ == "EvalCaseResult"
    assert EvalReport.__name__ == "EvalReport"
    assert SpanType is not None
