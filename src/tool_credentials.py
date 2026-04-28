# src/tool_credentials.py
import hashlib
import logging

logger = logging.getLogger(__name__)


def _tc_id(agent_id, action_group_id):
    raw = f"{agent_id}|{action_group_id}"
    return "tc-" + hashlib.sha256(raw.encode()).hexdigest()[:16]


def _classify_executor(action_group):
    """
    Return (credentialType, credentialRef) for one action group.

    Precedence (§7.1 of design spec):
    1. confluenceConfiguration + lambda ARN  → CONFLUENCE_SECRET
    2. lambda ARN only                       → LAMBDA_EXECUTION_ROLE
    3. apiSchema.s3 present                  → S3_READ
    4. customControl == RETURN_CONTROL       → NONE
    5. fallback                              → NONE
    """
    executor = action_group.get("actionGroupExecutor", {})
    lambda_arn = executor.get("lambda")
    confluence = action_group.get("confluenceConfiguration")

    if lambda_arn and confluence:
        source = confluence.get("sourceConfiguration", {})
        return "CONFLUENCE_SECRET", source.get("credentialsSecretArn")

    if lambda_arn:
        return "LAMBDA_EXECUTION_ROLE", lambda_arn

    api_schema = action_group.get("apiSchema", {})
    if "s3" in api_schema:
        bucket = api_schema["s3"].get("s3BucketName", "")
        return "S3_READ", f"arn:aws:s3:::{bucket}" if bucket else None

    if executor.get("customControl") == "RETURN_CONTROL":
        return "NONE", None

    return "NONE", None


def _api_schema_source(action_group):
    schema = action_group.get("apiSchema", {})
    if "s3" in schema:
        return "S3"
    if "payload" in schema:
        return "INLINE"
    return None


# OPENICF-432: Fetch the IAM execution role ARN for a Lambda function.
# Fails soft — returns None and logs a warning on any error.
def _get_lambda_execution_role(lambda_client, lambda_arn):
    try:
        resp = lambda_client.get_function(FunctionName=lambda_arn)
        return resp["Configuration"]["Role"]
    except Exception as exc:
        logger.warning("Failed to get execution role for Lambda %s: %s", lambda_arn, exc)
        return None


def normalize_tool_credentials(agents, account_id, region, lambda_client=None):
    """
    Normalize raw agent/action-group records into agent-tool-credentials.json entries.
    agents: output of collect_agents().
    lambda_client: boto3 Lambda client — when provided, lambdaExecutionRoleArn is populated
                   for LAMBDA_EXECUTION_ROLE action groups (OPENICF-432).
    Returns a flat list of credential records, one per action group across all agents.
    """
    records = []
    for agent in agents:
        agent_id = agent["agentId"]
        agent_arn = agent.get("agentArn", "")
        agent_service_role_arn = agent.get("agentServiceRoleArn", "")
        for ag in agent.get("actionGroups", []):
            credential_type, credential_ref = _classify_executor(ag)

            # OPENICF-432: Resolve Lambda execution role for Lambda-backed action groups.
            lambda_execution_role_arn = None
            if credential_type == "LAMBDA_EXECUTION_ROLE" and lambda_client is not None:
                lambda_execution_role_arn = _get_lambda_execution_role(
                    lambda_client, credential_ref
                )

            records.append({
                "id": _tc_id(agent_id, ag["actionGroupId"]),
                "agentId": agent_id,
                "agentArn": agent_arn,
                "agentServiceRoleArn": agent_service_role_arn,
                "actionGroupId": ag["actionGroupId"],
                "actionGroupName": ag.get("actionGroupName", ""),
                "actionGroupState": ag.get("actionGroupState", ""),
                "credentialType": credential_type,
                "credentialRef": credential_ref,
                "apiSchemaSource": _api_schema_source(ag),
                "functionSchema": "functionSchema" in ag,
                "accountId": account_id,
                "region": region,
                "lambdaExecutionRoleArn": lambda_execution_role_arn,
            })
    return records