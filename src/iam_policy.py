# src/iam_policy.py
import fnmatch
import json

# All Bedrock actions that run inference against a foundation model.
# bedrock:InvokeInlineAgent is included because it invokes a model under the
# caller's own IAM identity (not an agent service role) and is equivalent in
# governance impact to bedrock:InvokeModel. See design §5.1 and §11.
_INVOKE_ACTIONS = frozenset({
    "bedrock:invokemodel",
    "bedrock:invokemodelwithresponsestream",
    "bedrock:converse",
    "bedrock:conversestream",
    "bedrock:invokeinlineagent",
})

CONFIDENCE_MEDIUM = "MEDIUM"
CONFIDENCE_LOW = "LOW"


def action_matches(pattern, action):
    """Case-insensitive IAM wildcard match (* and ? supported)."""
    return fnmatch.fnmatchcase(action.lower(), pattern.lower())


def allows_bedrock_invoke(actions):
    """True if any action entry (string or list) grants a Bedrock invoke action."""
    if isinstance(actions, str):
        actions = [actions]
    for pattern in actions:
        for invoke_action in _INVOKE_ACTIONS:
            if action_matches(pattern, invoke_action):
                return True
    return False


def parse_model_id_from_arn(arn):
    """
    Return the model-ID segment from a Bedrock foundation-model ARN.
    Returns '*' for a bare '*', the model ID for a proper ARN,
    or None if the ARN is not a foundation-model resource.
    """
    if arn == "*":
        return "*"
    prefix = "foundation-model/"
    idx = arn.find(prefix)
    if idx == -1:
        return None
    return arn[idx + len(prefix):]


def is_wildcard_resource(resource):
    """True if the resource covers every foundation model ('*' or ARN ending '/*')."""
    return parse_model_id_from_arn(resource) == "*"


def classify_scope(resource):
    """
    Return (scopeType, scopeResourceName) for a Bedrock resource string.
    Covers the five types in design §6.1.
    """
    if resource == "*":
        return "ACCOUNT_REGION_WILDCARD", resource
    if "foundation-model/" in resource:
        model_id = parse_model_id_from_arn(resource)
        if model_id == "*":
            return "MODEL_WILDCARD", resource
        return "MODEL", resource
    if "provisioned-model/" in resource:
        return "PROVISIONED_MODEL", resource
    if "custom-model/" in resource:
        return "CUSTOM_MODEL", resource
    # Catch-all wildcard patterns (e.g. arn:aws:bedrock:*)
    return "ACCOUNT_REGION_WILDCARD", resource


def serialize_condition_json(conditions):
    """
    Serialize IAM condition block to a JSON string per design §8.3.
    Returns None when conditions is absent or empty.
    """
    if not conditions:
        return None
    return json.dumps(conditions, sort_keys=True)


def derive_confidence(statement):
    """MEDIUM for unconditional allows; LOW when a Condition block is present."""
    if statement.get("Condition"):
        return CONFIDENCE_LOW
    return CONFIDENCE_MEDIUM


def derive_policy_ref(policy_type, policy_name):
    """Return a compact reference identifying the granting policy, e.g. 'inline:Name'.
    Stored as policyRef on the candidate dict; sourceTag is computed in normalize.py.
    """
    return f"{policy_type}:{policy_name}"


def extract_model_bindings(statement):
    """
    Return Bedrock model binding dicts for a single policy statement.
    Skips Deny, non-invoke actions, and non-foundation-model resources.
    NotAction statements are conservatively skipped (no bindings extracted).

    Each binding includes the full set of fields needed by design §8.3:
      modelId, modelArn, scopeType, scopeResourceName, wildcard,
      confidence, conditionJson.
    """
    if statement.get("Effect") != "Allow":
        return []

    actions = statement.get("Action", [])
    if not allows_bedrock_invoke(actions):
        return []

    resources = statement.get("Resource", [])
    if isinstance(resources, str):
        resources = [resources]

    confidence = derive_confidence(statement)
    condition_json = serialize_condition_json(statement.get("Condition"))

    bindings = []
    for resource in resources:
        model_id = parse_model_id_from_arn(resource)
        if model_id is None:
            continue
        scope_type, scope_resource_name = classify_scope(resource)
        wildcard = is_wildcard_resource(resource)
        # modelArn: use the resource string directly when it is a proper ARN;
        # None for bare '*' since there is no single model ARN to reference.
        model_arn = None if resource == "*" else resource
        bindings.append({
            "modelId": model_id,
            "modelArn": model_arn,
            "scopeType": scope_type,
            "scopeResourceName": scope_resource_name,
            "wildcard": wildcard,
            "confidence": confidence,
            "conditionJson": condition_json,
        })
    return bindings