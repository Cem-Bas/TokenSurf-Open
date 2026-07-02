import pytest
from pydantic import ValidationError

from tokensurf.core.models import Span


def test_span_minimal_required_fields_and_defaults():
    s = Span(id="s1", name="step", start=1.0)
    assert s.id == "s1"
    assert s.name == "step"
    assert s.start == 1.0
    assert s.parent_id is None
    assert s.type == "custom"
    assert s.input is None
    assert s.output is None
    assert s.end is None
    assert s.error is None
    assert s.attributes == {}


def test_span_round_trip_dict_and_json():
    s = Span(
        id="s1",
        parent_id="p0",
        type="tool",
        name="search",
        input={"q": "hi"},
        output=["a", "b"],
        start=1.0,
        end=2.5,
        attributes={"cost": 0.01},
    )
    assert Span.model_validate(s.model_dump()) == s
    assert Span.model_validate_json(s.model_dump_json()) == s


def test_span_rejects_invalid_type():
    with pytest.raises(ValidationError):
        Span.model_validate({"id": "s1", "name": "x", "start": 0.0, "type": "database"})


def test_span_requires_id_name_start():
    with pytest.raises(ValidationError):
        Span.model_validate({"name": "x", "start": 0.0})


def test_span_attributes_default_is_not_shared_between_instances():
    a = Span(id="a", name="a", start=0.0)
    b = Span(id="b", name="b", start=0.0)
    a.attributes["k"] = 1
    assert b.attributes == {}
