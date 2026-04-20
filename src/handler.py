from config import load_config


def handler(event, context):
    cfg = load_config()
    return {"status": "ok", "region": cfg["region"], "run_prefix": cfg["run_prefix"]}
