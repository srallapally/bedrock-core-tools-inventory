import pytest
from config import load_config


def test_load_config_success(monkeypatch):
    monkeypatch.setenv("TARGET_REGION", "us-east-1")
    monkeypatch.setenv("OUTPUT_BUCKET", "my-bucket")
    cfg = load_config()
    assert cfg["region"] == "us-east-1"
    assert cfg["bucket"] == "my-bucket"
    assert cfg["prefix"] == "runs/"


def test_load_config_custom_prefix(monkeypatch):
    monkeypatch.setenv("TARGET_REGION", "us-west-2")
    monkeypatch.setenv("OUTPUT_BUCKET", "my-bucket")
    monkeypatch.setenv("OUTPUT_PREFIX", "custom/")
    cfg = load_config()
    assert cfg["prefix"] == "custom/"


def test_load_config_missing_region(monkeypatch):
    monkeypatch.delenv("TARGET_REGION", raising=False)
    monkeypatch.setenv("OUTPUT_BUCKET", "my-bucket")
    with pytest.raises(ValueError, match="TARGET_REGION"):
        load_config()


def test_load_config_missing_bucket(monkeypatch):
    monkeypatch.setenv("TARGET_REGION", "us-east-1")
    monkeypatch.delenv("OUTPUT_BUCKET", raising=False)
    with pytest.raises(ValueError, match="OUTPUT_BUCKET"):
        load_config()
