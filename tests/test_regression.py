# tests/test_regression.py
"""
Fixture-based regression tests.

Uses a realistic multi-role / multi-user / multi-agent scenario with fixed
inputs to verify deterministic IDs, correct deduplication, and cross-artifact
consistency across all five artifact payloads.

Scenario summary
----------------
Roles:
  DataScienceRole  → amazon.titan-text-express-v1  (inline:BedrockPolicy)       MEDIUM
  DataScienceRole  → anthropic.claude-v2           (managed:ClaudeAccess)        MEDIUM
  MLEngineerRole   → *                             (managed:AllBedrockModels)    MEDIUM  [wildcard]

Users:
  alice  direct    → anthropic.claude-v2           (inline:ClaudeConditionalPolicy) LOW  [conditional]
  alice  direct    → amazon.titan-text-express-v1  (inline:TitanPolicy)          MEDIUM
  alice  direct    → amazon.titan-text-express-v1  (inline:TitanPolicy)          MEDIUM  [DUPLICATE → deduped]
  bob    via MLTeam→ *                             (inline:MLTeamBedrockPolicy)   MEDIUM  [wildcard]

After dedup: 6 bindings, 2 wildcards, 1 conditional, 4 principals.

Agents:
  SearchAgent / AG001  – lambda executor          → LAMBDA_EXECUTION_ROLE
  DataAgent   / AG002  – lambda + Confluence      → CONFLUENCE_SECRET
  DataAgent   / AG003  – RETURN_CONTROL + payload → NONE  (apiSchemaSource=INLINE)
"""
import datetime

from iam_policy import CONFIDENCE_LOW, CONFIDENCE_MEDIUM
from manifest import build_manifest
from normalize import normalize_bindings
from tool_credentials import normalize_tool_credentials

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ACCOUNT = "123456789012"
_REGION = "us-east-1"
_FIXED_NOW = datetime.datetime(2026, 4, 20, 12, 0, 0)
_CFG = {"account_id": _ACCOUNT, "region": _REGION}

_ROLE_DS = f"arn:aws:iam::{_ACCOUNT}:role/DataScienceRole"
_ROLE_ML = f"arn:aws:iam::{_ACCOUNT}:role/MLEngineerRole"
_USER_ALICE = f"arn:aws:iam::{_ACCOUNT}:user/alice"
_USER_BOB = f"arn:aws:iam::{_ACCOUNT}:user/bob"
_GROUP_MLTEAM = f"arn:aws:iam::{_ACCOUNT}:group/MLTeam"
_POLICY_CLAUDE = f"arn:aws:iam::{_ACCOUNT}:policy/ClaudeAccess"
_POLICY_ALL = f"arn:aws:iam::{_ACCOUNT}:policy/AllBedrockModels"
_SECRET_ARN = f"arn:aws:secretsmanager:{_REGION}:{_ACCOUNT}:secret:confluence-creds"
_LAMBDA_SEARCH = f"arn:aws:lambda:{_REGION}:{_ACCOUNT}:function:SearchTool"
_LAMBDA_CONFLUENCE = f"arn:aws:lambda:{_REGION}:{_ACCOUNT}:function:ConfluenceTool"

# ---------------------------------------------------------------------------
# Models fixture — realistic normalized output of collect_models
# ---------------------------------------------------------------------------

_MODELS = [
    {
        "modelId": "amazon.titan-text-express-v1",
        "modelName": "Titan Text Express",
        "providerName": "Amazon",
        "inputModalities": ["TEXT"],
        "outputModalities": ["TEXT"],
        "responseStreamingSupported": True,
        "customizationsSupported": [],
        "inferenceTypesSupported": ["ON_DEMAND"],
        "modelLifecycle": {"status": "ACTIVE"},
    },
    {
        "modelId": "anthropic.claude-v2",
        "modelName": "Claude 2",
        "providerName": "Anthropic",
        "inputModalities": ["TEXT"],
        "outputModalities": ["TEXT"],
        "responseStreamingSupported": True,
        "customizationsSupported": [],
        "inferenceTypesSupported": ["ON_DEMAND"],
        "modelLifecycle": {"status": "ACTIVE"},
    },
    {
        "modelId": "meta.llama2-13b-chat-v1",
        "modelName": "Llama 2 Chat 13B",
        "providerName": "Meta",
        "inputModalities": ["TEXT"],
        "outputModalities": ["TEXT"],
        "responseStreamingSupported": False,
        "customizationsSupported": [],
        "inferenceTypesSupported": ["ON_DEMAND"],
        "modelLifecycle": {"status": "ACTIVE"},
    },
]

# ---------------------------------------------------------------------------
# IAM binding candidates
# ---------------------------------------------------------------------------

