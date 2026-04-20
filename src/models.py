# src/models.py


def _normalize(summary, account_id, region):
    # modelArn: use API field if present; construct from modelId as fallback.
    # Foundation-model ARNs have an empty account segment (global namespace).
    model_arn = summary.get("modelArn") or (
        f"arn:aws:bedrock:{region}::foundation-model/{summary['modelId']}"
    )
    return {
        "modelId": summary["modelId"],
        "modelArn": model_arn,
        "modelName": summary.get("modelName", ""),
        "providerName": summary.get("providerName", ""),
        "inputModalities": summary.get("inputModalities", []),
        "outputModalities": summary.get("outputModalities", []),
        "responseStreamingSupported": summary.get("responseStreamingSupported", False),
        "customizationsSupported": summary.get("customizationsSupported", []),
        "inferenceTypesSupported": summary.get("inferenceTypesSupported", []),
        "accountId": account_id,
        "region": region,
    }


def collect_models(bedrock_client, account_id, region):
    """
    Return normalized records for all foundation models.
    Defensive pagination loop handles a nextToken if the API ever adds one.
    account_id and region are stamped on every record per design §8.2.
    """
    models = []
    kwargs = {}
    while True:
        resp = bedrock_client.list_foundation_models(**kwargs)
        for summary in resp.get("modelSummaries", []):
            models.append(_normalize(summary, account_id, region))
        next_token = resp.get("nextToken")
        if not next_token:
            break
        kwargs["nextToken"] = next_token
    return models