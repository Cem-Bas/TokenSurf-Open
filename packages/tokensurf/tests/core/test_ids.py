import re
import uuid

from tokensurf.core.ids import new_id


def test_new_id_is_32_char_lowercase_hex():
    value = new_id()
    assert isinstance(value, str)
    assert re.fullmatch(r"[0-9a-f]{32}", value)


def test_new_id_is_unique_across_many_calls():
    assert len({new_id() for _ in range(1000)}) == 1000


def test_new_id_is_monkeypatchable_for_determinism(monkeypatch):
    import tokensurf.core.ids as ids

    monkeypatch.setattr(ids.uuid, "uuid4", lambda: uuid.UUID(int=0))
    assert ids.new_id() == "00000000000000000000000000000000"
