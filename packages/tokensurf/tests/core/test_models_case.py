import pytest
from pydantic import ValidationError

from tokensurf.core.models import Case


def test_case_minimal_requires_id_and_input_with_defaults():
    c = Case(id="c1", input="q")
    assert c.id == "c1"
    assert c.input == "q"
    assert c.expected is None
    assert c.metadata == {}


def test_case_requires_input():
    with pytest.raises(ValidationError):
        Case.model_validate({"id": "c1"})


def test_case_round_trip_json():
    c = Case(id="c1", input={"q": 1}, expected="answer", metadata={"split": "test"})
    assert Case.model_validate_json(c.model_dump_json()) == c
