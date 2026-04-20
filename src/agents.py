# src/agents.py
import logging

logger = logging.getLogger(__name__)

_AGENT_VERSION = "DRAFT"


def _list_agents(client):
    """Paginate list_agents via nextToken. Any failure propagates."""
    items = []
    kwargs = {}
    while True:
        resp = client.list_agents(**kwargs)
        items.extend(resp.get("agentSummaries", []))
        next_token = resp.get("nextToken")
        if not next_token:
            break
        kwargs["nextToken"] = next_token
    return items


def _list_action_groups(client, agent_id):
    """Paginate list_agent_action_groups for one agent via nextToken. Any failure propagates."""
    items = []
    kwargs = {"agentId": agent_id, "agentVersion": _AGENT_VERSION}
    while True:
        resp = client.list_agent_action_groups(**kwargs)
        items.extend(resp.get("actionGroupSummaries", []))
        next_token = resp.get("nextToken")
        if not next_token:
            break
        kwargs["nextToken"] = next_token
    return items


def _get_action_group(client, agent_id, action_group_id):
    resp = client.get_agent_action_group(
        agentId=agent_id,
        agentVersion=_AGENT_VERSION,
        actionGroupId=action_group_id,
    )
    return resp["agentActionGroup"]


def collect_agents(client):
    """
    Collect all agents with embedded action group details.
    list_agents failure propagates (list-level abort).
    Per-agent failures (including listing their action groups) warn and continue.
    Per-action-group get failures warn and continue.
    """
    agents = []
    for summary in _list_agents(client):
        agent_id = summary["agentId"]
        agent_name = summary.get("agentName", "")
        try:
            action_groups = []
            for ag_summary in _list_action_groups(client, agent_id):
                ag_id = ag_summary["actionGroupId"]
                try:
                    action_groups.append(_get_action_group(client, agent_id, ag_id))
                except Exception as exc:
                    logger.warning(
                        "skipping action group %s on agent %s: %s", ag_id, agent_id, exc
                    )
            agents.append({
                "agentId": agent_id,
                "agentName": agent_name,
                "agentArn": summary.get("agentArn", ""),
                "agentStatus": summary.get("agentStatus", ""),
                "actionGroups": action_groups,
            })
        except Exception as exc:
            logger.warning("skipping agent %s (%s): %s", agent_id, agent_name, exc)
    return agents