_ROLE_CANDIDATES = [
    {
        "roleName": "DataScienceRole",
        "roleArn": _ROLE_DS,
        "modelId": "amazon.titan-text-express-v1",
        "confidence": CONFIDENCE_MEDIUM,
        "conditions": None,
        "sourceTag": "inline:BedrockPolicy",
    },
    {
        "roleName": "DataScienceRole",
        "roleArn": _ROLE_DS,
        "modelId": "anthropic.claude-v2",
        "confidence": CONFIDENCE_MEDIUM,
        "conditions": None,
        "sourceTag": f"managed:{_POLICY_CLAUDE}",
    },
    {
        "roleName": "MLEngineerRole",
        "roleArn": _ROLE_ML,
        "modelId": "*",
        "confidence": CONFIDENCE_MEDIUM,
        "conditions": None,
        "sourceTag": f"managed:{_POLICY_ALL}",
    },
]

_USER_CANDIDATES = [
    # alice — conditional grant on claude (LOW confidence)
    {
        "principalType": "user",
        "principalName": "alice",
        "principalArn": _USER_ALICE,
        "sourcePrincipalType": "user",
        "sourcePrincipalName": "alice",
        "sourcePrincipalArn": _USER_ALICE,
        "modelId": "anthropic.claude-v2",
        "confidence": CONFIDENCE_LOW,
        "conditions": {"StringEquals": {"aws:RequestedRegion": "us-east-1"}},
        "sourceTag": "inline:ClaudeConditionalPolicy",
    },
    # alice — direct titan grant
    {
        "principalType": "user",
        "principalName": "alice",
        "principalArn": _USER_ALICE,
        "sourcePrincipalType": "user",
        "sourcePrincipalName": "alice",
        "sourcePrincipalArn": _USER_ALICE,
        "modelId": "amazon.titan-text-express-v1",
        "confidence": CONFIDENCE_MEDIUM,
        "conditions": None,
        "sourceTag": "inline:TitanPolicy",
    },
    # alice — exact duplicate of the entry above; must be collapsed to one binding
    {
        "principalType": "user",
        "principalName": "alice",
        "principalArn": _USER_ALICE,
        "sourcePrincipalType": "user",
        "sourcePrincipalName": "alice",
        "sourcePrincipalArn": _USER_ALICE,
        "modelId": "amazon.titan-text-express-v1",
        "confidence": CONFIDENCE_MEDIUM,
        "conditions": None,
        "sourceTag": "inline:TitanPolicy",
    },
    # bob — wildcard via MLTeam group; sourcePrincipalArn differs from principalArn
    {
        "principalType": "user",
        "principalName": "bob",
        "principalArn": _USER_BOB,
        "sourcePrincipalType": "group",
        "sourcePrincipalName": "MLTeam",
        "sourcePrincipalArn": _GROUP_MLTEAM,
        "modelId": "*",
        "confidence": CONFIDENCE_MEDIUM,
        "conditions": None,
        "sourceTag": "inline:MLTeamBedrockPolicy",
    },
]

# ---------------------------------------------------------------------------
# Agents fixture — realistic output of collect_agents
# ---------------------------------------------------------------------------

_AGENTS = [
    {
        "agentId": "AGENT001",
        "agentName": "SearchAgent",
        "agentArn": f"arn:aws:bedrock:{_REGION}:{_ACCOUNT}:agent/AGENT001",
        "agentStatus": "PREPARED",
        "agentServiceRoleArn": f"arn:aws:iam::{_ACCOUNT}:role/AmazonBedrockExecutionRole",
        "actionGroups": [
            {
                "actionGroupId": "AG001",
                "actionGroupName": "SearchTool",
                "actionGroupState": "ENABLED",
                "actionGroupExecutor": {"lambda": _LAMBDA_SEARCH},
            },
        ],
    },
    {
        "agentId": "AGENT002",
        "agentName": "DataAgent",
        "agentArn": f"arn:aws:bedrock:{_REGION}:{_ACCOUNT}:agent/AGENT002",
        "agentStatus": "PREPARED",
        "agentServiceRoleArn": f"arn:aws:iam::{_ACCOUNT}:role/AmazonBedrockExecutionRole",
        "actionGroups": [
            {
                "actionGroupId": "AG002",
                "actionGroupName": "ConfluenceTool",
                "actionGroupState": "ENABLED",
                "actionGroupExecutor": {"lambda": _LAMBDA_CONFLUENCE},
                "confluenceConfiguration": {
                    "sourceConfiguration": {"credentialsSecretArn": _SECRET_ARN}
                },
            },
            {
                "actionGroupId": "AG003",
                "actionGroupName": "InlineSchemaTool",
                "actionGroupState": "ENABLED",
                "actionGroupExecutor": {"customControl": "RETURN_CONTROL"},
                "apiSchema": {"payload": "openapi: 3.0.0\ninfo:\n  title: test\n"},
            },
        ],
    },
]

