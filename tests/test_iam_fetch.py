# tests/test_iam_fetch.py
import json
import urllib.parse
from unittest.mock import MagicMock, call

import pytest

from iam_fetch import (
    fetch_attached_policies,
    fetch_inline_policies,
    list_groups,
    list_roles,
    list_users,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

_DOC = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "*", "Resource": "*"}]}


def _page(result_key, items, truncated=False, marker=None):
    p = {result_key: items, "IsTruncated": truncated}
    if marker:
        p["Marker"] = marker
    return p


def _role(name):
    return {"RoleName": name, "Arn": f"arn:aws:iam::123:role/{name}"}


def _user(name):
    return {"UserName": name, "Arn": f"arn:aws:iam::123:user/{name}"}


def _group(name):
    return {"GroupName": name, "Arn": f"arn:aws:iam::123:group/{name}"}


def _attached(name, arn=None):
    arn = arn or f"arn:aws:iam::123456789012:policy/{name}"
    return {"PolicyName": name, "PolicyArn": arn}


# ---------------------------------------------------------------------------
# list_roles
# ---------------------------------------------------------------------------

def test_list_roles_single_page():
    iam = MagicMock()
    iam.list_roles.return_value = _page("Roles", [_role("R1"), _role("R2")])
    roles = list_roles(iam)
    assert [r["RoleName"] for r in roles] == ["R1", "R2"]
    iam.list_roles.assert_called_once_with()


def test_list_roles_two_pages():
    iam = MagicMock()
    iam.list_roles.side_effect = [
        _page("Roles", [_role("R1")], truncated=True, marker="m1"),
        _page("Roles", [_role("R2")]),
    ]
    roles = list_roles(iam)
    assert [r["RoleName"] for r in roles] == ["R1", "R2"]
    assert iam.list_roles.call_args_list == [call(), call(Marker="m1")]


def test_list_roles_propagates_list_failure():
    iam = MagicMock()
    iam.list_roles.side_effect = RuntimeError("access denied")
    with pytest.raises(RuntimeError, match="access denied"):
        list_roles(iam)


# ---------------------------------------------------------------------------
# list_users
# ---------------------------------------------------------------------------

def test_list_users_single_page():
    iam = MagicMock()
    iam.list_users.return_value = _page("Users", [_user("U1")])
    assert list_users(iam) == [_user("U1")]
    iam.list_users.assert_called_once_with()


def test_list_users_propagates_list_failure():
    iam = MagicMock()
    iam.list_users.side_effect = RuntimeError("throttled")
    with pytest.raises(RuntimeError):
        list_users(iam)


# ---------------------------------------------------------------------------
# list_groups
# ---------------------------------------------------------------------------

def test_list_groups_single_page():
    iam = MagicMock()
    iam.list_groups.return_value = _page("Groups", [_group("G1")])
    assert list_groups(iam) == [_group("G1")]
    iam.list_groups.assert_called_once_with()


def test_list_groups_propagates_list_failure():
    iam = MagicMock()
    iam.list_groups.side_effect = RuntimeError("throttled")
    with pytest.raises(RuntimeError):
        list_groups(iam)


# ---------------------------------------------------------------------------
# fetch_inline_policies — role
# ---------------------------------------------------------------------------

def test_fetch_inline_role_calls_correct_methods():
    iam = MagicMock()
    iam.list_role_policies.return_value = _page("PolicyNames", ["P1"])
    iam.get_role_policy.return_value = {"PolicyDocument": _DOC}
    results = fetch_inline_policies(iam, "role", "MyRole")
    iam.list_role_policies.assert_called_once_with(RoleName="MyRole")
    iam.get_role_policy.assert_called_once_with(RoleName="MyRole", PolicyName="P1")
    assert results == [{"name": "P1", "document": _DOC}]


def test_fetch_inline_role_multiple_policies():
    iam = MagicMock()
    iam.list_role_policies.return_value = _page("PolicyNames", ["P1", "P2"])
    iam.get_role_policy.return_value = {"PolicyDocument": _DOC}
    results = fetch_inline_policies(iam, "role", "MyRole")
    assert len(results) == 2
    assert {r["name"] for r in results} == {"P1", "P2"}


def test_fetch_inline_role_paginated_names():
    iam = MagicMock()
    iam.list_role_policies.side_effect = [
        _page("PolicyNames", ["P1"], truncated=True, marker="mk"),
        _page("PolicyNames", ["P2"]),
    ]
    iam.get_role_policy.return_value = {"PolicyDocument": _DOC}
    results = fetch_inline_policies(iam, "role", "MyRole")
    assert len(results) == 2
    assert iam.list_role_policies.call_args_list == [
        call(RoleName="MyRole"),
        call(RoleName="MyRole", Marker="mk"),
    ]


def test_fetch_inline_role_get_failure_warns_and_continues():
    iam = MagicMock()
    iam.list_role_policies.return_value = _page("PolicyNames", ["Bad", "Good"])

    def get_side_effect(**kwargs):
        if kwargs["PolicyName"] == "Bad":
            raise RuntimeError("NoSuchEntity")
        return {"PolicyDocument": _DOC}

    iam.get_role_policy.side_effect = get_side_effect
    results = fetch_inline_policies(iam, "role", "MyRole")
    assert len(results) == 1
    assert results[0]["name"] == "Good"


def test_fetch_inline_role_list_failure_propagates():
    iam = MagicMock()
    iam.list_role_policies.side_effect = RuntimeError("access denied")
    with pytest.raises(RuntimeError, match="access denied"):
        fetch_inline_policies(iam, "role", "MyRole")


