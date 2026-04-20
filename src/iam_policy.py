# src/iam_policy.py
import fnmatch

# All Bedrock actions that run inference against a foundation model.
_INVOKE_ACTIONS = frozenset({
    "bedrock:invokemodel",
    "bedrock:invokemodelwithresponsestream",
    "bedrock:converse",
    "bedrock:conversestream",
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


def serialize_conditions(conditions):
    """Return None when conditions is absent/empty; shallow-copy dict otherwise."""
    if not conditions:
        return None
    return dict(conditions)


def derive_confidence(statement):
    """MEDIUM for unconditional allows; LOW when a Condition block is present."""
    if statement.get("Condition"):
        return CONFIDENCE_LOW
    return CONFIDENCE_MEDIUM


def derive_source_tag(policy_type, policy_name):
    """Return a compact tag identifying the granting policy, e.g. 'inline:Name'."""
    return f"{policy_type}:{policy_name}"


def extract_model_bindings(statement):
    """
    Return Bedrock model binding dicts for a single policy statement.
    Skips Deny, non-invoke actions, and non-foundation-model resources.
    NotAction statements are conservatively skipped (no bindings extracted).
    Each binding: {modelId, confidence, conditions}.
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
    conditions = serialize_conditions(statement.get("Condition"))

    bindings = []
    for resource in resources:
        model_id = parse_model_id_from_arn(resource)
        if model_id is not None:
            bindings.append({
                "modelId": model_id,
                "confidence": confidence,
                "conditions": conditions,
            })
    return bindings