# ---------------------------------------------------------------------------
# Derived outputs — computed once from the fixtures above
# ---------------------------------------------------------------------------

_BINDINGS, _PRINCIPALS = normalize_bindings(_ROLE_CANDIDATES, _USER_CANDIDATES)
_TOOL_CREDENTIALS = normalize_tool_credentials(_AGENTS, _ACCOUNT, _REGION)
_MANIFEST = build_manifest(
    _CFG, _MODELS, _BINDINGS, _TOOL_CREDENTIALS, _PRINCIPALS, now=_FIXED_NOW
)

# ---------------------------------------------------------------------------
# Cross-artifact consistency
# ---------------------------------------------------------------------------

def test_manifest_model_count_matches_models_list():
    assert _MANIFEST["modelCount"] == len(_MODELS)


def test_manifest_binding_count_matches_bindings_list():
    assert _MANIFEST["modelBindingCount"] == len(_BINDINGS)


def test_manifest_credential_count_matches_tool_credentials_list():
    assert _MANIFEST["agentToolCredentialCount"] == len(_TOOL_CREDENTIALS)


def test_manifest_principal_count_matches_principals_list():
    assert _MANIFEST["principalCount"] == len(_PRINCIPALS)


def test_manifest_artifacts_subdict_consistent_with_lists():
    art = _MANIFEST["artifacts"]
    assert art["models.json"] == len(_MODELS)
    assert art["model-bindings.json"] == len(_BINDINGS)
    assert art["agent-tool-credentials.json"] == len(_TOOL_CREDENTIALS)
    assert art["principals.json"] == len(_PRINCIPALS)
    assert art["manifest.json"] == 1


def test_all_binding_principal_arns_appear_in_principals():
    principal_arns = {p["principalArn"] for p in _PRINCIPALS}
    for b in _BINDINGS:
        assert b["principalArn"] in principal_arns


def test_principal_metadata_consistent_across_bindings():
    """All bindings for a given principalArn carry the same type and name."""
    seen = {}
    for b in _BINDINGS:
        arn = b["principalArn"]
        meta = (b["principalType"], b["principalName"])
        if arn in seen:
            assert seen[arn] == meta
        else:
            seen[arn] = meta


def test_manifest_wildcard_count_matches_bindings():
    expected = sum(1 for b in _BINDINGS if "*" in b.get("modelId", ""))
    assert _MANIFEST["wildcardBindingCount"] == expected


def test_manifest_conditional_count_matches_bindings():
    expected = sum(1 for b in _BINDINGS if b.get("conditions") is not None)
    assert _MANIFEST["conditionalBindingCount"] == expected


def test_no_duplicate_binding_ids():
    ids = [b["bindingId"] for b in _BINDINGS]
    assert len(ids) == len(set(ids))


def test_no_duplicate_principal_arns_in_principals():
    arns = [p["principalArn"] for p in _PRINCIPALS]
    assert len(arns) == len(set(arns))


def test_no_duplicate_tool_credential_ids():
    ids = [tc["id"] for tc in _TOOL_CREDENTIALS]
    assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

def test_bindings_are_deterministic():
    b1, _ = normalize_bindings(_ROLE_CANDIDATES, _USER_CANDIDATES)
    b2, _ = normalize_bindings(_ROLE_CANDIDATES, _USER_CANDIDATES)
    assert b1 == b2


def test_principals_are_deterministic():
    _, p1 = normalize_bindings(_ROLE_CANDIDATES, _USER_CANDIDATES)
    _, p2 = normalize_bindings(_ROLE_CANDIDATES, _USER_CANDIDATES)
    assert p1 == p2


def test_tool_credential_ids_are_deterministic():
    tc1 = normalize_tool_credentials(_AGENTS, _ACCOUNT, _REGION)
    tc2 = normalize_tool_credentials(_AGENTS, _ACCOUNT, _REGION)
    assert [tc["id"] for tc in tc1] == [tc["id"] for tc in tc2]


def test_manifest_generated_at_uses_injected_time():
    m = build_manifest(
        _CFG, _MODELS, _BINDINGS, _TOOL_CREDENTIALS, _PRINCIPALS, now=_FIXED_NOW
    )
    assert m["generatedAt"] == "2026-04-20T12:00:00Z"


# ---------------------------------------------------------------------------
# Expected values derived from the known fixture scenario
# ---------------------------------------------------------------------------

def test_duplicate_entry_is_deduped_to_six_bindings():
    # 3 role + 4 user inputs, 1 duplicate user entry → 6 unique bindings
    assert len(_BINDINGS) == 6


