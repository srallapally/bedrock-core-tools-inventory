# tests/test_user_scan.py
from unittest.mock import MagicMock, call, patch

from iam_policy import CONFIDENCE_LOW, CONFIDENCE_MEDIUM
from user_scan import scan_users

# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

_USER = {"UserName": "alice", "Arn": "arn:aws:iam::123456789012:user/alice"}
_USER2 = {"UserName": "bob", "Arn": "arn:aws:iam::123456789012:user/bob"}
_GROUP = {"GroupName": "DevGroup", "Arn": "arn:aws:iam::123456789012:group/DevGroup"}
_GROUP2 = {"GroupName": "OpsGroup", "Arn": "arn:aws:iam::123456789012:group/OpsGroup"}

_MODEL_ARN = "arn:aws:bedrock:us-east-1::foundation-model/amazon.titan-text-express-v1"
_MODEL_ID = "amazon.titan-text-express-v1"
_POLICY_ARN = "arn:aws:iam::123456789012:policy/BedrockPolicy"

_INVOKE_DOC = {
    "Version": "2012-10-17",
    "Statement": [{
        "Effect": "Allow",
        "Action": "bedrock:InvokeModel",
        "Resource": _MODEL_ARN,
    }],
}
_CONDITIONAL_DOC = {
    "Version": "2012-10-17",
    "Statement": [{
        "Effect": "Allow",
        "Action": "bedrock:InvokeModel",
        "Resource": _MODEL_ARN,
        "Condition": {"StringEquals": {"aws:RequestedRegion": "us-east-1"}},
    }],
}
_EMPTY_DOC = {"Version": "2012-10-17", "Statement": []}


def _no_groups(iam_client, user_name):
    return {"Groups": [], "IsTruncated": False}


def _inline(name, document):
    return {"name": name, "document": document}


def _attached(name, arn, document):
    return {"name": name, "arn": arn, "document": document}


def _iam_no_groups():
    iam = MagicMock()
    iam.list_groups_for_user.return_value = {"Groups": [], "IsTruncated": False}
    return iam


def _iam_with_groups(*groups):
    iam = MagicMock()
    iam.list_groups_for_user.return_value = {"Groups": list(groups), "IsTruncated": False}
    return iam


# ---------------------------------------------------------------------------
# empty / no-policy cases
# ---------------------------------------------------------------------------

def test_scan_users_empty_user_list():
    with patch("user_scan.fetch_inline_policies", return_value=[]), \
         patch("user_scan.fetch_attached_policies", return_value=[]):
        assert scan_users(_iam_no_groups(), []) == []


def test_scan_users_no_policies_no_groups():
    with patch("user_scan.fetch_inline_policies", return_value=[]), \
         patch("user_scan.fetch_attached_policies", return_value=[]):
        assert scan_users(_iam_no_groups(), [_USER]) == []


def test_scan_users_empty_policy_document():
    with patch("user_scan.fetch_inline_policies", return_value=[_inline("P", _EMPTY_DOC)]), \
         patch("user_scan.fetch_attached_policies", return_value=[]):
        assert scan_users(_iam_no_groups(), [_USER]) == []


# ---------------------------------------------------------------------------
# direct user grants — lineage fields
# ---------------------------------------------------------------------------

def test_scan_users_direct_inline_all_fields():
    with patch("user_scan.fetch_inline_policies", return_value=[_inline("MyPolicy", _INVOKE_DOC)]), \
         patch("user_scan.fetch_attached_policies", return_value=[]):
        results = scan_users(_iam_no_groups(), [_USER])

    assert len(results) == 1
    c = results[0]
    assert c["principalType"] == "user"
    assert c["principalName"] == "alice"
    assert c["principalArn"] == _USER["Arn"]
    assert c["sourcePrincipalType"] == "user"
    assert c["sourcePrincipalName"] == "alice"
    assert c["sourcePrincipalArn"] == _USER["Arn"]
    assert c["modelId"] == _MODEL_ID
    assert c["confidence"] == CONFIDENCE_MEDIUM
    assert c["conditions"] is None
    assert c["sourceTag"] == "inline:MyPolicy"


def test_scan_users_direct_source_principal_arn_equals_principal_arn():
    with patch("user_scan.fetch_inline_policies", return_value=[_inline("P", _INVOKE_DOC)]), \
         patch("user_scan.fetch_attached_policies", return_value=[]):
        results = scan_users(_iam_no_groups(), [_USER])
    assert results[0]["sourcePrincipalArn"] == results[0]["principalArn"]


def test_scan_users_direct_attached_source_tag_uses_arn():
    with patch("user_scan.fetch_inline_policies", return_value=[]), \
         patch("user_scan.fetch_attached_policies",
               return_value=[_attached("BP", _POLICY_ARN, _INVOKE_DOC)]):
        results = scan_users(_iam_no_groups(), [_USER])

    assert len(results) == 1
    assert results[0]["sourceTag"] == f"managed:{_POLICY_ARN}"
    assert results[0]["sourcePrincipalArn"] == _USER["Arn"]


# ---------------------------------------------------------------------------
# inherited group grants — lineage fields
# ---------------------------------------------------------------------------

def test_scan_users_inherited_principal_is_user_not_group():
    def inline(iam_client, entity_type, entity_name):
        return [_inline("GP", _INVOKE_DOC)] if entity_type == "group" else []

    with patch("user_scan.fetch_inline_policies", side_effect=inline), \
         patch("user_scan.fetch_attached_policies", return_value=[]):
        results = scan_users(_iam_with_groups(_GROUP), [_USER])

    assert len(results) == 1
    c = results[0]
    assert c["principalType"] == "user"
    assert c["principalArn"] == _USER["Arn"]


