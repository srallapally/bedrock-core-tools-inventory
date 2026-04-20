# tests/test_handler.py
from unittest.mock import MagicMock, patch
import json

import pytest

import handler as handler_module


@pytest.fixture()
def env(monkeypatch):
    monkeypatch.setenv("TARGET_REGION", "us-east-1")
    monkeypatch.setenv("OUTPUT_BUCKET", "test-bucket")
    monkeypatch.setenv("ACCOUNT_ID", "123456789012")


def _make_clients():
    bedrock = MagicMock()
    bedrock.list_foundation_models.return_value = {
        "modelSummaries": [
            {"modelId": "amazon.titan-text-express-v1", "modelName": "Titan Text Express",
             "providerName": "Amazon", "inputModalities": [], "outputModalities": [],
             "responseStreamingSupported": True, "customizationsSupported": [],
             "inferenceTypesSupported": [], "modelLifecycle": {}}
        ]
    }

    bedrock_agent = MagicMock()
    bedrock_agent.list_agents.return_value = {"agentSummaries": []}

    iam = MagicMock()
    iam.list_roles.return_value = {"Roles": [], "IsTruncated": False}
    iam.list_users.return_value = {"Users": [], "IsTruncated": False}

    s3 = MagicMock()

    return {"bedrock": bedrock, "bedrock-agent": bedrock_agent, "iam": iam, "s3": s3}


def test_handler_end_to_end(env):
    clients = _make_clients()

    def fake_make_client(service, region):
        return clients[service]

    with patch.object(handler_module, "make_client", side_effect=fake_make_client):
        result = handler_module.handler({}, None)

    assert result["statusCode"] == 200
    s3 = clients["s3"]
    assert s3.put_object.call_count == 5
    assert s3.copy_object.call_count == 5


def test_handler_raises_on_upload_failure(env):
    clients = _make_clients()
    clients["s3"].put_object.side_effect = Exception("S3 unavailable")

    def fake_make_client(service, region):
        return clients[service]

    with patch.object(handler_module, "make_client", side_effect=fake_make_client):
        with pytest.raises(RuntimeError, match="artifact upload failed"):
            handler_module.handler({}, None)
