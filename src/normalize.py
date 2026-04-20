# src/normalize.py
import hashlib

# Canonical tuple that uniquely identifies a grant for deduplication and ID generation.
_DEDUP_FIELDS = ("principalArn", "sourcePrincipalArn", "modelId", "sourceTag")


def _normalize_role_candidate(c):
    """Map role_scan's roleName/roleArn fields to the unified principal/source schema."""
    return {
        "principalType": "role",
        "principalName": c["roleName"],
        "principalArn": c["roleArn"],
        "sourcePrincipalType": "role",
        "sourcePrincipalName": c["roleName"],
        "sourcePrincipalArn": c["roleArn"],
        "modelId": c["modelId"],
        "confidence": c["confidence"],
        "conditions": c["conditions"],
        "sourceTag": c["sourceTag"],
    }


def _dedup_key(c):
    return tuple(c[f] for f in _DEDUP_FIELDS)


def _binding_id(c):
    raw = "|".join(c[f] for f in _DEDUP_FIELDS)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _deduplicate(candidates):
    """First-seen wins; preserves insertion order of surviving entries."""
    seen = set()
    result = []
    for c in candidates:
        k = _dedup_key(c)
        if k not in seen:
            seen.add(k)
            result.append(c)
    return result


def _derive_principals(bindings):
    """Unique effective principals (principalArn) sorted by ARN for stability."""
    seen = set()
    principals = []
    for b in bindings:
        arn = b["principalArn"]
        if arn not in seen:
            seen.add(arn)
            principals.append({
                "principalType": b["principalType"],
                "principalName": b["principalName"],
                "principalArn": arn,
            })
    return sorted(principals, key=lambda p: p["principalArn"])


def normalize_bindings(role_candidates, user_candidates):
    """
    Normalize role candidates to unified schema, merge with user candidates,
    deduplicate on _DEDUP_FIELDS, attach stable bindingId, derive principals.
    Returns (bindings: list[dict], principals: list[dict]).
    """
    unified = [_normalize_role_candidate(c) for c in role_candidates]
    unified.extend(user_candidates)
    deduped = _deduplicate(unified)
    bindings = [{"bindingId": _binding_id(c), **c} for c in deduped]
    principals = _derive_principals(bindings)
    return bindings, principals
