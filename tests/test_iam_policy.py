# tests/test_iam_policy.py
import pytest

from iam_policy import (
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    _INVOKE_ACTIONS,
    action_matches,
    allows_bedrock_invoke,
    derive_confidence,
    derive_source_tag,
    extract_model_bindings,
    is_wildcard_resource,
    parse_model_id_from_arn,
    serialize_conditions,
)

# ---------------------------------------------------------------------------
# action_matches
# ---------------------------------------------------------------------------

def test_action_matches_exact():
    assert action_matches("bedrock:InvokeModel", "bedrock:InvokeModel")


def test_action_matches_case_insensitive():
    assert action_matches("Bedrock:INVOKEMODEL", "bedrock:invokemodel")
    assert action_matches("bedrock:invokemodel", "BEDROCK:InvokeModel")


def test_action_matches_asterisk_wildcard():
    assert action_matches("bedrock:*", "bedrock:InvokeModel")
    assert action_matches("bedrock:*", "bedrock:Converse")
    assert action_matches("*", "bedrock:InvokeModel")
    assert action_matches("*", "s3:GetObject")


def test_action_matches_prefix_wildcard():
    assert action_matches("bedrock:Invoke*", "bedrock:InvokeModel")
    assert action_matches("bedrock:Invoke*", "bedrock:InvokeModelWithResponseStream")
    assert not action_matches("bedrock:Invoke*", "bedrock:Converse")


def test_action_matches_question_mark():
    assert action_matches("bedrock:Convers?", "bedrock:Converse")
    assert not action_matches("bedrock:Convers?", "bedrock:ConverseStream")


def test_action_matches_no_match():
    assert not action_matches("bedrock:ListFoundationModels", "bedrock:InvokeModel")
    assert not action_matches("s3:*", "bedrock:InvokeModel")


# ---------------------------------------------------------------------------
# allows_bedrock_invoke
# ---------------------------------------------------------------------------

def test_allows_bedrock_invoke_each_action():
    for action in [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream",
        "bedrock:Converse",
        "bedrock:ConverseStream",
    ]:
        assert allows_bedrock_invoke(action), f"expected True for {action}"


def test_allows_bedrock_invoke_string_input():
    assert allows_bedrock_invoke("bedrock:InvokeModel")


def test_allows_bedrock_invoke_list_input():
    assert allows_bedrock_invoke(["bedrock:InvokeModel"])


def test_allows_bedrock_invoke_bedrock_wildcard():
    assert allows_bedrock_invoke("bedrock:*")
    assert allows_bedrock_invoke(["bedrock:*"])


def test_allows_bedrock_invoke_global_wildcard():
    assert allows_bedrock_invoke("*")
    assert allows_bedrock_invoke(["*"])


def test_allows_bedrock_invoke_prefix_wildcard():
    assert allows_bedrock_invoke("bedrock:Invoke*")
    assert allows_bedrock_invoke("bedrock:Convers*")


def test_allows_bedrock_invoke_mixed_list_true():
    assert allows_bedrock_invoke(["bedrock:ListFoundationModels", "bedrock:InvokeModel"])


def test_allows_bedrock_invoke_non_invoke_bedrock_action():
    assert not allows_bedrock_invoke("bedrock:ListFoundationModels")
    assert not allows_bedrock_invoke(["bedrock:GetFoundationModel"])


def test_allows_bedrock_invoke_unrelated_service():
    assert not allows_bedrock_invoke("s3:GetObject")
    assert not allows_bedrock_invoke(["s3:*", "iam:*"])


def test_allows_bedrock_invoke_empty_list():
    assert not allows_bedrock_invoke([])


# ---------------------------------------------------------------------------
# parse_model_id_from_arn
# ---------------------------------------------------------------------------

def test_parse_bare_wildcard():
    assert parse_model_id_from_arn("*") == "*"


def test_parse_specific_model_arn():
    arn = "arn:aws:bedrock:us-east-1::foundation-model/amazon.titan-text-express-v1"
    assert parse_model_id_from_arn(arn) == "amazon.titan-text-express-v1"


def test_parse_all_models_arn():
    arn = "arn:aws:bedrock:us-east-1::foundation-model/*"
    assert parse_model_id_from_arn(arn) == "*"


