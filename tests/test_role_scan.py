# tests/test_role_scan.py
from unittest.mock import MagicMock, patch

import pytest

from iam_policy import CONFIDENCE_LOW, CONFIDENCE_MEDIUM
from role_scan import scan_roles

# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

_ROLE = {"RoleName": "MyRole", "Arn": "arn:aws:iam::123456789012:role/MyRole"}
_ROLE2 = {"RoleName": "OtherRole", "Arn": "arn:aws:iam::123456789012:role/OtherRole"}

_MODEL_ARN = "arn:aws:bedrock:us-east-1::foundation-model/amazon.titan-text-express-v1"
_MODEL_ID = "amazon.titan-text-express-v1"
_POLICY_ARN = "arn:aws:iam::123456789012:policy/BedrockPolicy"

_INVOKE_STMT = {
    "Effect": "Allow",
    "Action": "bedrock:InvokeModel",
    "Resource": _MODEL_ARN,
}
_CONDITIONAL_STMT = {
    "Effect": "Allow",
    "Action": "bedrock:InvokeModel",
    "Resource": _MODEL_ARN,
    "Condition": {"StringEquals": {"aws:RequestedRegion": "us-east-1"}},
}
_DENY_STMT = {
    "Effect": "Deny",
    "Action": "bedrock:InvokeModel",
    "Resource": _MODEL_ARN,
}
_NON_BEDROCK_STMT = {
    "Effect": "Allow",
    "Action": "s3:GetObject",
    "Resource": "*",
}

_INVOKE_DOC = {"Version": "2012-10-17", "Statement": [_INVOKE_STMT]}
_EMPTY_DOC = {"Version": "2012-10-17", "Statement": []}


def _no_policies(iam_client, entity_type, entity_name):
    return []


# ---------------------------------------------------------------------------
# helpers to build fake policy lists
# ---------------------------------------------------------------------------

def _inline(name, document):
    return {"name": name, "document": document}


def _attached(name, arn, document):
    return {"name": name, "arn": arn, "document": document}


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------

def test_scan_roles_empty_role_list():
    with patch("role_scan.fetch_inline_policies", side_effect=_no_policies), \
         patch("role_scan.fetch_attached_policies", side_effect=_no_policies):
        assert scan_roles(MagicMock(), []) == []


def test_scan_roles_role_with_no_policies():
    with patch("role_scan.fetch_inline_policies", side_effect=_no_policies), \
         patch("role_scan.fetch_attached_policies", side_effect=_no_policies):
        assert scan_roles(MagicMock(), [_ROLE]) == []


def test_scan_roles_role_with_empty_policy_document():
    with patch("role_scan.fetch_inline_policies", return_value=[_inline("P", _EMPTY_DOC)]), \
         patch("role_scan.fetch_attached_policies", side_effect=_no_policies):
        assert scan_roles(MagicMock(), [_ROLE]) == []


def test_scan_roles_inline_binding_candidate_fields():
    with patch("role_scan.fetch_inline_policies", return_value=[_inline("MyPolicy", _INVOKE_DOC)]), \
         patch("role_scan.fetch_attached_policies", side_effect=_no_policies):
        results = scan_roles(MagicMock(), [_ROLE])

    assert len(results) == 1
    c = results[0]
    assert c["roleName"] == "MyRole"
    assert c["roleArn"] == _ROLE["Arn"]
    assert c["modelId"] == _MODEL_ID
    assert c["confidence"] == CONFIDENCE_MEDIUM
    assert c["conditions"] is None
    assert c["sourceTag"] == "inline:MyPolicy"


def test_scan_roles_attached_binding_candidate_fields():
    with patch("role_scan.fetch_inline_policies", side_effect=_no_policies), \
         patch("role_scan.fetch_attached_policies", return_value=[_attached("BP", _POLICY_ARN, _INVOKE_DOC)]):
        results = scan_roles(MagicMock(), [_ROLE])

    assert len(results) == 1
    c = results[0]
    assert c["roleName"] == "MyRole"
    assert c["roleArn"] == _ROLE["Arn"]
    assert c["modelId"] == _MODEL_ID
    assert c["confidence"] == CONFIDENCE_MEDIUM
    assert c["sourceTag"] == f"managed:{_POLICY_ARN}"


def test_scan_roles_inline_source_tag_format():
    with patch("role_scan.fetch_inline_policies", return_value=[_inline("InlinePolicy", _INVOKE_DOC)]), \
         patch("role_scan.fetch_attached_policies", side_effect=_no_policies):
        results = scan_roles(MagicMock(), [_ROLE])
    assert results[0]["sourceTag"] == "inline:InlinePolicy"