def test_scan_users_inherited_source_principal_is_group():
    def inline(iam_client, entity_type, entity_name):
        return [_inline("GP", _INVOKE_DOC)] if entity_type == "group" else []

    with patch("user_scan.fetch_inline_policies", side_effect=inline), \
         patch("user_scan.fetch_attached_policies", return_value=[]):
        results = scan_users(_iam_with_groups(_GROUP), [_USER])

    c = results[0]
    assert c["sourcePrincipalType"] == "group"
    assert c["sourcePrincipalName"] == "DevGroup"
    assert c["sourcePrincipalArn"] == _GROUP["Arn"]


def test_scan_users_inherited_source_principal_arn_differs_from_principal_arn():
    def inline(iam_client, entity_type, entity_name):
        return [_inline("GP", _INVOKE_DOC)] if entity_type == "group" else []

    with patch("user_scan.fetch_inline_policies", side_effect=inline), \
         patch("user_scan.fetch_attached_policies", return_value=[]):
        results = scan_users(_iam_with_groups(_GROUP), [_USER])

    c = results[0]
    assert c["sourcePrincipalArn"] != c["principalArn"]
    assert c["sourcePrincipalArn"] == _GROUP["Arn"]


# ---------------------------------------------------------------------------
# dedup distinguishability
# ---------------------------------------------------------------------------

def test_scan_users_direct_and_inherited_same_model_two_records():
    """Same model granted via user's own policy AND via group — two distinct candidates."""
    def inline(iam_client, entity_type, entity_name):
        return [_inline("Policy", _INVOKE_DOC)]  # both user and group have the same policy

    with patch("user_scan.fetch_inline_policies", side_effect=inline), \
         patch("user_scan.fetch_attached_policies", return_value=[]):
        results = scan_users(_iam_with_groups(_GROUP), [_USER])

    assert len(results) == 2
    source_arns = {r["sourcePrincipalArn"] for r in results}
    assert source_arns == {_USER["Arn"], _GROUP["Arn"]}


# ---------------------------------------------------------------------------
# multiple groups
# ---------------------------------------------------------------------------

def test_scan_users_multiple_groups_accumulates_all():
    def inline(iam_client, entity_type, entity_name):
        if entity_type == "group":
            return [_inline(f"{entity_name}Policy", _INVOKE_DOC)]
        return []

    iam = MagicMock()
    iam.list_groups_for_user.return_value = {
        "Groups": [_GROUP, _GROUP2], "IsTruncated": False
    }
    with patch("user_scan.fetch_inline_policies", side_effect=inline), \
         patch("user_scan.fetch_attached_policies", return_value=[]):
        results = scan_users(iam, [_USER])

    assert len(results) == 2
    source_arns = {r["sourcePrincipalArn"] for r in results}
    assert source_arns == {_GROUP["Arn"], _GROUP2["Arn"]}


# ---------------------------------------------------------------------------
# group membership pagination
# ---------------------------------------------------------------------------

def test_scan_users_group_membership_pagination():
    iam = MagicMock()
    iam.list_groups_for_user.side_effect = [
        {"Groups": [_GROUP], "IsTruncated": True, "Marker": "mk1"},
        {"Groups": [_GROUP2], "IsTruncated": False},
    ]

    def inline(iam_client, entity_type, entity_name):
        if entity_type == "group":
            return [_inline("GP", _INVOKE_DOC)]
        return []

    with patch("user_scan.fetch_inline_policies", side_effect=inline), \
         patch("user_scan.fetch_attached_policies", return_value=[]):
        results = scan_users(iam, [_USER])

    assert len(results) == 2
    assert iam.list_groups_for_user.call_args_list == [
        call(UserName="alice"),
        call(UserName="alice", Marker="mk1"),
    ]


# ---------------------------------------------------------------------------
# failure model
# ---------------------------------------------------------------------------

def test_scan_users_per_user_failure_warns_and_continues():
    def inline(iam_client, entity_type, entity_name):
        if entity_name == "alice":
            raise RuntimeError("access denied")
        return [_inline("P", _INVOKE_DOC)]

    with patch("user_scan.fetch_inline_policies", side_effect=inline), \
         patch("user_scan.fetch_attached_policies", return_value=[]):
        results = scan_users(_iam_no_groups(), [_USER, _USER2])

    assert len(results) == 1
    assert results[0]["principalName"] == "bob"


def test_scan_users_group_list_failure_treated_as_per_user():
    iam = MagicMock()
    iam.list_groups_for_user.side_effect = RuntimeError("throttled")

    with patch("user_scan.fetch_inline_policies", return_value=[]), \
         patch("user_scan.fetch_attached_policies", return_value=[]):
        results = scan_users(iam, [_USER, _USER2])

    # Both fail at group-listing; both are warned and skipped
    assert results == []


# ---------------------------------------------------------------------------
# confidence and conditions
# ---------------------------------------------------------------------------

def test_scan_users_conditional_binding_is_low_confidence():
    with patch("user_scan.fetch_inline_policies", return_value=[_inline("CP", _CONDITIONAL_DOC)]), \
         patch("user_scan.fetch_attached_policies", return_value=[]):
        results = scan_users(_iam_no_groups(), [_USER])

    assert results[0]["confidence"] == CONFIDENCE_LOW
    assert results[0]["conditions"] == {"StringEquals": {"aws:RequestedRegion": "us-east-1"}}


def test_scan_users_multiple_users_accumulates():
    with patch("user_scan.fetch_inline_policies", return_value=[_inline("P", _INVOKE_DOC)]), \
         patch("user_scan.fetch_attached_policies", return_value=[]):
        results = scan_users(_iam_no_groups(), [_USER, _USER2])

    assert len(results) == 2
    assert {r["principalName"] for r in results} == {"alice", "bob"}
