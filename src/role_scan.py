# src/role_scan.py
import logging

from iam_fetch import fetch_attached_policies, fetch_inline_policies
from iam_policy import derive_source_tag, extract_model_bindings

logger = logging.getLogger(__name__)


def _bindings_from_document(document, role_name, role_arn, policy_type, policy_name):
    candidates = []
    for stmt in document.get("Statement", []):
        for binding in extract_model_bindings(stmt):
            candidates.append({
                "roleName": role_name,
                "roleArn": role_arn,
                "modelId": binding["modelId"],
                "confidence": binding["confidence"],
                "conditions": binding["conditions"],
                "sourceTag": derive_source_tag(policy_type, policy_name),
            })
    return candidates


def scan_roles(iam_client, roles):
    """
    Scan each role's inline and attached policies for Bedrock model bindings.
    Takes a pre-fetched list of role dicts. Per-role failures warn and continue.
    Returns a flat list of binding candidates.
    """
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
