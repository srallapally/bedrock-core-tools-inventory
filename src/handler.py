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
from agent_bindings import scan_agent_bindings, build_agent_bindings_payload
from manifest import build_manifest
from artifacts import write_artifacts

logger = logging.getLogger(__name__)


def handler(event, context):
    cfg = load_config()

    bedrock = make_client("bedrock", cfg["region"])
    bedrock_agent = make_client("bedrock-agent", cfg["region"])
    iam = make_client("iam", cfg["region"])
    s3 = make_client("s3", cfg["region"])
    # OPENICF-432
    lambda_client = make_client("lambda", cfg["region"])

    models = collect_models(bedrock, cfg["account_id"], cfg["region"])

    roles = list_roles(iam)
    users = list_users(iam)

    role_candidates = scan_roles(iam, roles)
    user_candidates = scan_users(iam, users)
    bindings, principals = normalize_bindings(role_candidates, user_candidates)

    agent_bindings = scan_agent_bindings(iam, roles, users, cfg["account_id"])
    agent_bindings_payload = build_agent_bindings_payload(
        agent_bindings, cfg["account_id"], cfg["region"]
    )

    agents = collect_agents(bedrock_agent)
    # OPENICF-432: pass lambda_client to populate lambdaExecutionRoleArn
    tool_credentials = normalize_tool_credentials(
        agents, cfg["account_id"], cfg["region"], lambda_client=lambda_client
    )

    manifest = build_manifest(cfg, models, bindings, agent_bindings, tool_credentials, principals)

    payloads = {
        "models.json": models,
        "model-bindings.json": bindings,
        "agent-bindings.json": agent_bindings_payload,
        "agent-tool-credentials.json": tool_credentials,
        "principals.json": principals,
        "manifest.json": manifest,
    }

    # write_artifacts raises ClientError on any upload failure — no try/except here.
    # The Lambda runtime will catch the exception and mark the invocation failed.
    write_artifacts(s3, cfg["bucket"], cfg["run_prefix"], payloads)

    return {"statusCode": 200, "run_prefix": cfg["run_prefix"]}