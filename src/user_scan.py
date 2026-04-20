# src/user_scan.py
import logging

from iam_fetch import fetch_attached_policies, fetch_inline_policies
from iam_policy import derive_source_tag, extract_model_bindings

logger = logging.getLogger(__name__)


def _bindings_from_document(
    document,
    principal_type, principal_name, principal_arn,
    source_type, source_name, source_arn,
    policy_type, policy_name,
):
    candidates = []
    for stmt in document.get("Statement", []):
        for binding in extract_model_bindings(stmt):
            candidates.append({
                "principalType": principal_type,
                "principalName": principal_name,
                "principalArn": principal_arn,
                "sourcePrincipalType": source_type,
                "sourcePrincipalName": source_name,
                "sourcePrincipalArn": source_arn,
                "modelId": binding["modelId"],
                "confidence": binding["confidence"],
                "conditions": binding["conditions"],
                "sourceTag": derive_source_tag(policy_type, policy_name),
            })
    return candidates


def _scan_entity_policies(
    iam_client,
    principal_type, principal_name, principal_arn,
    source_type, source_name, source_arn,
):
    """Scan inline and attached policies for source entity, stamping principal lineage."""
    candidates = []
    for policy in fetch_inline_policies(iam_client, source_type, source_name):
        candidates.extend(_bindings_from_document(
            policy["document"],
            principal_type, principal_name, principal_arn,
            source_type, source_name, source_arn,
            "inline", policy["name"],
        ))
    for policy in fetch_attached_policies(iam_client, source_type, source_name):
        candidates.extend(_bindings_from_document(
            policy["document"],
            principal_type, principal_name, principal_arn,
            source_type, source_name, source_arn,
            "managed", policy["arn"],
        ))
    return candidates


def _list_user_groups(iam_client, user_name):
    """Return all IAM groups the user belongs to, handling IsTruncated/Marker pagination."""
    groups = []
    kwargs = {"UserName": user_name}
    while True:
        resp = iam_client.list_groups_for_user(**kwargs)
        groups.extend(resp["Groups"])
        if not resp.get("IsTruncated"):
            break
        kwargs["Marker"] = resp["Marker"]
    return groups


def scan_users(iam_client, users):
    """
    Scan each user's direct policies and group-inherited policies for Bedrock bindings.
    Per-user failures warn and continue. Returns a flat list of binding candidates
    with full principal and source lineage fields.
    """
    candidates = []
    for user in users:
        user_name = user["UserName"]
        user_arn = user["Arn"]
        try:
            candidates.extend(_scan_entity_policies(
                iam_client,
                "user", user_name, user_arn,
                "user", user_name, user_arn,
            ))
            for group in _list_user_groups(iam_client, user_name):
                group_name = group["GroupName"]
                group_arn = group["Arn"]
                candidates.extend(_scan_entity_policies(
                    iam_client,
                    "user", user_name, user_arn,
                    "group", group_name, group_arn,
                ))
        except Exception as exc:
            logger.warning("skipping user %s: %s", user_name, exc)
    return candidates
