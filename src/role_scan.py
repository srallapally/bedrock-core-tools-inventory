# src/role_scan.py
import logging

from iam_fetch import fetch_attached_policies, fetch_inline_policies
from iam_policy import derive_policy_ref, extract_model_bindings

logger = logging.getLogger(__name__)


def _bindings_from_document(document, role_name, role_arn, policy_type, policy_name):
    candidates = []
    for stmt in document.get("Statement", []):
        for binding in extract_model_bindings(stmt):
            candidates.append({
                "roleName": role_name,
                "roleArn": role_arn,
                "modelId": binding["modelId"],
                "modelArn": binding["modelArn"],
                "scopeType": binding["scopeType"],
                "scopeResourceName": binding["scopeResourceName"],
                "wildcard": binding["wildcard"],
                "confidence": binding["confidence"],
                "conditionJson": binding["conditionJson"],
                "policyRef": derive_policy_ref(policy_type, policy_name),
                "bindingOrigin": "DIRECT_ROLE_POLICY",
            })
    return candidates


def scan_roles(iam_client, roles):
    candidates = []
    for role in roles:
        role_name = role["RoleName"]
        role_arn = role["Arn"]
        try:
            for policy in fetch_inline_policies(iam_client, "role", role_name):
                candidates.extend(
                    _bindings_from_document(
                        policy["document"], role_name, role_arn, "inline", policy["name"]
                    )
                )
            for policy in fetch_attached_policies(iam_client, "role", role_name):
                candidates.extend(
                    _bindings_from_document(
                        policy["document"], role_name, role_arn, "managed", policy["arn"]
                    )
                )
        except Exception as exc:
            logger.warning("skipping role %s: %s", role_name, exc)
    return candidates