def test_parse_wildcard_region_arn():
    arn = "arn:aws:bedrock:*::foundation-model/*"
    assert parse_model_id_from_arn(arn) == "*"


def test_parse_partial_wildcard_model():
    arn = "arn:aws:bedrock:us-east-1::foundation-model/amazon.titan-*"
    assert parse_model_id_from_arn(arn) == "amazon.titan-*"


def test_parse_non_model_arn_returns_none():
    assert parse_model_id_from_arn("arn:aws:iam::123456789012:role/MyRole") is None
    assert parse_model_id_from_arn("arn:aws:s3:::my-bucket") is None


def test_parse_empty_string_returns_none():
    assert parse_model_id_from_arn("") is None


# ---------------------------------------------------------------------------
# is_wildcard_resource
# ---------------------------------------------------------------------------

def test_is_wildcard_bare_star():
    assert is_wildcard_resource("*")


def test_is_wildcard_all_models_arn():
    assert is_wildcard_resource("arn:aws:bedrock:us-east-1::foundation-model/*")
    assert is_wildcard_resource("arn:aws:bedrock:*::foundation-model/*")


def test_is_wildcard_specific_model_is_false():
    arn = "arn:aws:bedrock:us-east-1::foundation-model/amazon.titan-text-express-v1"
    assert not is_wildcard_resource(arn)


def test_is_wildcard_partial_wildcard_is_false():
    arn = "arn:aws:bedrock:us-east-1::foundation-model/amazon.titan-*"
    assert not is_wildcard_resource(arn)


def test_is_wildcard_non_model_arn_is_false():
    assert not is_wildcard_resource("arn:aws:iam::123:role/MyRole")


# ---------------------------------------------------------------------------
# serialize_conditions
# ---------------------------------------------------------------------------

def test_serialize_conditions_none():
    assert serialize_conditions(None) is None


def test_serialize_conditions_empty_dict():
    assert serialize_conditions({}) is None


def test_serialize_conditions_returns_copy():
    original = {"StringEquals": {"aws:RequestedRegion": "us-east-1"}}
    result = serialize_conditions(original)
    assert result == original
    assert result is not original  # shallow copy


def test_serialize_conditions_preserves_nested_structure():
    cond = {
        "StringEquals": {"aws:PrincipalTag/Department": "Engineering"},
        "Bool": {"aws:MultiFactorAuthPresent": "true"},
    }
    assert serialize_conditions(cond) == cond


# ---------------------------------------------------------------------------
# derive_confidence
# ---------------------------------------------------------------------------

def test_derive_confidence_no_condition():
    assert derive_confidence({"Effect": "Allow", "Action": "*", "Resource": "*"}) == CONFIDENCE_MEDIUM


def test_derive_confidence_condition_absent_key():
    assert derive_confidence({}) == CONFIDENCE_MEDIUM


def test_derive_confidence_empty_condition():
    # Empty dict is falsy — treated as no condition
    assert derive_confidence({"Condition": {}}) == CONFIDENCE_MEDIUM


def test_derive_confidence_with_condition():
    stmt = {
        "Effect": "Allow",
        "Condition": {"StringEquals": {"aws:RequestedRegion": "us-east-1"}},
    }
    assert derive_confidence(stmt) == CONFIDENCE_LOW


# ---------------------------------------------------------------------------
# derive_source_tag
# ---------------------------------------------------------------------------

def test_derive_source_tag_inline():
    assert derive_source_tag("inline", "MyInlinePolicy") == "inline:MyInlinePolicy"


def test_derive_source_tag_managed():
    arn = "arn:aws:iam::123456789012:policy/MyManagedPolicy"
    assert derive_source_tag("managed", arn) == f"managed:{arn}"


def test_derive_source_tag_aws_managed():
    assert derive_source_tag("aws-managed", "AmazonBedrockFullAccess") == "aws-managed:AmazonBedrockFullAccess"


# ---------------------------------------------------------------------------
# extract_model_bindings
# ---------------------------------------------------------------------------

def test_extract_bindings_deny_returns_empty():
    stmt = {
        "Effect": "Deny",
        "Action": "bedrock:InvokeModel",
        "Resource": "*",
    }
    assert extract_model_bindings(stmt) == []


def test_extract_bindings_missing_effect_returns_empty():
    stmt = {"Action": "bedrock:InvokeModel", "Resource": "*"}
    assert extract_model_bindings(stmt) == []


