# tests/test_normalize.py
from iam_policy import CONFIDENCE_LOW, CONFIDENCE_MEDIUM
from normalize import _DEDUP_FIELDS, normalize_bindings

# ---------------------------------------------------------------------------
# shared fixtures
# ---------------------------------------------------------------------------

_ROLE_ARN = "arn:aws:iam::123456789012:role/MyRole"
_USER_ARN = "arn:aws:iam::123456789012:user/alice"
_USER2_ARN = "arn:aws:iam::123456789012:user/bob"
_GROUP_ARN = "arn:aws:iam::123456789012:group/DevGroup"
_MODEL_A = "amazon.titan-text-express-v1"
_MODEL_B = "anthropic.claude-v2"
_POLICY_ARN = "arn:aws:iam::123456789012:policy/BedrockPolicy"

_ROLE_CAND = {
    "roleName": "MyRole",
    "roleArn": _ROLE_ARN,
    "modelId": _MODEL_A,
    "confidence": CONFIDENCE_MEDIUM,
    "conditions": None,
    "sourceTag": "inline:RolePolicy",
}

def _direct(*, model_id=_MODEL_A, source_tag="inline:UserPolicy",
            principal_arn=_USER_ARN, confidence=CONFIDENCE_MEDIUM, conditions=None):
    return {
        "principalType": "user",
        "principalName": "alice",
        "principalArn": principal_arn,
        "sourcePrincipalType": "user",
        "sourcePrincipalName": "alice",
        "sourcePrincipalArn": principal_arn,
        "modelId": model_id,
        "confidence": confidence,
        "conditions": conditions,
        "sourceTag": source_tag,
    }

def _inherited(*, model_id=_MODEL_A, source_tag="inline:GroupPolicy",
               source_arn=_GROUP_ARN, confidence=CONFIDENCE_MEDIUM, conditions=None):
    return {
        "principalType": "user",
        "principalName": "alice",
        "principalArn": _USER_ARN,
        "sourcePrincipalType": "group",
        "sourcePrincipalName": "DevGroup",
        "sourcePrincipalArn": source_arn,
        "modelId": model_id,
        "confidence": confidence,
        "conditions": conditions,
        "sourceTag": source_tag,
    }


# ---------------------------------------------------------------------------
# empty input
# ---------------------------------------------------------------------------

def test_empty_input_returns_empty():
    bindings, principals = normalize_bindings([], [])
    assert bindings == []
    assert principals == []


# ---------------------------------------------------------------------------
# role candidate normalization
# ---------------------------------------------------------------------------

def test_role_candidate_maps_to_unified_schema():
    bindings, _ = normalize_bindings([_ROLE_CAND], [])
    b = bindings[0]
    assert b["principalType"] == "role"
    assert b["principalName"] == "MyRole"
    assert b["principalArn"] == _ROLE_ARN
    assert b["sourcePrincipalType"] == "role"
    assert b["sourcePrincipalName"] == "MyRole"
    assert b["sourcePrincipalArn"] == _ROLE_ARN
    assert b["modelId"] == _MODEL_A
    assert b["confidence"] == CONFIDENCE_MEDIUM
    assert b["conditions"] is None
    assert b["sourceTag"] == "inline:RolePolicy"


def test_role_source_principal_arn_equals_principal_arn():
    bindings, _ = normalize_bindings([_ROLE_CAND], [])
    b = bindings[0]
    assert b["sourcePrincipalArn"] == b["principalArn"]


def test_role_candidate_preserves_conditions():
    cand = {**_ROLE_CAND, "confidence": CONFIDENCE_LOW,
            "conditions": {"StringEquals": {"aws:region": "us-east-1"}}}
    bindings, _ = normalize_bindings([cand], [])
    assert bindings[0]["confidence"] == CONFIDENCE_LOW
    assert bindings[0]["conditions"] == {"StringEquals": {"aws:region": "us-east-1"}}


# ---------------------------------------------------------------------------
# user candidates pass through unchanged (except bindingId added)
# ---------------------------------------------------------------------------

def test_user_direct_candidate_fields_preserved():
    bindings, _ = normalize_bindings([], [_direct()])
    b = bindings[0]
    assert b["principalType"] == "user"
    assert b["principalArn"] == _USER_ARN
    assert b["sourcePrincipalType"] == "user"
    assert b["sourcePrincipalArn"] == _USER_ARN


def test_user_inherited_candidate_fields_preserved():
    bindings, _ = normalize_bindings([], [_inherited()])
    b = bindings[0]
    assert b["principalType"] == "user"
    assert b["principalArn"] == _USER_ARN
    assert b["sourcePrincipalType"] == "group"
    assert b["sourcePrincipalArn"] == _GROUP_ARN


def test_binding_id_field_added():
    bindings, _ = normalize_bindings([_ROLE_CAND], [])
    assert "bindingId" in bindings[0]
    assert len(bindings[0]["bindingId"]) == 16


# ---------------------------------------------------------------------------
# deduplication
# ---------------------------------------------------------------------------

def test_dedup_exact_duplicate_collapsed():
    bindings, _ = normalize_bindings([], [_direct(), _direct()])
    assert len(bindings) == 1


