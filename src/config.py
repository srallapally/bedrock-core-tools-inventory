# src/config.py
import datetime
import os

import boto3


def _account_id_from_sts(region):
    client = boto3.client("sts", region_name=region)
    return client.get_caller_identity()["Account"]


def load_config(now=None):
    # B-13: env var names and fallback chain per design §12
    region = (
        os.environ.get("REGION")
        or os.environ.get("AWS_REGION")
        or "us-east-1"
    )

    # B-13: CORE_INVENTORY_BUCKET with default per design §12
    bucket = os.environ.get("CORE_INVENTORY_BUCKET", "bedrock-core-inventory")

    prefix = os.environ.get("OUTPUT_PREFIX", "bedrock-core-inventory/")

    account_id = os.environ.get("ACCOUNT_ID") or _account_id_from_sts(region)

    if now is None:
        now = datetime.datetime.utcnow()
    timestamp = now.strftime("%Y%m%dT%H%M%SZ")

    # B-14: path is bedrock-core-inventory/runs/<TIMESTAMP>/ per design §8.1
    # account ID is not embedded in the path
    run_prefix = f"{prefix}runs/{timestamp}/"

    return {
        "region": region,
        "bucket": bucket,
        "prefix": prefix,
        "account_id": account_id,
        "timestamp": timestamp,
        "run_prefix": run_prefix,
    }