def test_fetch_inline_role_url_encoded_document():
    encoded = urllib.parse.quote(json.dumps(_DOC))
    iam = MagicMock()
    iam.list_role_policies.return_value = _page("PolicyNames", ["P1"])
    iam.get_role_policy.return_value = {"PolicyDocument": encoded}
    results = fetch_inline_policies(iam, "role", "MyRole")
    assert results[0]["document"] == _DOC


# ---------------------------------------------------------------------------
# fetch_inline_policies — user and group dispatch
# ---------------------------------------------------------------------------

def test_fetch_inline_user_calls_correct_methods():
    iam = MagicMock()
    iam.list_user_policies.return_value = _page("PolicyNames", ["UP1"])
    iam.get_user_policy.return_value = {"PolicyDocument": _DOC}
    results = fetch_inline_policies(iam, "user", "Alice")
    iam.list_user_policies.assert_called_once_with(UserName="Alice")
    iam.get_user_policy.assert_called_once_with(UserName="Alice", PolicyName="UP1")
    assert results[0]["name"] == "UP1"


def test_fetch_inline_group_calls_correct_methods():
    iam = MagicMock()
    iam.list_group_policies.return_value = _page("PolicyNames", ["GP1"])
    iam.get_group_policy.return_value = {"PolicyDocument": _DOC}
    results = fetch_inline_policies(iam, "group", "Devs")
    iam.list_group_policies.assert_called_once_with(GroupName="Devs")
    iam.get_group_policy.assert_called_once_with(GroupName="Devs", PolicyName="GP1")
    assert results[0]["name"] == "GP1"


# ---------------------------------------------------------------------------
# fetch_attached_policies — role
# ---------------------------------------------------------------------------

def test_fetch_attached_role_calls_correct_methods():
    iam = MagicMock()
    iam.list_attached_role_policies.return_value = _page(
        "AttachedPolicies", [_attached("MP1")]
    )
    iam.get_policy.return_value = {"Policy": {"DefaultVersionId": "v3"}}
    iam.get_policy_version.return_value = {"PolicyVersion": {"Document": _DOC}}

    results = fetch_attached_policies(iam, "role", "MyRole")

    iam.list_attached_role_policies.assert_called_once_with(RoleName="MyRole")
    iam.get_policy.assert_called_once_with(PolicyArn="arn:aws:iam::123456789012:policy/MP1")
    iam.get_policy_version.assert_called_once_with(
        PolicyArn="arn:aws:iam::123456789012:policy/MP1", VersionId="v3"
    )
    assert results == [{"name": "MP1", "arn": "arn:aws:iam::123456789012:policy/MP1", "document": _DOC}]


def test_fetch_attached_role_get_failure_warns_and_continues():
    iam = MagicMock()
    iam.list_attached_role_policies.return_value = _page(
        "AttachedPolicies",
        [_attached("Bad", "arn:aws:iam::123:policy/Bad"),
         _attached("Good", "arn:aws:iam::123:policy/Good")],
    )

    def get_policy_side_effect(**kwargs):
        if "Bad" in kwargs["PolicyArn"]:
            raise RuntimeError("no such policy")
        return {"Policy": {"DefaultVersionId": "v1"}}

    iam.get_policy.side_effect = get_policy_side_effect
    iam.get_policy_version.return_value = {"PolicyVersion": {"Document": _DOC}}

    results = fetch_attached_policies(iam, "role", "MyRole")
    assert len(results) == 1
    assert results[0]["name"] == "Good"


def test_fetch_attached_role_list_failure_propagates():
    iam = MagicMock()
    iam.list_attached_role_policies.side_effect = RuntimeError("access denied")
    with pytest.raises(RuntimeError, match="access denied"):
        fetch_attached_policies(iam, "role", "MyRole")


def test_fetch_attached_role_url_encoded_document():
    encoded = urllib.parse.quote(json.dumps(_DOC))
    iam = MagicMock()
    iam.list_attached_role_policies.return_value = _page(
        "AttachedPolicies", [_attached("MP1")]
    )
    iam.get_policy.return_value = {"Policy": {"DefaultVersionId": "v1"}}
    iam.get_policy_version.return_value = {"PolicyVersion": {"Document": encoded}}
    results = fetch_attached_policies(iam, "role", "MyRole")
    assert results[0]["document"] == _DOC


# ---------------------------------------------------------------------------
# fetch_attached_policies — user and group dispatch
# ---------------------------------------------------------------------------

def test_fetch_attached_user_calls_correct_method():
    iam = MagicMock()
    iam.list_attached_user_policies.return_value = _page(
        "AttachedPolicies", [_attached("UP")]
    )
    iam.get_policy.return_value = {"Policy": {"DefaultVersionId": "v1"}}
    iam.get_policy_version.return_value = {"PolicyVersion": {"Document": _DOC}}
    fetch_attached_policies(iam, "user", "Alice")
    iam.list_attached_user_policies.assert_called_once_with(UserName="Alice")


def test_fetch_attached_group_calls_correct_method():
    iam = MagicMock()
    iam.list_attached_group_policies.return_value = _page(
        "AttachedPolicies", [_attached("GP")]
    )
    iam.get_policy.return_value = {"Policy": {"DefaultVersionId": "v1"}}
    iam.get_policy_version.return_value = {"PolicyVersion": {"Document": _DOC}}
    fetch_attached_policies(iam, "group", "Devs")
    iam.list_attached_group_policies.assert_called_once_with(GroupName="Devs")
