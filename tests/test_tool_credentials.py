# tests/test_tool_credentials.py
from tool_credentials import normalize_tool_credentials

# ---------------------------------------------------------------------------
# shared constants
# ---------------------------------------------------------------------------

_ACCOUNT = "123456789012"
_REGION = "us-east-1"
_AGENT_ID = "AGT001"
_AGENT_ARN = "arn:aws:bedrock:us-east-1:123456789012:agent/AGT001"
_AGENT_ROLE_ARN = "arn:aws:iam::123456789012:role/AmazonBedrockExecutionRoleForAgents"
_AG_ID = "AG001"
_LAMBDA_ARN = "arn:aws:lambda:us-east-1:123456789012:function:MyTool"
_SECRET_ARN = "arn:aws:secretsmanager:us-east-1:123456789012:secret:confluence-creds"
_BUCKET = "my-schema-bucket"
_S3_ARN = f"arn:aws:s3:::{_BUCKET}"

_BASE_AGENT = {
    "agentId": _AGENT_ID,
    "agentArn": _AGENT_ARN,
    "agentServiceRoleArn": _AGENT_ROLE_ARN,
    "agentName": "MyAgent",
    "agentStatus": "PREPARED",
}


def _agent(action_groups):
    return {**_BASE_AGENT, "actionGroups": action_groups}


def _ag(ag_id=_AG_ID, **extra):
    return {"actionGroupId": ag_id, "actionGroupName": "MyGroup",
            "actionGroupState": "ENABLED", **extra}


def _run(action_groups):
    return normalize_tool_credentials([_agent(action_groups)], _ACCOUNT, _REGION)


# ---------------------------------------------------------------------------
# empty / no-action-group cases
# ---------------------------------------------------------------------------

def test_empty_agents_returns_empty():
    assert normalize_tool_credentials([], _ACCOUNT, _REGION) == []


def test_agent_with_no_action_groups_returns_empty():
    assert normalize_tool_credentials([_agent([])], _ACCOUNT, _REGION) == []


# ---------------------------------------------------------------------------
# executor type: LAMBDA_EXECUTION_ROLE
# ---------------------------------------------------------------------------

def test_lambda_executor_credential_type():
    ag = _ag(actionGroupExecutor={"lambda": _LAMBDA_ARN})
    records = _run([ag])
    assert records[0]["credentialType"] == "LAMBDA_EXECUTION_ROLE"


def test_lambda_executor_credential_ref_is_lambda_arn():
    ag = _ag(actionGroupExecutor={"lambda": _LAMBDA_ARN})
    records = _run([ag])
    assert records[0]["credentialRef"] == _LAMBDA_ARN


# ---------------------------------------------------------------------------
# executor type: CONFLUENCE_SECRET (lambda + confluenceConfiguration)
# ---------------------------------------------------------------------------

def test_confluence_executor_credential_type():
    ag = _ag(
        actionGroupExecutor={"lambda": _LAMBDA_ARN},
        confluenceConfiguration={
            "sourceConfiguration": {"credentialsSecretArn": _SECRET_ARN}
        },
    )
    records = _run([ag])
    assert records[0]["credentialType"] == "CONFLUENCE_SECRET"


def test_confluence_executor_credential_ref_is_secret_arn():
    ag = _ag(
        actionGroupExecutor={"lambda": _LAMBDA_ARN},
        confluenceConfiguration={
            "sourceConfiguration": {"credentialsSecretArn": _SECRET_ARN}
        },
    )
    records = _run([ag])
    assert records[0]["credentialRef"] == _SECRET_ARN


def test_confluence_takes_precedence_over_plain_lambda():
    """When both lambda ARN and confluenceConfiguration present, CONFLUENCE_SECRET wins."""
    ag = _ag(
        actionGroupExecutor={"lambda": _LAMBDA_ARN},
        confluenceConfiguration={
            "sourceConfiguration": {"credentialsSecretArn": _SECRET_ARN}
        },
    )
    records = _run([ag])
    assert records[0]["credentialType"] == "CONFLUENCE_SECRET"
    assert records[0]["credentialRef"] != _LAMBDA_ARN


def test_confluence_missing_secret_arn_gives_none_ref():
    ag = _ag(
        actionGroupExecutor={"lambda": _LAMBDA_ARN},
        confluenceConfiguration={"sourceConfiguration": {}},
    )
    records = _run([ag])
    assert records[0]["credentialType"] == "CONFLUENCE_SECRET"
    assert records[0]["credentialRef"] is None


# ---------------------------------------------------------------------------
# executor type: S3_READ
# ---------------------------------------------------------------------------

def test_s3_schema_credential_type():
    ag = _ag(
        actionGroupExecutor={},
        apiSchema={"s3": {"s3BucketName": _BUCKET, "s3ObjectKey": "schema.json"}},
    )
    records = _run([ag])
    assert records[0]["credentialType"] == "S3_READ"


def test_s3_schema_credential_ref_is_bucket_arn():
    ag = _ag(
        actionGroupExecutor={},
        apiSchema={"s3": {"s3BucketName": _BUCKET, "s3ObjectKey": "schema.json"}},
    )
    records = _run([ag])
    assert records[0]["credentialRef"] == _S3_ARN


def test_s3_schema_missing_bucket_name_gives_none_ref():
    ag = _ag(actionGroupExecutor={}, apiSchema={"s3": {}})
    records = _run([ag])
    assert records[0]["credentialType"] == "S3_READ"
    assert records[0]["credentialRef"] is None


# ---------------------------------------------------------------------------
# executor type: NONE (Return Control)
# ---------------------------------------------------------------------------