def test_extract_bindings_non_invoke_action_returns_empty():
    stmt = {
        "Effect": "Allow",
        "Action": "bedrock:ListFoundationModels",
        "Resource": "*",
    }
    assert extract_model_bindings(stmt) == []


def test_extract_bindings_notaction_skipped():
    # NotAction is not under "Action" key — conservatively returns nothing
    stmt = {
        "Effect": "Allow",
        "NotAction": "bedrock:InvokeModel",
        "Resource": "*",
    }
    assert extract_model_bindings(stmt) == []


def test_extract_bindings_non_model_resource_skipped():
    stmt = {
        "Effect": "Allow",
        "Action": "bedrock:InvokeModel",
        "Resource": "arn:aws:iam::123:role/MyRole",
    }
    assert extract_model_bindings(stmt) == []


def test_extract_bindings_specific_model():
    arn = "arn:aws:bedrock:us-east-1::foundation-model/amazon.titan-text-express-v1"
    stmt = {
        "Effect": "Allow",
        "Action": "bedrock:InvokeModel",
        "Resource": arn,
    }
    bindings = extract_model_bindings(stmt)
    assert len(bindings) == 1
    assert bindings[0]["modelId"] == "amazon.titan-text-express-v1"
    assert bindings[0]["confidence"] == CONFIDENCE_MEDIUM
    assert bindings[0]["conditions"] is None


def test_extract_bindings_bare_wildcard_resource():
    stmt = {"Effect": "Allow", "Action": "bedrock:*", "Resource": "*"}
    bindings = extract_model_bindings(stmt)
    assert len(bindings) == 1
    assert bindings[0]["modelId"] == "*"


def test_extract_bindings_all_models_arn():
    stmt = {
        "Effect": "Allow",
        "Action": "bedrock:InvokeModel",
        "Resource": "arn:aws:bedrock:*::foundation-model/*",
    }
    bindings = extract_model_bindings(stmt)
    assert len(bindings) == 1
    assert bindings[0]["modelId"] == "*"


def test_extract_bindings_with_condition_is_low():
    stmt = {
        "Effect": "Allow",
        "Action": "bedrock:Converse",
        "Resource": "*",
        "Condition": {"StringEquals": {"aws:RequestedRegion": "us-east-1"}},
    }
    bindings = extract_model_bindings(stmt)
    assert bindings[0]["confidence"] == CONFIDENCE_LOW
    assert bindings[0]["conditions"] == {"StringEquals": {"aws:RequestedRegion": "us-east-1"}}


def test_extract_bindings_multiple_resources():
    arn1 = "arn:aws:bedrock:us-east-1::foundation-model/amazon.titan-text-express-v1"
    arn2 = "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-v2"
    stmt = {
        "Effect": "Allow",
        "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
        "Resource": [arn1, arn2],
    }
    bindings = extract_model_bindings(stmt)
    model_ids = [b["modelId"] for b in bindings]
    assert len(bindings) == 2
    assert "amazon.titan-text-express-v1" in model_ids
    assert "anthropic.claude-v2" in model_ids


def test_extract_bindings_mixed_resources_skips_non_model():
    model_arn = "arn:aws:bedrock:us-east-1::foundation-model/amazon.titan-text-express-v1"
    stmt = {
        "Effect": "Allow",
        "Action": "bedrock:InvokeModel",
        "Resource": [model_arn, "arn:aws:s3:::my-bucket"],
    }
    bindings = extract_model_bindings(stmt)
    assert len(bindings) == 1
    assert bindings[0]["modelId"] == "amazon.titan-text-express-v1"


def test_extract_bindings_action_as_string():
    stmt = {
        "Effect": "Allow",
        "Action": "bedrock:InvokeModel",
        "Resource": "arn:aws:bedrock:us-east-1::foundation-model/model-x",
    }
    bindings = extract_model_bindings(stmt)
    assert len(bindings) == 1


def test_extract_bindings_resource_as_string():
    arn = "arn:aws:bedrock:us-east-1::foundation-model/model-x"
    stmt = {"Effect": "Allow", "Action": ["bedrock:InvokeModel"], "Resource": arn}
    bindings = extract_model_bindings(stmt)
    assert len(bindings) == 1
