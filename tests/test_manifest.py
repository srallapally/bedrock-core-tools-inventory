# tests/test_manifest.py
import datetime

from manifest import build_manifest

# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

_FIXED_NOW = datetime.datetime(2026, 4, 20, 12, 34, 56)

_CFG = {"account_id": "123456789012", "region": "us-east-1"}

_MODEL = {"modelId": "amazon.titan-text-express-v1"}

def _binding(model_id="amazon.titan-text-express-v1", conditions=None):
    return {"modelId": model_id, "conditions": conditions}

_PRINCIPAL = {"principalArn": "arn:aws:iam::123456789012:role/MyRole"}
_CREDENTIAL = {"id": "tc-abc", "agentId": "a1"}


def _build(**kwargs):
    defaults = dict(
        cfg=_CFG,
        models=[_MODEL],
        bindings=[_binding()],
        tool_credentials=[_CREDENTIAL],
        principals=[_PRINCIPAL],
        now=_FIXED_NOW,
    )
    defaults.update(kwargs)
    return build_manifest(**defaults)


# ---------------------------------------------------------------------------
# fixed string fields
# ---------------------------------------------------------------------------

def test_schema_version_is_1_0():
    assert _build()["schemaVersion"] == "1.0"


def test_platform_is_aws_bedrock_core():
    assert _build()["platform"] == "aws-bedrock-core"


# ---------------------------------------------------------------------------
# config fields
# ---------------------------------------------------------------------------

def test_account_id_from_cfg():
    assert _build()["accountId"] == "123456789012"


def test_region_from_cfg():
    assert _build()["region"] == "us-east-1"


# ---------------------------------------------------------------------------
# generatedAt
# ---------------------------------------------------------------------------

def test_generated_at_is_iso8601_utc():
    assert _build()["generatedAt"] == "2026-04-20T12:34:56Z"


def test_generated_at_injectable():
    t1 = datetime.datetime(2026, 1, 1, 0, 0, 0)
    t2 = datetime.datetime(2026, 6, 15, 8, 30, 0)
    assert _build(now=t1)["generatedAt"] == "2026-01-01T00:00:00Z"
    assert _build(now=t2)["generatedAt"] == "2026-06-15T08:30:00Z"


# ---------------------------------------------------------------------------
# count fields
# ---------------------------------------------------------------------------

def test_model_count():
    assert _build(models=[_MODEL, _MODEL])["modelCount"] == 2


def test_model_count_zero():
    assert _build(models=[])["modelCount"] == 0


def test_model_binding_count():
    assert _build(bindings=[_binding(), _binding()])["modelBindingCount"] == 2


def test_model_binding_count_zero():
    m = _build(bindings=[])
    assert m["modelBindingCount"] == 0


def test_agent_tool_credential_count():
    assert _build(tool_credentials=[_CREDENTIAL, _CREDENTIAL])["agentToolCredentialCount"] == 2


def test_principal_count():
    assert _build(principals=[_PRINCIPAL, _PRINCIPAL])["principalCount"] == 2


# ---------------------------------------------------------------------------
# wildcardBindingCount
# ---------------------------------------------------------------------------

def test_wildcard_count_zero_for_specific_models():
    m = _build(bindings=[_binding("amazon.titan-text-express-v1")])
    assert m["wildcardBindingCount"] == 0


def test_wildcard_count_for_bare_star():
    m = _build(bindings=[_binding("*")])
    assert m["wildcardBindingCount"] == 1


def test_wildcard_count_for_prefix_wildcard():
    m = _build(bindings=[_binding("amazon.titan-*")])
    assert m["wildcardBindingCount"] == 1


def test_wildcard_count_mixed():
    m = _build(bindings=[
        _binding("specific-model"),
        _binding("*"),
        _binding("amazon.titan-*"),
    ])
    assert m["wildcardBindingCount"] == 2


# ---------------------------------------------------------------------------
# conditionalBindingCount
# ---------------------------------------------------------------------------

def test_conditional_count_zero_when_no_conditions():
    m = _build(bindings=[_binding(conditions=None)])
    assert m["conditionalBindingCount"] == 0


def test_conditional_count_for_binding_with_conditions():
    cond = {"StringEquals": {"aws:RequestedRegion": "us-east-1"}}
    m = _build(bindings=[_binding(conditions=cond)])
    assert m["conditionalBindingCount"] == 1


