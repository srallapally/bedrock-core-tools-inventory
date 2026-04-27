# src/artifacts.py
import json
import logging

logger = logging.getLogger(__name__)

ARTIFACT_NAMES = [
    "models.json",
    "model-bindings.json",
    "agent-bindings.json",
    "agent-tool-credentials.json",
    "principals.json",
    "manifest.json",
]


def _put(s3_client, bucket, key, data):
    body = json.dumps(data, indent=2).encode()
    s3_client.put_object(Bucket=bucket, Key=key, Body=body, ContentType="application/json")


def _copy_to_latest(s3_client, bucket, run_prefix):
    for name in ARTIFACT_NAMES:
        s3_client.copy_object(
            Bucket=bucket,
            CopySource={"Bucket": bucket, "Key": f"{run_prefix}{name}"},
            Key=f"latest/{name}",
        )


def write_artifacts(s3_client, bucket, run_prefix, payloads):
    """
    Upload all artifacts to run_prefix then promote to latest/.
    Any PutObject failure raises ClientError immediately — no partial writes to latest/.
    Per design §5.4: fail-fast on first upload error; latest/ is never partially updated.
    """
    for name in ARTIFACT_NAMES:
        key = f"{run_prefix}{name}"
        _put(s3_client, bucket, key, payloads[name])
        logger.info("uploaded %s", key)

    _copy_to_latest(s3_client, bucket, run_prefix)