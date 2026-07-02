import json
import sqlite3

from tokensurf.core.models import Trace
from tokensurf.sdk.sinks import JSONLSink, Sink, SQLiteSink


def test_jsonlsink_appends_one_line_per_trace(tmp_path):
    path = tmp_path / "traces.jsonl"
    sink = JSONLSink(path)
    sink.write(Trace(id="t1", name="a", start=1.0, output="hi"))
    sink.write(Trace(id="t2", name="b", start=2.0))

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2

    first = json.loads(lines[0])
    assert first["id"] == "t1"
    assert first["name"] == "a"
    assert first["output"] == "hi"

    second = json.loads(lines[1])
    assert second["id"] == "t2"


def test_jsonlsink_satisfies_sink_protocol(tmp_path):
    assert isinstance(JSONLSink(tmp_path / "x.jsonl"), Sink)


def test_sqlitesink_write_and_read_back(tmp_path):
    path = tmp_path / "traces.db"
    sink = SQLiteSink(path)
    sink.write(Trace(id="t1", name="agent-run", start=1.0, output="hi"))

    conn = sqlite3.connect(path)
    try:
        rows = conn.execute("SELECT id, name, json, created FROM traces").fetchall()
    finally:
        conn.close()

    assert len(rows) == 1
    row_id, row_name, row_json, row_created = rows[0]
    assert row_id == "t1"
    assert row_name == "agent-run"
    assert row_created is not None

    restored = Trace.model_validate_json(row_json)
    assert restored.id == "t1"
    assert restored.output == "hi"


def test_sqlitesink_satisfies_sink_protocol(tmp_path):
    assert isinstance(SQLiteSink(tmp_path / "x.db"), Sink)
