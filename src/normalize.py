# src/normalize.py
import hashlib

def _derive_source_tag(binding_origin, wildcard, condition_json):
    """
    Compute the design §8.3 sourceTag enum value from binding attributes.

    Precedence:
      - CONDITIONAL_BINDING   when conditionJson is present (lowest confidence)
      - WILDCARD_*            when wildcard=True and no condition
      - DIRECT/GROUP          when specific ARN and no condition
    """
    if condition_json:
        return "CONDITIONAL_BINDING"
    if wildcard:
        if binding_origin == "GROUP_INHERITED":
            return "GROUP_INHERITED_WILDCARD_BINDING"
        return "WILDCARD_ACCOUNT_SCOPE_BINDING"
    if binding_origin == "GROUP_INHERITED":
        return "GROUP_INHERITED_BINDING"
    return "DIRECT_PRINCIPAL_POLICY_BINDING"


# Dedup key per design §6.3:
#   (principalArn, modelArn, wildcard, conditionJson, bindingOrigin, sourcePrincipalArn)
# modelArn stand-in: modelId (replaced in B-06).
# wildcard and conditionJson not yet on candidate dict (added in B-16/B-17); .get() safe.
def _dedup_key(c):
    return (
        c["principalArn"],
        c.get("modelArn", c["modelId"]),
        c.get("wildcard"),
        c.get("conditionJson"),
        c.get("bindingOrigin", ""),
        c.get("sourcePrincipalArn") or "",
        c.get("policyRef", ""),
    )


def _normalize_role_candidate(c):
    return {
        "principalType": "role",
        "principalName": c["roleName"],
        "principalArn": c["roleArn"],
        "sourcePrincipalType": "role",
        "sourcePrincipalName": c["roleName"],
        "sourcePrincipalArn": c["roleArn"],
        "modelId": c["modelId"],
        "modelArn": c.get("modelArn"),
        "scopeType": c.get("scopeType", ""),
        "scopeResourceName": c.get("scopeResourceName", c["modelId"]),
        "wildcard": c.get("wildcard", False),
        "confidence": c["confidence"],
        "conditionJson": c.get("conditionJson"),
        "policyRef": c.get("policyRef", c.get("sourceTag", "")),
        "bindingOrigin": c.get("bindingOrigin", "DIRECT_ROLE_POLICY"),
    }


def _binding_id(c):
    # Hash input per design §6.4: principalArn|scopeType|scopeResourceName|conditionJson
    # Extended with sourcePrincipalArn so that direct and group-inherited grants to the
    # same model by the same principal produce distinct IDs.
    # scopeType and scopeResourceName are not yet on the candidate dict (added in B-15/B-06);
    # use modelId as scopeResourceName stand-in until those fields exist.
    scope_resource = c.get("scopeResourceName", c["modelId"])
    scope_type = c.get("scopeType", "")
    condition = c.get("conditionJson") or ""
    source_principal = c.get("sourcePrincipalArn") or ""
    raw = f"{c['principalArn']}|{scope_type}|{scope_resource}|{condition}|{source_principal}"
    return "mb-" + hashlib.sha256(raw.encode()).hexdigest()[:16]


def _deduplicate(candidates):
    seen = set()
    result = []
    for c in candidates:
        k = _dedup_key(c)
        if k not in seen:
            seen.add(k)
            result.append(c)
    return result


def _account_id_from_arn(arn):
    """Extract account ID from an IAM ARN (colon-segment index 4)."""
    parts = arn.split(":")
    return parts[4] if len(parts) > 4 else ""


def _derive_principals(bindings):
    """
    Unique effective principals sorted by ARN.
    Fields per design §8.5: principalArn, principalType, principalName,
    principalAccountId, bindingCount.
    """
    counts: dict = {}
    for b in bindings:
        counts[b["principalArn"]] = counts.get(b["principalArn"], 0) + 1

    seen: set = set()
    principals = []
    for b in bindings:
        arn = b["principalArn"]
        if arn not in seen:
            seen.add(arn)
            principals.append({
                "principalArn": arn,
                "principalType": b["principalType"],
                "principalName": b["principalName"],
                "principalAccountId": _account_id_from_arn(arn),
                "bindingCount": counts[arn],
            })
    return sorted(principals, key=lambda p: p["principalArn"])


def normalize_bindings(role_candidates, user_candidates):
    unified = [_normalize_role_candidate(c) for c in role_candidates]
    unified.extend(user_candidates)
    deduped = _deduplicate(unified)
    bindings = [
        {
            "id": _binding_id(c),
            "permissions": ["invoke"],
            "principalAccountId": _account_id_from_arn(c["principalArn"]),
            "sourceTag": _derive_source_tag(
                c.get("bindingOrigin", ""),
                c.get("wildcard", False),
                c.get("conditionJson"),
            ),
            **c,
        }
        for c in deduped
    ]
    principals = _derive_principals(bindings)
    return bindings, principals