def test_two_wildcard_bindings():
    # MLEngineerRole→* and bob→* are the only wildcards
    assert _MANIFEST["wildcardBindingCount"] == 2


def test_one_conditional_binding():
    # Only alice's claude grant carries a Condition
    assert _MANIFEST["conditionalBindingCount"] == 1


def test_four_principals():
    # DataScienceRole, MLEngineerRole, alice, bob
    assert len(_PRINCIPALS) == 4


def test_three_tool_credentials():
    # AG001 + AG002 + AG003
    assert len(_TOOL_CREDENTIALS) == 3


def test_three_models():
    assert _MANIFEST["modelCount"] == 3


def test_group_source_not_listed_as_principal():
    """MLTeam grants bob access but is not itself a principal."""
    principal_arns = {p["principalArn"] for p in _PRINCIPALS}
    assert _GROUP_MLTEAM not in principal_arns
    assert _USER_BOB in principal_arns


def test_alice_appears_exactly_once_in_principals():
    entries = [p for p in _PRINCIPALS if p["principalArn"] == _USER_ALICE]
    assert len(entries) == 1


def test_principals_sorted_by_arn():
    arns = [p["principalArn"] for p in _PRINCIPALS]
    assert arns == sorted(arns)


def test_tool_credential_executor_types():
    by_ag = {tc["actionGroupId"]: tc for tc in _TOOL_CREDENTIALS}
    assert by_ag["AG001"]["credentialType"] == "LAMBDA_EXECUTION_ROLE"
    assert by_ag["AG002"]["credentialType"] == "CONFLUENCE_SECRET"
    assert by_ag["AG003"]["credentialType"] == "NONE"


def test_lambda_credential_ref_is_lambda_arn():
    by_ag = {tc["actionGroupId"]: tc for tc in _TOOL_CREDENTIALS}
    assert by_ag["AG001"]["credentialRef"] == _LAMBDA_SEARCH


def test_confluence_credential_ref_is_secret_arn():
    by_ag = {tc["actionGroupId"]: tc for tc in _TOOL_CREDENTIALS}
    assert by_ag["AG002"]["credentialRef"] == _SECRET_ARN


def test_return_control_api_schema_source_is_inline():
    by_ag = {tc["actionGroupId"]: tc for tc in _TOOL_CREDENTIALS}
    assert by_ag["AG003"]["apiSchemaSource"] == "INLINE"
    assert by_ag["AG003"]["credentialRef"] is None


def test_warnings_wildcard_and_conditional_both_present():
    assert "WILDCARD_BINDINGS_PRESENT" in _MANIFEST["warnings"]
    assert "CONDITIONAL_BINDINGS_PRESENT" in _MANIFEST["warnings"]
    assert "NO_MODEL_BINDINGS_FOUND" not in _MANIFEST["warnings"]


# ---------------------------------------------------------------------------
# Structural invariants across all artifacts
# ---------------------------------------------------------------------------

_BINDING_FIELDS = {
    "bindingId",
    "principalType", "principalName", "principalArn",
    "sourcePrincipalType", "sourcePrincipalName", "sourcePrincipalArn",
    "modelId", "confidence", "conditions", "sourceTag",
}
_PRINCIPAL_FIELDS = {"principalType", "principalName", "principalArn"}
_TC_FIELDS = {
    "id", "agentId", "agentArn", "agentServiceRoleArn",
    "actionGroupId", "actionGroupName", "actionGroupState",
    "credentialType", "credentialRef", "apiSchemaSource", "functionSchema",
    "accountId", "region",
}


def test_all_bindings_have_required_fields():
    for b in _BINDINGS:
        assert set(b.keys()) == _BINDING_FIELDS


def test_all_principals_have_required_fields():
    for p in _PRINCIPALS:
        assert set(p.keys()) == _PRINCIPAL_FIELDS


def test_all_tool_credentials_have_required_fields():
    for tc in _TOOL_CREDENTIALS:
        assert set(tc.keys()) == _TC_FIELDS


def test_confidence_values_are_valid():
    valid = {CONFIDENCE_MEDIUM, CONFIDENCE_LOW}
    for b in _BINDINGS:
        assert b["confidence"] in valid


def test_source_tags_have_valid_format():
    for b in _BINDINGS:
        assert b["sourceTag"].startswith("inline:") or b["sourceTag"].startswith("managed:")


def test_tool_credential_ids_have_tc_prefix():
    for tc in _TOOL_CREDENTIALS:
        assert tc["id"].startswith("tc-")


def test_tool_credentials_account_and_region_stamped():
    for tc in _TOOL_CREDENTIALS:
        assert tc["accountId"] == _ACCOUNT
        assert tc["region"] == _REGION
