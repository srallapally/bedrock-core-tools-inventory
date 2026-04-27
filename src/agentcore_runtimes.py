# src/agentcore_runtimes.py
import logging

logger = logging.getLogger(__name__)


def _list_runtimes(client):
    """Paginate list_agent_runtimes via nextToken. Any failure propagates."""
    items = []
    kwargs = {}
    while True:
        resp = client.list_agent_runtimes(**kwargs)
        items.extend(resp.get("agentRuntimes", []))
        next_token = resp.get("nextToken")
        if not next_token:
            break
        kwargs["nextToken"] = next_token
    return items


def _get_runtime(client, runtime_id):
    """Fetch full runtime detail. Required to obtain roleArn and networkMode."""
    resp = client.get_agent_runtime(agentRuntimeId=runtime_id)
    # API wraps the object under agentRuntime in some SDK versions
    return resp.get("agentRuntime", resp)


def _safe_isoformat(value):
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def collect_agentcore_runtimes(client, account_id, region):
    """
    Collect all AgentCore Runtime deployments with their workload identities.

    list_agent_runtimes failure propagates (list-level abort).
    Per-runtime get_agent_runtime failures warn and emit a sparse record
    containing only the fields available from the list summary.

    Returns a list of runtime records matching the agentcore-runtimes.json schema.
    """
    runtimes = []
    for summary in _list_runtimes(client):
        runtime_id = summary.get("agentRuntimeId", "")
        runtime_name = summary.get("agentRuntimeName", "")
        try:
            detail = _get_runtime(client, runtime_id)
            runtimes.append({
                "agentRuntimeId":   runtime_id,
                "agentRuntimeArn":  summary.get("agentRuntimeArn", ""),
                "agentRuntimeName": runtime_name,
                "status":           summary.get("status", ""),
                # roleArn is the workload identity — the IAM role the runtime assumes.
                # Only available from GetAgentRuntime, not the list summary.
                "roleArn":          detail.get("roleArn", ""),
                "networkMode":      detail.get("networkConfiguration", {}).get("networkMode", ""),
                "createdAt":        _safe_isoformat(summary.get("createdAt", "")),
                "updatedAt":        _safe_isoformat(summary.get("updatedAt", "")),
                "accountId":        account_id,
                "region":           region,
            })
        except Exception as exc:
            logger.warning("skipping agentcore runtime %s (%s): %s",
                           runtime_id, runtime_name, exc)
            # Emit sparse record — enough to identify the runtime
            runtimes.append({
                "agentRuntimeId":   runtime_id,
                "agentRuntimeArn":  summary.get("agentRuntimeArn", ""),
                "agentRuntimeName": runtime_name,
                "status":           summary.get("status", ""),
                "roleArn":          "",
                "networkMode":      "",
                "createdAt":        _safe_isoformat(summary.get("createdAt", "")),
                "updatedAt":        _safe_isoformat(summary.get("updatedAt", "")),
                "accountId":        account_id,
                "region":           region,
                "_sparse":          True,
            })
    return runtimes