def test_return_control_credential_type():
    ag = _ag(actionGroupExecutor={"customControl": "RETURN_CONTROL"})
    records = _run([ag])
    assert records[0]["credentialType"] == "NONE"


def test_return_control_credential_ref_is_none():
    ag = _ag(actionGroupExecutor={"customControl": "RETURN_CONTROL"})
    records = _run([ag])
    assert records[0]["credentialRef"] is None


# ---------------------------------------------------------------------------
# executor type: NONE (fallback / unknown)
# ---------------------------------------------------------------------------

def test_unknown_executor_falls_back_to_none():
    ag = _ag(actionGroupExecutor={})
    records = _run([ag])
    assert records[0]["credentialType"] == "NONE"
    assert records[0]["credentialRef"] is None


def test_missing_executor_key_falls_back_to_none():
    ag = _ag()  # no actionGroupExecutor key
    records = _run([ag])
    assert records[0]["credentialType"] == "NONE"


# ---------------------------------------------------------------------------
# apiSchemaSource
# ---------------------------------------------------------------------------

def test_api_schema_source_s3():
    ag = _ag(apiSchema={"s3": {"s3BucketName": _BUCKET}})
    records = _run([ag])
    assert records[0]["apiSchemaSource"] == "S3"


def test_api_schema_source_inline():
    ag = _ag(apiSchema={"payload": "openapi: 3.0.0\n..."})
    records = _run([ag])
    assert records[0]["apiSchemaSource"] == "INLINE"


def test_api_schema_source_none_when_absent():
    ag = _ag()
    records = _run([ag])
    assert records[0]["apiSchemaSource"] is None


# ---------------------------------------------------------------------------
# functionSchema flag
# ---------------------------------------------------------------------------

def test_function_schema_true_when_key_present():
    ag = _ag(functionSchema={"functions": []})
    records = _run([ag])
    assert records[0]["functionSchema"] is True


def test_function_schema_false_when_key_absent():
    ag = _ag()
    records = _run([ag])
    assert records[0]["functionSchema"] is False


# ---------------------------------------------------------------------------
# ID generation
# ---------------------------------------------------------------------------

def test_id_has_tc_prefix():
    records = _run([_ag()])
    assert records[0]["id"].startswith("tc-")


def test_id_is_deterministic():
    r1 = normalize_tool_credentials([_agent([_ag()])], _ACCOUNT, _REGION)
    r2 = normalize_tool_credentials([_agent([_ag()])], _ACCOUNT, _REGION)
    assert r1[0]["id"] == r2[0]["id"]


def test_id_distinct_for_different_action_group_ids():
    r = normalize_tool_credentials([_agent([_ag("AG001"), _ag("AG002")])], _ACCOUNT, _REGION)
    assert r[0]["id"] != r[1]["id"]


def test_id_distinct_for_different_agent_ids():
    agent1 = {**_BASE_AGENT, "agentId": "A1", "actionGroups": [_ag()]}
    agent2 = {**_BASE_AGENT, "agentId": "A2", "actionGroups": [_ag()]}
    r = normalize_tool_credentials([agent1, agent2], _ACCOUNT, _REGION)
    assert r[0]["id"] != r[1]["id"]


# ---------------------------------------------------------------------------
# output schema completeness
# ---------------------------------------------------------------------------

_EXPECTED_FIELDS = {
    "id", "agentId", "agentArn", "agentServiceRoleArn",
    "actionGroupId", "actionGroupName", "actionGroupState",
    "credentialType", "credentialRef",
    "apiSchemaSource", "functionSchema",
    "accountId", "region",
}


def test_all_13_fields_present():
    records = _run([_ag()])
    assert set(records[0].keys()) == _EXPECTED_FIELDS


def test_agent_arn_propagated():
    records = _run([_ag()])
    assert records[0]["agentArn"] == _AGENT_ARN


def test_agent_service_role_arn_propagated():
    records = _run([_ag()])
    assert records[0]["agentServiceRoleArn"] == _AGENT_ROLE_ARN


def test_agent_service_role_arn_defaults_to_empty_string():
    agent = {k: v for k, v in _BASE_AGENT.items() if k != "agentServiceRoleArn"}
    agent["actionGroups"] = [_ag()]
    records = normalize_tool_credentials([agent], _ACCOUNT, _REGION)
    assert records[0]["agentServiceRoleArn"] == ""


def test_account_id_stamped_on_record():
    records = _run([_ag()])
    assert records[0]["accountId"] == _ACCOUNT


def test_region_stamped_on_record():
    records = _run([_ag()])
    assert records[0]["region"] == _REGION


def test_action_group_fields_passed_through():
    ag = _ag("AG42", actionGroupName="SearchTool", actionGroupState="DISABLED")
    records = _run([ag])
    assert records[0]["actionGroupId"] == "AG42"
    assert records[0]["actionGroupName"] == "SearchTool"
    assert records[0]["actionGroupState"] == "DISABLED"


# ---------------------------------------------------------------------------
# multi-agent, multi-action-group
# ---------------------------------------------------------------------------

def test_multiple_action_groups_emit_one_record_each():
    records = _run([_ag("AG1"), _ag("AG2"), _ag("AG3")])
    assert len(records) == 3


def test_multiple_agents_accumulate_records():
    agent1 = {**_BASE_AGENT, "agentId": "A1", "actionGroups": [_ag("AG1")]}
    agent2 = {**_BASE_AGENT, "agentId": "A2", "actionGroups": [_ag("AG2"), _ag("AG3")]}
    records = normalize_tool_credentials([agent1, agent2], _ACCOUNT, _REGION)
    assert len(records) == 3
    assert {r["agentId"] for r in records} == {"A1", "A2"}
