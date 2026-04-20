# tests/test_agents.py
from unittest.mock import MagicMock, call

import pytest

from agents import _AGENT_VERSION, collect_agents

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _agent_summary(agent_id, name="AgentOne", status="PREPARED"):
    return {"agentId": agent_id, "agentName": name, "agentStatus": status}


def _ag_summary(ag_id, name="AG"):
    return {"actionGroupId": ag_id, "actionGroupName": name, "actionGroupState": "ENABLED"}


def _ag_detail(ag_id, agent_id="a1", name="AG"):
    return {
        "agentId": agent_id,
        "agentVersion": _AGENT_VERSION,
        "actionGroupId": ag_id,
        "actionGroupName": name,
        "actionGroupState": "ENABLED",
        "actionGroupExecutor": {"lambda": f"arn:aws:lambda:us-east-1::function:{name}"},
    }


def _agents_page(summaries, next_token=None):
    p = {"agentSummaries": summaries}
    if next_token:
        p["nextToken"] = next_token
    return p


def _ags_page(summaries, next_token=None):
    p = {"actionGroupSummaries": summaries}
    if next_token:
        p["nextToken"] = next_token
    return p


# ---------------------------------------------------------------------------
# empty / no-action-group cases
# ---------------------------------------------------------------------------

def test_collect_agents_empty():
    client = MagicMock()
    client.list_agents.return_value = _agents_page([])
    assert collect_agents(client) == []


def test_collect_agents_no_action_groups():
    client = MagicMock()
    client.list_agents.return_value = _agents_page([_agent_summary("a1")])
    client.list_agent_action_groups.return_value = _ags_page([])
    result = collect_agents(client)
    assert len(result) == 1
    assert result[0]["agentId"] == "a1"
    assert result[0]["actionGroups"] == []


def test_collect_agents_output_fields():
    client = MagicMock()
    client.list_agents.return_value = _agents_page([_agent_summary("a1", "MyAgent", "PREPARED")])
    client.list_agent_action_groups.return_value = _ags_page([])
    result = collect_agents(client)
    r = result[0]
    assert r["agentId"] == "a1"
    assert r["agentName"] == "MyAgent"
    assert r["agentStatus"] == "PREPARED"
    assert r["actionGroups"] == []


# ---------------------------------------------------------------------------
# single agent with action groups
# ---------------------------------------------------------------------------

def test_collect_agents_embeds_action_group_details():
    client = MagicMock()
    client.list_agents.return_value = _agents_page([_agent_summary("a1")])
    client.list_agent_action_groups.return_value = _ags_page([_ag_summary("ag1")])
    client.get_agent_action_group.return_value = {"agentActionGroup": _ag_detail("ag1")}
    result = collect_agents(client)
    assert len(result[0]["actionGroups"]) == 1
    assert result[0]["actionGroups"][0]["actionGroupId"] == "ag1"


def test_collect_agents_uses_draft_version_for_action_groups():
    client = MagicMock()
    client.list_agents.return_value = _agents_page([_agent_summary("a1")])
    client.list_agent_action_groups.return_value = _ags_page([_ag_summary("ag1")])
    client.get_agent_action_group.return_value = {"agentActionGroup": _ag_detail("ag1")}
    collect_agents(client)
    list_call = client.list_agent_action_groups.call_args
    get_call = client.get_agent_action_group.call_args
    assert list_call.kwargs["agentVersion"] == _AGENT_VERSION
    assert get_call.kwargs["agentVersion"] == _AGENT_VERSION


def test_collect_agents_get_called_with_correct_ids():
    client = MagicMock()
    client.list_agents.return_value = _agents_page([_agent_summary("a1")])
    client.list_agent_action_groups.return_value = _ags_page([_ag_summary("ag1")])
    client.get_agent_action_group.return_value = {"agentActionGroup": _ag_detail("ag1")}
    collect_agents(client)
    client.get_agent_action_group.assert_called_once_with(
        agentId="a1", agentVersion=_AGENT_VERSION, actionGroupId="ag1"
    )


# ---------------------------------------------------------------------------
# pagination
# ---------------------------------------------------------------------------

def test_collect_agents_pagination_agents():
    client = MagicMock()
    client.list_agents.side_effect = [
        _agents_page([_agent_summary("a1")], next_token="tok1"),
        _agents_page([_agent_summary("a2", "AgentTwo")]),
    ]
    client.list_agent_action_groups.return_value = _ags_page([])
    result = collect_agents(client)
    assert len(result) == 2
    assert client.list_agents.call_args_list == [call(), call(nextToken="tok1")]


