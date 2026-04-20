# src/iam_fetch.py
import json
import logging
import urllib.parse

logger = logging.getLogger(__name__)

_ENTITY_KEY = {
    "role": "RoleName",
    "user": "UserName",
    "group": "GroupName",
}

_INLINE_LIST_METHOD = {
    "role": "list_role_policies",
    "user": "list_user_policies",
    "group": "list_group_policies",
}

_INLINE_GET_METHOD = {
    "role": "get_role_policy",
    "user": "get_user_policy",
    "group": "get_group_policy",
}

_ATTACHED_LIST_METHOD = {
    "role": "list_attached_role_policies",
    "user": "list_attached_user_policies",
    "group": "list_attached_group_policies",
}


def _paginate_iam(method, result_key, **kwargs):
    """Accumulate pages from an IAM list call using IsTruncated/Marker."""
    items = []
    while True:
        resp = method(**kwargs)
        items.extend(resp[result_key])
        if not resp.get("IsTruncated"):
            break
        kwargs["Marker"] = resp["Marker"]
    return items


def _parse_policy_doc(raw):
    """Accept a policy document as a dict or a URL-encoded JSON string."""
    if isinstance(raw, dict):
        return raw
    return json.loads(urllib.parse.unquote(raw))


# ---------------------------------------------------------------------------
# List operations — list-level failures propagate to the caller
# ---------------------------------------------------------------------------

def list_roles(iam_client):
    return _paginate_iam(iam_client.list_roles, "Roles")


def list_users(iam_client):
    return _paginate_iam(iam_client.list_users, "Users")


def list_groups(iam_client):
    return _paginate_iam(iam_client.list_groups, "Groups")


# ---------------------------------------------------------------------------
# Per-entity policy fetchers — per-document failures warn and continue
# ---------------------------------------------------------------------------

def fetch_inline_policies(iam_client, entity_type, entity_name):
    """
    Return [{name, document}] for every inline policy attached to the entity.
    Failure to list policy names propagates. Per-document read failures warn and continue.
    """
    entity_key = _ENTITY_KEY[entity_type]
    list_method = getattr(iam_client, _INLINE_LIST_METHOD[entity_type])
    get_method = getattr(iam_client, _INLINE_GET_METHOD[entity_type])

    policy_names = _paginate_iam(
        list_method, "PolicyNames", **{entity_key: entity_name}
    )

    results = []
    for name in policy_names:
        try:
            resp = get_method(**{entity_key: entity_name, "PolicyName": name})
            results.append({
                "name": name,
                "document": _parse_policy_doc(resp["PolicyDocument"]),
            })
        except Exception as exc:
            logger.warning(
                "skipping inline policy %s on %s/%s: %s", name, entity_type, entity_name, exc
            )
    return results


def fetch_attached_policies(iam_client, entity_type, entity_name):
    """
    Return [{name, arn, document}] for every managed policy attached to the entity.
    Failure to list attachments propagates. Per-document read failures warn and continue.
    """
    entity_key = _ENTITY_KEY[entity_type]
    list_method = getattr(iam_client, _ATTACHED_LIST_METHOD[entity_type])

    attached = _paginate_iam(
        list_method, "AttachedPolicies", **{entity_key: entity_name}
    )

    results = []
    for policy in attached:
        arn = policy["PolicyArn"]
        pol_name = policy["PolicyName"]
        try:
            version_id = iam_client.get_policy(PolicyArn=arn)["Policy"]["DefaultVersionId"]
            doc_resp = iam_client.get_policy_version(PolicyArn=arn, VersionId=version_id)
            results.append({
                "name": pol_name,
                "arn": arn,
                "document": _parse_policy_doc(doc_resp["PolicyVersion"]["Document"]),
            })
        except Exception as exc:
            logger.warning(
                "skipping managed policy %s (%s) on %s/%s: %s",
                pol_name, arn, entity_type, entity_name, exc,
            )
    return results
