# src/manifest.py
import datetime

_SCHEMA_VERSION = "1.0"
_PLATFORM = "aws-bedrock-core"


def build_manifest(cfg, models, bindings, tool_credentials, principals,
                   extra_warnings=None, now=None):
    """
    Build the manifest.json payload from already-normalized in-memory data.
    Counts and warnings are derived purely from the supplied lists.
    extra_warnings: caller-supplied operational warnings (e.g. agent scan failures).
    now: injectable datetime for deterministic tests; defaults to utcnow().
    """
    if now is None:
        now = datetime.datetime.utcnow()

    wildcard_count = sum(1 for b in bindings if "*" in b.get("modelId", ""))
    conditional_count = sum(1 for b in bindings if b.get("conditions") is not None)

    warnings = []
    if not bindings:
        warnings.append("NO_MODEL_BINDINGS_FOUND")
    if wildcard_count > 0:
        warnings.append("WILDCARD_BINDINGS_PRESENT")
    if conditional_count > 0:
        warnings.append("CONDITIONAL_BINDINGS_PRESENT")
    if extra_warnings:
        warnings.extend(extra_warnings)

    return {
        "generatedAt": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "schemaVersion": _SCHEMA_VERSION,
        "platform": _PLATFORM,
        "accountId": cfg["account_id"],
        "region": cfg["region"],
        "modelCount": len(models),
        "modelBindingCount": len(bindings),
        "wildcardBindingCount": wildcard_count,
        "conditionalBindingCount": conditional_count,
        "agentToolCredentialCount": len(tool_credentials),
        "principalCount": len(principals),
        "warnings": warnings,
        "artifacts": {
            "models.json": len(models),
            "model-bindings.json": len(bindings),
            "agent-tool-credentials.json": len(tool_credentials),
            "principals.json": len(principals),
            "manifest.json": 1,
        },
    }