def test_scan_roles_managed_source_tag_uses_arn():
    with patch("role_scan.fetch_inline_policies", side_effect=_no_policies), \
         patch("role_scan.fetch_attached_policies", return_value=[_attached("BP", _POLICY_ARN, _INVOKE_DOC)]):
        results = scan_roles(MagicMock(), [_ROLE])
    assert results[0]["sourceTag"] == f"managed:{_POLICY_ARN}"


def test_scan_roles_non_bedrock_policy_emits_nothing():
    doc = {"Version": "2012-10-17", "Statement": [_NON_BEDROCK_STMT]}
    with patch("role_scan.fetch_inline_policies", return_value=[_inline("S3Policy", doc)]), \
         patch("role_scan.fetch_attached_policies", side_effect=_no_policies):
        assert scan_roles(MagicMock(), [_ROLE]) == []


def test_scan_roles_deny_statement_emits_nothing():
    doc = {"Version": "2012-10-17", "Statement": [_DENY_STMT]}
    with patch("role_scan.fetch_inline_policies", return_value=[_inline("DenyPolicy", doc)]), \
         patch("role_scan.fetch_attached_policies", side_effect=_no_policies):
        assert scan_roles(MagicMock(), [_ROLE]) == []


def test_scan_roles_multi_statement_only_matching_emitted():
    doc = {"Version": "2012-10-17", "Statement": [_NON_BEDROCK_STMT, _INVOKE_STMT, _DENY_STMT]}
    with patch("role_scan.fetch_inline_policies", return_value=[_inline("Mixed", doc)]), \
         patch("role_scan.fetch_attached_policies", side_effect=_no_policies):
        results = scan_roles(MagicMock(), [_ROLE])
    assert len(results) == 1
    assert results[0]["modelId"] == _MODEL_ID


def test_scan_roles_conditional_stmt_is_low_confidence():
    doc = {"Version": "2012-10-17", "Statement": [_CONDITIONAL_STMT]}
    with patch("role_scan.fetch_inline_policies", return_value=[_inline("CondPolicy", doc)]), \
         patch("role_scan.fetch_attached_policies", side_effect=_no_policies):
        results = scan_roles(MagicMock(), [_ROLE])
    assert results[0]["confidence"] == CONFIDENCE_LOW
    assert results[0]["conditions"] == {"StringEquals": {"aws:RequestedRegion": "us-east-1"}}


def test_scan_roles_wildcard_resource_yields_star_model_id():
    doc = {"Version": "2012-10-17", "Statement": [
        {"Effect": "Allow", "Action": "bedrock:*", "Resource": "*"}
    ]}
    with patch("role_scan.fetch_inline_policies", return_value=[_inline("WildPolicy", doc)]), \
         patch("role_scan.fetch_attached_policies", side_effect=_no_policies):
        results = scan_roles(MagicMock(), [_ROLE])
    assert results[0]["modelId"] == "*"


def test_scan_roles_per_role_failure_warns_and_continues():
    def inline_side_effect(iam_client, entity_type, entity_name):
        if entity_name == "MyRole":
            raise RuntimeError("access denied")
        return [_inline("P", _INVOKE_DOC)]

    with patch("role_scan.fetch_inline_policies", side_effect=inline_side_effect), \
         patch("role_scan.fetch_attached_policies", side_effect=_no_policies):
        results = scan_roles(MagicMock(), [_ROLE, _ROLE2])

    assert len(results) == 1
    assert results[0]["roleName"] == "OtherRole"


def test_scan_roles_multiple_roles_accumulates_all():
    with patch("role_scan.fetch_inline_policies", return_value=[_inline("P", _INVOKE_DOC)]), \
         patch("role_scan.fetch_attached_policies", side_effect=_no_policies):
        results = scan_roles(MagicMock(), [_ROLE, _ROLE2])

    assert len(results) == 2
    assert {r["roleName"] for r in results} == {"MyRole", "OtherRole"}


def test_scan_roles_both_inline_and_attached_accumulates():
    arn2 = "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-v2"
    attached_doc = {"Version": "2012-10-17", "Statement": [{
        "Effect": "Allow", "Action": "bedrock:Converse", "Resource": arn2,
    }]}
    with patch("role_scan.fetch_inline_policies", return_value=[_inline("IP", _INVOKE_DOC)]), \
         patch("role_scan.fetch_attached_policies", return_value=[_attached("MP", _POLICY_ARN, attached_doc)]):
        results = scan_roles(MagicMock(), [_ROLE])

    assert len(results) == 2
    model_ids = {r["modelId"] for r in results}
    assert _MODEL_ID in model_ids
    assert "anthropic.claude-v2" in model_ids
