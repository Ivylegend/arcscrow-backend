from app.evidence.service import canonical_json, evidence_hash


def test_canonical_evidence_hash_is_order_independent():
    assert canonical_json({"b": 2, "a": 1}) == canonical_json({"a": 1, "b": 2})
    first = evidence_hash(None, {"a": 1})
    second = evidence_hash(first, {"b": 2})
    assert first != second
    assert len(second) == 64
