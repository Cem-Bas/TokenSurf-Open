from tokensurf.core.models import Case
from tokensurf.eval.dataset import Dataset


def test_from_list_builds_cases_and_generates_ids():
    ds = Dataset.from_list(
        [
            {"id": "c1", "input": "2+2", "expected": "4"},
            {"input": "cap of France", "expected": "Paris"},
        ]
    )
    assert len(ds) == 2
    assert isinstance(ds.cases[0], Case)
    assert ds.cases[0].id == "c1"
    assert ds.cases[0].input == "2+2"
    assert ds.cases[0].expected == "4"
    # second row had no id -> a non-empty id was generated
    assert ds.cases[1].id
    assert ds.cases[1].id != "c1"


def test_iter_and_len():
    ds = Dataset.from_list([{"input": "a"}, {"input": "b"}, {"input": "c"}])
    assert len(ds) == 3
    assert [case.input for case in ds] == ["a", "b", "c"]


def test_from_jsonl(tmp_path):
    path = tmp_path / "data.jsonl"
    path.write_text(
        '{"id": "j1", "input": "hi", "expected": "ok"}\n'
        "\n"  # blank line is skipped
        '{"id": "j2", "input": "bye", "expected": "later"}\n',
        encoding="utf-8",
    )
    ds = Dataset.from_jsonl(path)
    assert len(ds) == 2
    assert [c.id for c in ds] == ["j1", "j2"]
    assert ds.cases[1].expected == "later"


def test_from_csv(tmp_path):
    path = tmp_path / "data.csv"
    path.write_text(
        "id,input,expected\nx1,question one,answer one\nx2,question two,answer two\n",
        encoding="utf-8",
    )
    ds = Dataset.from_csv(path)
    assert len(ds) == 2
    assert ds.cases[0].id == "x1"
    assert ds.cases[0].input == "question one"
    assert ds.cases[1].expected == "answer two"
