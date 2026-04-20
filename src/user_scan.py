# src/user_scan.py
import logging

from iam_fetch import fetch_attached_policies, fetch_inline_policies
from iam_policy import derive_policy_ref, extract_model_bindings

logger = logging.getLogger(__name__)


def _binding_origin(source_type):
    """Map source entity type to the design §8.3 bindingOrigin enum value."""
    if source_type == "group":
        return "GROUP_INHERITED"
    return "DIRECT_USER_POLICY"


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
                "modelArn": binding["modelArn"],
                "scopeType": binding["scopeType"],
                "scopeResourceName": binding["scopeResourceName"],
                "wildcard": binding["wildcard"],
                "confidence": binding["confidence"],
                "conditionJson": binding["conditionJson"],
                "policyRef": derive_policy_ref(policy_type, policy_name),
                "bindingOrigin": _binding_origin(source_type),
            })
    return candidates


def _scan_entity_policies(
    iam_client,
    principal_type, principal_name, principal_arn,
    source_type, source_name, source_arn,
):
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