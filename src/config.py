# src/config.py
import datetime
import os

import boto3


def _account_id_from_sts(region):
    client = boto3.client("sts", region_name=region)
    return client.get_caller_identity()["Account"]


def load_config(now=None):
    region = os.environ.get("TARGET_REGION")
    if not region:
        raise ValueError("TARGET_REGION is required")

    bucket = os.environ.get("OUTPUT_BUCKET")
    if not bucket:
        raise ValueError("OUTPUT_BUCKET is required")

    prefix = os.environ.get("OUTPUT_PREFIX", "runs/")

    account_id = os.environ.get("ACCOUNT_ID") or _account_id_from_sts(region)

    if now is None:
        now = datetime.datetime.utcnow()
    timestamp = now.strftime("%Y%m%dT%H%M%SZ")

    run_prefix = f"{prefix}{account_id}/{timestamp}/"

    return {
        "region": region,
        "bucket": bucket,
        "prefix": prefix,
        "account_id": account_id,
        "timestamp": timestamp,
        "run_prefix": run_prefix,
    }
