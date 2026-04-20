import datetime
from unittest.mock import MagicMock, patch

import pytest

from config import load_config

FIXED_NOW = datetime.datetime(2026, 4, 20, 12, 34, 56)


def test_account_id_from_env_not_sts(monkeypatch):
    monkeypatch.setenv("TARGET_REGION", "us-east-1")
    monkeypatch.setenv("OUTPUT_BUCKET", "my-bucket")
    monkeypatch.setenv("ACCOUNT_ID", "123456789012")
    with patch("config.boto3.client") as mock_boto:
        cfg = load_config(now=FIXED_NOW)
    mock_boto.assert_not_called()
    assert cfg["account_id"] == "123456789012"


def test_account_id_falls_back_to_sts(monkeypatch):
    monkeypatch.setenv("TARGET_REGION", "us-east-1")
    monkeypatch.setenv("OUTPUT_BUCKET", "my-bucket")
    monkeypatch.delenv("ACCOUNT_ID", raising=False)
    mock_sts = MagicMock()
    mock_sts.get_caller_identity.return_value = {"Account": "999888777666"}
    with patch("config.boto3.client", return_value=mock_sts):
        cfg = load_config(now=FIXED_NOW)
    mock_sts.get_caller_identity.assert_called_once()
    assert cfg["account_id"] == "999888777666"


def test_run_prefix_format(monkeypatch):
    monkeypatch.setenv("TARGET_REGION", "us-east-1")
    monkeypatch.setenv("OUTPUT_BUCKET", "my-bucket")
    monkeypatch.setenv("ACCOUNT_ID", "123456789012")
    cfg = load_config(now=FIXED_NOW)
    assert cfg["run_prefix"] == "runs/123456789012/20260420T123456Z/"


def test_custom_prefix_in_run_prefix(monkeypatch):
    monkeypatch.setenv("TARGET_REGION", "us-east-1")
    monkeypatch.setenv("OUTPUT_BUCKET", "my-bucket")
    monkeypatch.setenv("ACCOUNT_ID", "123456789012")
    monkeypatch.setenv("OUTPUT_PREFIX", "archive/")
    cfg = load_config(now=FIXED_NOW)
    assert cfg["run_prefix"] == "archive/123456789012/20260420T123456Z/"


def test_timestamp_is_deterministic(monkeypatch):
    monkeypatch.setenv("TARGET_REGION", "us-east-1")
    monkeypatch.setenv("OUTPUT_BUCKET", "my-bucket")
    monkeypatch.setenv("ACCOUNT_ID", "123456789012")
    cfg = load_config(now=FIXED_NOW)
    assert cfg["timestamp"] == "20260420T123456Z"


def test_missing_region_raises(monkeypatch):
    monkeypatch.delenv("TARGET_REGION", raising=False)
    monkeypatch.setenv("OUTPUT_BUCKET", "my-bucket")
    with pytest.raises(ValueError, match="TARGET_REGION"):
        load_config()


def test_missing_bucket_raises(monkeypatch):
    monkeypatch.setenv("TARGET_REGION", "us-east-1")
    monkeypatch.delenv("OUTPUT_BUCKET", raising=False)
    with pytest.raises(ValueError, match="OUTPUT_BUCKET"):
        load_config()
