# src/agent_bindings.py
import hashlib
import json
import logging

from iam_fetch import fetch_inline_policies, fetch_attached_policies

logger = logging.getLogger(__name__)

_INVOKE_AGENT_ACTIONS = frozenset({
    "bedrock:invokeagent",
    "bedrock:*",
    "*",
})


def _includes_invoke_agent(actions):
    if isinstance(actions, str):
        actions = [actions]
    return any(a.lower() in _INVOKE_AGENT_ACTIONS for a in actions)


def _parse_agent_or_alias_arn(resource_arn, account_id):
    """
    Returns (agentArn, agentVersion, aliasArn) or (None, None, None) if unparseable.
    Handles both agent-alias/ and agent/ ARN patterns.
    """
    parts = resource_arn.split(":")
    if len(parts) < 6:
        return None, None, None

    resource_segment = parts[5]

    if resource_segment.startswith("agent-alias/"):
        rest = resource_segment[len("agent-alias/"):]
        if "/" not in rest:
            return None, None, None
        agent_id, alias_id = rest.split("/", 1)
        region = parts[3]
        acct = parts[4] or account_id
        agent_arn = f"arn:aws:bedrock:{region}:{acct}:agent/{agent_id}"
        return agent_arn, None, resource_arn

    if resource_segment.startswith("agent/"):
        return resource_arn, None, None

    return None, None, None


def _extract_bindings_from_document(
    document,
    principal_arn,
    principal_type,
    principal_name,
    account_id,
    binding_origin,
    source_principal_arn=None,
    source_principal_type=None,
    source_principal_name=None,
):
    results = []
    statements = document.get("Statement", [])
    if isinstance(statements, dict):
        statements = [statements]

    for stmt in statements:
        if stmt.get("Effect") != "Allow":
            continue

        actions = stmt.get("Action", [])
        if not _includes_invoke_agent(actions):
            continue

        resources = stmt.get("Resource", [])
        if isinstance(resources, str):
            resources = [resources]

        condition_json = None
        if stmt.get("Condition"):
            condition_json = json.dumps(stmt["Condition"], sort_keys=True)

        for res in resources:
            if res == "*" or res.endswith(":*") or res.endswith("/*"):
                results.append({
                    "agentArn": None,
                    "agentVersion": None,
                    "aliasArn": None,
                    "principalType": principal_type,
                    "principalName": principal_name,
                    "principalArn": principal_arn,
                    "principalAccountId": account_id,
                    "wildcard": True,
                    "conditionJson": condition_json,
                    "bindingOrigin": binding_origin,
                    "sourcePrincipalArn": source_principal_arn,
                    "sourcePrincipalType": source_principal_type,
                    "sourcePrincipalName": source_principal_name,
                })
                continue

            if ":agent-alias/" in res or ":agent/" in res:
                agent_arn, agent_version, alias_arn = _parse_agent_or_alias_arn(res, account_id)
                if agent_arn is None:
                    logger.info("Could not parse agent/alias ARN %s for principal %s; skipping", res, principal_arn)
                    continue
                results.append({
                    "agentArn": agent_arn,
                    "agentVersion": agent_version,
                    "aliasArn": alias_arn,
                    "principalType": principal_type,
                    "principalName": principal_name,
                    "principalArn": principal_arn,
                    "principalAccountId": account_id,
                    "wildcard": False,
                    "conditionJson": condition_json,
                    "bindingOrigin": binding_origin,
                    "sourcePrincipalArn": source_principal_arn,
                    "sourcePrincipalType": source_principal_type,
                    "sourcePrincipalName": source_principal_name,
                })

    return results


def _dedup_key(b):
    return (
        b.get("principalArn"),
        b.get("agentArn"),
        b.get("aliasArn"),
        b.get("wildcard"),
        b.get("conditionJson"),
        b.get("bindingOrigin", ""),
        b.get("sourcePrincipalArn") or "",
    )


def _deduplicate(bindings):
    seen = set()
    result = []
    for b in bindings:
        k = _dedup_key(b)
        if k not in seen:
            seen.add(k)
            result.append(b)
    return result


def _scan_entity(
    iam_client,
    entity_type,
    entity_name,
    principal_arn,
    principal_type,
    principal_name,
    account_id,
    binding_origin,
    source_principal_arn=None,
    source_principal_type=None,
    source_principal_name=None,
):
    candidates = []
    for policy in fetch_inline_policies(iam_client, entity_type, entity_name):
        candidates.extend(_extract_bindings_from_document(
            policy["document"],
            principal_arn, principal_type, principal_name, account_id,
            binding_origin, source_principal_arn, source_principal_type, source_principal_name,
        ))
    for policy in fetch_attached_policies(iam_client, entity_type, entity_name):
        candidates.extend(_extract_bindings_from_document(
            policy["document"],
            principal_arn, principal_type, principal_name, account_id,
            binding_origin, source_principal_arn, source_principal_type, source_principal_name,
        ))
    return candidates


def _list_user_groups(iam_client, user_name):
    groups = []
    kwargs = {"UserName": user_name}
    while True:
        resp = iam_client.list_groups_for_user(**kwargs)
        groups.extend(resp["Groups"])
        if not resp.get("IsTruncated"):
            break
        kwargs["Marker"] = resp["Marker"]
    return groups


def scan_agent_bindings(iam_client, roles, users, account_id):
    """
    Scan all IAM roles and users for bedrock:InvokeAgent permissions.
    Returns a deduplicated list of binding records in the agent-bindings.json format.
    roles: output of iam_fetch.list_roles()
    users: output of iam_fetch.list_users()
    """
    candidates = []

    for role in roles:
        role_name = role["RoleName"]
        role_arn = role["Arn"]
        try:
            candidates.extend(_scan_entity(
                iam_client, "role", role_name,
                role_arn, "ROLE", role_name,
                account_id, "DIRECT_ROLE_POLICY",
                source_principal_arn=role_arn,
                source_principal_type="role",
                source_principal_name=role_name,
            ))
        except Exception as exc:
            logger.warning("skipping role %s: %s", role_name, exc)

    for user in users:
        user_name = user["UserName"]
        user_arn = user["Arn"]
        try:
            # Direct user policies
            candidates.extend(_scan_entity(
                iam_client, "user", user_name,
                user_arn, "USER", user_name,
                account_id, "DIRECT_USER_POLICY",
                source_principal_arn=user_arn,
                source_principal_type="user",
                source_principal_name=user_name,
            ))
            # Group-inherited policies — principal is user, source is group
            for group in _list_user_groups(iam_client, user_name):
                group_name = group["GroupName"]
                group_arn = group["Arn"]
                candidates.extend(_scan_entity(
                    iam_client, "group", group_name,
                    user_arn, "USER", user_name,
                    account_id, "GROUP_INHERITED",
                    source_principal_arn=group_arn,
                    source_principal_type="group",
                    source_principal_name=group_name,
                ))
        except Exception as exc:
            logger.warning("skipping user %s: %s", user_name, exc)

    return _deduplicate(candidates)


def build_agent_bindings_payload(bindings, account_id, region):
    """
    Wrap bindings in the legacy payload envelope expected by the Java connector's
    loadBindingsFromS3() parser.
    """
    from datetime import datetime, timezone
    return {
        "accountId": account_id,
        "region": region,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "bindings": bindings,
    }