def test_dedup_different_model_both_preserved():
    bindings, _ = normalize_bindings([], [_direct(model_id=_MODEL_A), _direct(model_id=_MODEL_B)])
    assert len(bindings) == 2
    assert {b["modelId"] for b in bindings} == {_MODEL_A, _MODEL_B}


def test_dedup_different_source_tag_both_preserved():
    bindings, _ = normalize_bindings([], [
        _direct(source_tag="inline:PolicyA"),
        _direct(source_tag="inline:PolicyB"),
    ])
    assert len(bindings) == 2


def test_dedup_different_principal_both_preserved():
    bindings, _ = normalize_bindings([], [
        _direct(principal_arn=_USER_ARN),
        _direct(principal_arn=_USER2_ARN),
    ])
    assert len(bindings) == 2


# ---------------------------------------------------------------------------
# direct vs inherited distinctness — the core invariant
# ---------------------------------------------------------------------------

def test_direct_and_inherited_different_source_tag_both_preserved():
    """Standard case: direct and inherited use different source tags."""
    bindings, _ = normalize_bindings([], [
        _direct(source_tag="inline:UserPolicy"),
        _inherited(source_tag="inline:GroupPolicy"),
    ])
    assert len(bindings) == 2


def test_direct_and_inherited_same_source_tag_still_preserved():
    """
    Even when sourceTag is identical (e.g. both policies named 'BedrockPolicy'),
    sourcePrincipalArn differs (user vs group), so the dedup key differs.
    Both grants must be retained.
    """
    same_tag = "inline:BedrockPolicy"
    bindings, _ = normalize_bindings([], [
        _direct(source_tag=same_tag),
        _inherited(source_tag=same_tag),
    ])
    assert len(bindings) == 2
    source_arns = {b["sourcePrincipalArn"] for b in bindings}
    assert source_arns == {_USER_ARN, _GROUP_ARN}


def test_dedup_key_fields_are_the_documented_tuple():
    """_DEDUP_FIELDS is exactly the four-field tuple used for dedup and ID generation."""
    assert set(_DEDUP_FIELDS) == {"principalArn", "sourcePrincipalArn", "modelId", "sourceTag"}
    assert len(_DEDUP_FIELDS) == 4


def test_dedup_first_seen_wins():
    """First occurrence is kept when the dedup key collides."""
    first = _direct(confidence=CONFIDENCE_MEDIUM)
    second = {**first, "confidence": CONFIDENCE_LOW}  # same key, different confidence
    bindings, _ = normalize_bindings([], [first, second])
    assert len(bindings) == 1
    assert bindings[0]["confidence"] == CONFIDENCE_MEDIUM


# ---------------------------------------------------------------------------
# binding ID stability and distinctness
# ---------------------------------------------------------------------------

def test_binding_id_is_deterministic():
    b1, _ = normalize_bindings([_ROLE_CAND], [])
    b2, _ = normalize_bindings([_ROLE_CAND], [])
    assert b1[0]["bindingId"] == b2[0]["bindingId"]


def test_binding_id_distinct_for_different_model():
    bindings, _ = normalize_bindings([], [
        _direct(model_id=_MODEL_A),
        _direct(model_id=_MODEL_B),
    ])
    assert bindings[0]["bindingId"] != bindings[1]["bindingId"]


def test_binding_id_distinct_for_different_source_principal_arn():
    """Direct and inherited same model produce different IDs."""
    bindings, _ = normalize_bindings([], [
        _direct(source_tag="inline:P"),
        _inherited(source_tag="inline:P"),
    ])
    assert bindings[0]["bindingId"] != bindings[1]["bindingId"]


def test_binding_id_distinct_for_different_source_tag():
    bindings, _ = normalize_bindings([], [
        _direct(source_tag="inline:A"),
        _direct(source_tag="inline:B"),
    ])
    assert bindings[0]["bindingId"] != bindings[1]["bindingId"]


# ---------------------------------------------------------------------------
# principals derivation
# ---------------------------------------------------------------------------

def test_principals_unique_by_principal_arn():
    # Two bindings from the same user → one principal entry
    bindings, principals = normalize_bindings([], [
        _direct(model_id=_MODEL_A),
        _direct(model_id=_MODEL_B),
    ])
    assert len(principals) == 1
    assert principals[0]["principalArn"] == _USER_ARN


def test_principals_sorted_by_arn():
    bindings, principals = normalize_bindings(
        [_ROLE_CAND],
        [_direct(principal_arn=_USER_ARN)],
    )
    arns = [p["principalArn"] for p in principals]
    assert arns == sorted(arns)


def test_principals_contains_role_and_user():
    _, principals = normalize_bindings([_ROLE_CAND], [_direct()])
    types = {p["principalType"] for p in principals}
    assert "role" in types
    assert "user" in types


def test_principals_group_source_not_listed_as_primary_principal():
    """The group that granted the permission is a source, not an effective principal."""
    _, principals = normalize_bindings([], [_inherited()])
    principal_arns = {p["principalArn"] for p in principals}
    assert _GROUP_ARN not in principal_arns
    assert _USER_ARN in principal_arns


def test_principals_fields():
    _, principals = normalize_bindings([_ROLE_CAND], [])
    p = principals[0]
    assert set(p.keys()) == {"principalType", "principalName", "principalArn"}
