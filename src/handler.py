# src/handler.py
import logging

from config import load_config
from aws_clients import make_client
from models import collect_models
from iam_fetch import list_roles, list_users
from role_scan import scan_roles
from user_scan import scan_users
from normalize import normalize_bindings
from agents import collect_agents
from tool_credentials import normalize_tool_credentials
from manifest import build_manifest
from artifacts import write_artifacts

logger = logging.getLogger(__name__)


def handler(event, context):
    cfg = load_config()

    bedrock = make_client("bedrock", cfg["region"])
    bedrock_agent = make_client("bedrock-agent", cfg["region"])
    iam = make_client("iam", cfg["region"])
    s3 = make_client("s3", cfg["region"])

    models = collect_models(bedrock)

    roles = list_roles(iam)
    role_candidates = scan_roles(iam, roles)

    users = list_users(iam)
    user_candidates = scan_users(iam, users)

    bindings, principals = normalize_bindings(role_candidates, user_candidates)

    agents = collect_agents(bedrock_agent)
    tool_credentials = normalize_tool_credentials(agents, cfg["account_id"], cfg["region"])

    manifest = build_manifest(cfg, models, bindings, tool_credentials, principals)

    payloads = {
        "models.json": models,
        "model-bindings.json": bindings,
        "agent-tool-credentials.json": tool_credentials,
        "principals.json": principals,
        "manifest.json": manifest,
    }

    uploaded, failed = write_artifacts(s3, cfg["bucket"], cfg["run_prefix"], payloads)

    if failed:
        names = [name for name, _ in failed]
        raise RuntimeError(f"artifact upload failed: {names}")

    return {"statusCode": 200, "uploaded": uploaded, "run_prefix": cfg["run_prefix"]}
