# tests/test_artifacts.py
from unittest.mock import MagicMock

import pytest

from artifacts import ARTIFACT_NAMES, write_artifacts

BUCKET = "test-bucket"
RUN_PREFIX = "runs/123456789012/20260420T123456Z/"
PAYLOADS = {name: {"artifact": name} for name in ARTIFACT_NAMES}


def test_all_succeed_promotes_latest():
    s3 = MagicMock()
    uploaded, failed = write_artifacts(s3, BUCKET, RUN_PREFIX, PAYLOADS)
    assert failed == []
    assert set(uploaded) == set(ARTIFACT_NAMES)
    assert s3.copy_object.call_count == len(ARTIFACT_NAMES)


def test_partial_failure_skips_latest():
    s3 = MagicMock()
    fail_name = ARTIFACT_NAMES[1]

    def put_side_effect(*args, **kwargs):
        if kwargs.get("Key", "").endswith(fail_name):
            raise RuntimeError("upload failed")

    s3.put_object.side_effect = put_side_effect

    uploaded, failed = write_artifacts(s3, BUCKET, RUN_PREFIX, PAYLOADS)

    assert len(failed) == 1
    assert failed[0][0] == fail_name
    assert fail_name not in uploaded
    s3.copy_object.assert_not_called()


def test_all_fail_skips_latest():
    s3 = MagicMock()
    s3.put_object.side_effect = RuntimeError("upload failed")

    uploaded, failed = write_artifacts(s3, BUCKET, RUN_PREFIX, PAYLOADS)

    assert uploaded == []
    assert len(failed) == len(ARTIFACT_NAMES)
    s3.copy_object.assert_not_called()


def test_run_prefix_keys_are_correct():
    s3 = MagicMock()
    write_artifacts(s3, BUCKET, RUN_PREFIX, PAYLOADS)
    put_keys = {c.kwargs["Key"] for c in s3.put_object.call_args_list}
    assert put_keys == {f"{RUN_PREFIX}{name}" for name in ARTIFACT_NAMES}


def test_latest_keys_are_correct():
    s3 = MagicMock()
    write_artifacts(s3, BUCKET, RUN_PREFIX, PAYLOADS)
    dst_keys = {c.kwargs["Key"] for c in s3.copy_object.call_args_list}
    assert dst_keys == {f"latest/{name}" for name in ARTIFACT_NAMES}


def test_latest_copy_source_points_to_run_prefix():
    s3 = MagicMock()
    write_artifacts(s3, BUCKET, RUN_PREFIX, PAYLOADS)
    src_keys = {c.kwargs["CopySource"]["Key"] for c in s3.copy_object.call_args_list}
    assert src_keys == {f"{RUN_PREFIX}{name}" for name in ARTIFACT_NAMES}
