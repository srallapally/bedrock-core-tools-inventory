# src/models.py


def _normalize(summary):
    return {
        "modelId": summary["modelId"],
        "modelName": summary.get("modelName", ""),
        "providerName": summary.get("providerName", ""),
        "inputModalities": summary.get("inputModalities", []),
        "outputModalities": summary.get("outputModalities", []),
        "responseStreamingSupported": summary.get("responseStreamingSupported", False),
        "customizationsSupported": summary.get("customizationsSupported", []),
        "inferenceTypesSupported": summary.get("inferenceTypesSupported", []),
        "lifecycleStatus": summary.get("modelLifecycle", {}).get("status", ""),
    }


def collect_models(bedrock_client):
    """
    Return normalized records for all foundation models.
    Defensive pagination loop handles a nextToken if the API ever adds one.
    """
    models = []
    kwargs = {}
    while True:
        resp = bedrock_client.list_foundation_models(**kwargs)
        for summary in resp.get("modelSummaries", []):
            models.append(_normalize(summary))
        next_token = resp.get("nextToken")
        if not next_token:
            break
        kwargs["nextToken"] = next_token
    return models
