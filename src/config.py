import os


def load_config():
    region = os.environ.get("TARGET_REGION")
    if not region:
        raise ValueError("TARGET_REGION is required")

    bucket = os.environ.get("OUTPUT_BUCKET")
    if not bucket:
        raise ValueError("OUTPUT_BUCKET is required")

    return {
        "region": region,
        "bucket": bucket,
        "prefix": os.environ.get("OUTPUT_PREFIX", "runs/"),
    }