def test_conditional_count_mixed():
    cond = {"StringEquals": {"k": "v"}}
    m = _build(bindings=[_binding(conditions=None), _binding(conditions=cond)])
    assert m["conditionalBindingCount"] == 1


# ---------------------------------------------------------------------------
# warnings
# ---------------------------------------------------------------------------

def test_no_warnings_when_clean():
    m = _build(
        bindings=[_binding("specific-model", conditions=None)],
    )
    assert m["warnings"] == []


def test_warning_no_model_bindings_found():
    m = _build(bindings=[])
    assert "NO_MODEL_BINDINGS_FOUND" in m["warnings"]


def test_no_empty_binding_warning_when_bindings_exist():
    m = _build(bindings=[_binding()])
    assert "NO_MODEL_BINDINGS_FOUND" not in m["warnings"]


def test_warning_wildcard_bindings_present():
    m = _build(bindings=[_binding("*")])
    assert "WILDCARD_BINDINGS_PRESENT" in m["warnings"]


def test_no_wildcard_warning_when_no_wildcards():
    m = _build(bindings=[_binding("specific-model")])
    assert "WILDCARD_BINDINGS_PRESENT" not in m["warnings"]


def test_warning_conditional_bindings_present():
    cond = {"StringEquals": {"k": "v"}}
    m = _build(bindings=[_binding(conditions=cond)])
    assert "CONDITIONAL_BINDINGS_PRESENT" in m["warnings"]


def test_no_conditional_warning_when_no_conditions():
    m = _build(bindings=[_binding(conditions=None)])
    assert "CONDITIONAL_BINDINGS_PRESENT" not in m["warnings"]


def test_all_three_warnings_together():
    cond = {"StringEquals": {"k": "v"}}
    m = _build(bindings=[_binding("*", conditions=cond)])
    assert "WILDCARD_BINDINGS_PRESENT" in m["warnings"]
    assert "CONDITIONAL_BINDINGS_PRESENT" in m["warnings"]
    assert "NO_MODEL_BINDINGS_FOUND" not in m["warnings"]


def test_extra_warnings_appended():
    m = _build(
        bindings=[_binding()],
        extra_warnings=["AGENT_SCAN_PARTIAL_FAILURE"],
    )
    assert "AGENT_SCAN_PARTIAL_FAILURE" in m["warnings"]


def test_extra_warnings_none_safe():
    m = _build(extra_warnings=None)
    assert isinstance(m["warnings"], list)


def test_extra_warnings_after_derived_warnings():
    cond = {"StringEquals": {"k": "v"}}
    m = _build(
        bindings=[_binding(conditions=cond)],
        extra_warnings=["CUSTOM_WARNING"],
    )
    assert m["warnings"][-1] == "CUSTOM_WARNING"


# ---------------------------------------------------------------------------
# artifacts sub-object
# ---------------------------------------------------------------------------

def test_artifacts_keys():
    m = _build()
    assert set(m["artifacts"].keys()) == {
        "models.json",
        "model-bindings.json",
        "agent-tool-credentials.json",
        "principals.json",
        "manifest.json",
    }


def test_artifacts_counts_match_top_level():
    m = _build(
        models=[_MODEL, _MODEL],
        bindings=[_binding(), _binding(), _binding()],
        tool_credentials=[_CREDENTIAL],
        principals=[_PRINCIPAL, _PRINCIPAL],
    )
    assert m["artifacts"]["models.json"] == m["modelCount"]
    assert m["artifacts"]["model-bindings.json"] == m["modelBindingCount"]
    assert m["artifacts"]["agent-tool-credentials.json"] == m["agentToolCredentialCount"]
    assert m["artifacts"]["principals.json"] == m["principalCount"]
    assert m["artifacts"]["manifest.json"] == 1


# ---------------------------------------------------------------------------
# all fields present
# ---------------------------------------------------------------------------

_EXPECTED_FIELDS = {
    "generatedAt", "schemaVersion", "platform",
    "accountId", "region",
    "modelCount", "modelBindingCount",
    "wildcardBindingCount", "conditionalBindingCount",
    "agentToolCredentialCount", "principalCount",
    "warnings", "artifacts",
}


def test_all_fields_present():
    assert set(_build().keys()) == _EXPECTED_FIELDS