def test_collect_agents_pagination_action_groups():
    client = MagicMock()
    client.list_agents.return_value = _agents_page([_agent_summary("a1")])
    client.list_agent_action_groups.side_effect = [
        _ags_page([_ag_summary("ag1")], next_token="atok1"),
        _ags_page([_ag_summary("ag2")]),
    ]
    client.get_agent_action_group.side_effect = [
        {"agentActionGroup": _ag_detail("ag1")},
        {"agentActionGroup": _ag_detail("ag2")},
    ]
    result = collect_agents(client)
    assert len(result[0]["actionGroups"]) == 2
    assert client.list_agent_action_groups.call_args_list == [
        call(agentId="a1", agentVersion=_AGENT_VERSION),
        call(agentId="a1", agentVersion=_AGENT_VERSION, nextToken="atok1"),
    ]


def test_collect_agents_multiple_agents_multiple_action_groups():
    client = MagicMock()
    client.list_agents.return_value = _agents_page([
        _agent_summary("a1"), _agent_summary("a2", "AgentTwo"),
    ])
    client.list_agent_action_groups.side_effect = [
        _ags_page([_ag_summary("ag1")]),
        _ags_page([_ag_summary("ag2"), _ag_summary("ag3")]),
    ]
    client.get_agent_action_group.side_effect = [
        {"agentActionGroup": _ag_detail("ag1", "a1")},
        {"agentActionGroup": _ag_detail("ag2", "a2")},
        {"agentActionGroup": _ag_detail("ag3", "a2")},
    ]
    result = collect_agents(client)
    assert len(result) == 2
    assert len(result[0]["actionGroups"]) == 1
    assert len(result[1]["actionGroups"]) == 2


# ---------------------------------------------------------------------------
# failure semantics
# ---------------------------------------------------------------------------

def test_list_agents_failure_propagates():
    client = MagicMock()
    client.list_agents.side_effect = RuntimeError("network error")
    with pytest.raises(RuntimeError, match="network error"):
        collect_agents(client)


def test_per_agent_list_action_groups_failure_warns_and_continues():
    client = MagicMock()
    client.list_agents.return_value = _agents_page([
        _agent_summary("a1", "Bad"),
        _agent_summary("a2", "Good"),
    ])

    def list_ags_side_effect(**kwargs):
        if kwargs["agentId"] == "a1":
            raise RuntimeError("access denied")
        return _ags_page([])

    client.list_agent_action_groups.side_effect = list_ags_side_effect
    result = collect_agents(client)
    assert len(result) == 1
    assert result[0]["agentId"] == "a2"


def test_per_action_group_get_failure_warns_and_continues():
    client = MagicMock()
    client.list_agents.return_value = _agents_page([_agent_summary("a1")])
    client.list_agent_action_groups.return_value = _ags_page([
        _ag_summary("ag-bad"), _ag_summary("ag-good"),
    ])

    def get_ag_side_effect(**kwargs):
        if kwargs["actionGroupId"] == "ag-bad":
            raise RuntimeError("not found")
        return {"agentActionGroup": _ag_detail(kwargs["actionGroupId"])}

    client.get_agent_action_group.side_effect = get_ag_side_effect
    result = collect_agents(client)
    assert len(result) == 1
    assert len(result[0]["actionGroups"]) == 1
    assert result[0]["actionGroups"][0]["actionGroupId"] == "ag-good"


def test_per_action_group_get_failure_agent_still_emitted():
    """Agent record is still emitted even when some action groups fail."""
    client = MagicMock()
    client.list_agents.return_value = _agents_page([_agent_summary("a1", "MyAgent")])
    client.list_agent_action_groups.return_value = _ags_page([_ag_summary("ag-bad")])
    client.get_agent_action_group.side_effect = RuntimeError("not found")
    result = collect_agents(client)
    assert len(result) == 1
    assert result[0]["agentName"] == "MyAgent"
    assert result[0]["actionGroups"] == []


def test_list_agents_mid_pagination_failure_propagates():
    """Failure on second page of list_agents is still a list-level abort."""
    client = MagicMock()
    client.list_agents.side_effect = [
        _agents_page([_agent_summary("a1")], next_token="tok1"),
        RuntimeError("second page failed"),
    ]
    with pytest.raises(RuntimeError, match="second page failed"):
        collect_agents(client)
