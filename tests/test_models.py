# tests/test_models.py
from unittest.mock import MagicMock, call

from models import collect_models

_FULL = {
    "modelId": "amazon.titan-text-express-v1",
    "modelName": "Titan Text Express",
    "providerName": "Amazon",
    "inputModalities": ["TEXT"],
    "outputModalities": ["TEXT"],
    "responseStreamingSupported": True,
    "customizationsSupported": ["FINE_TUNING"],
    "inferenceTypesSupported": ["ON_DEMAND"],
    "modelLifecycle": {"status": "ACTIVE"},
}


def test_empty_response():
    client = MagicMock()
    client.list_foundation_models.return_value = {"modelSummaries": []}
    assert collect_models(client) == []
    client.list_foundation_models.assert_called_once_with()


def test_single_page():
    client = MagicMock()
    client.list_foundation_models.return_value = {"modelSummaries": [_FULL]}
    models = collect_models(client)
    assert len(models) == 1
    m = models[0]
    assert m["modelId"] == "amazon.titan-text-express-v1"
    assert m["modelName"] == "Titan Text Express"
    assert m["providerName"] == "Amazon"
    assert m["inputModalities"] == ["TEXT"]
    assert m["outputModalities"] == ["TEXT"]
    assert m["responseStreamingSupported"] is True
    assert m["customizationsSupported"] == ["FINE_TUNING"]
    assert m["inferenceTypesSupported"] == ["ON_DEMAND"]
    assert m["lifecycleStatus"] == "ACTIVE"
    client.list_foundation_models.assert_called_once_with()


def test_paginated_two_pages():
    client = MagicMock()
    page1 = {
        "modelSummaries": [{"modelId": "model-a", **{k: _FULL[k] for k in _FULL if k != "modelId"}}],
        "nextToken": "tok-1",
    }
    page2 = {
        "modelSummaries": [{"modelId": "model-b", **{k: _FULL[k] for k in _FULL if k != "modelId"}}],
    }
    client.list_foundation_models.side_effect = [page1, page2]
    models = collect_models(client)
    assert len(models) == 2
    assert models[0]["modelId"] == "model-a"
    assert models[1]["modelId"] == "model-b"
    assert client.list_foundation_models.call_count == 2
    assert client.list_foundation_models.call_args_list[0] == call()
    assert client.list_foundation_models.call_args_list[1] == call(nextToken="tok-1")


def test_missing_optional_fields_use_defaults():
    client = MagicMock()
    client.list_foundation_models.return_value = {
        "modelSummaries": [{"modelId": "bare-model"}]
    }
    models = collect_models(client)
    m = models[0]
    assert m["modelName"] == ""
    assert m["providerName"] == ""
    assert m["inputModalities"] == []
    assert m["outputModalities"] == []
    assert m["responseStreamingSupported"] is False
    assert m["customizationsSupported"] == []
    assert m["inferenceTypesSupported"] == []
    assert m["lifecycleStatus"] == ""


def test_missing_model_lifecycle_defaults_status():
    client = MagicMock()
    client.list_foundation_models.return_value = {
        "modelSummaries": [{"modelId": "m1", "modelLifecycle": {}}]
    }
    models = collect_models(client)
    assert models[0]["lifecycleStatus"] == ""
