# src/retry.py
import random
import time

from botocore.exceptions import ClientError

_THROTTLE_CODES = frozenset({
    "Throttling",
    "ThrottlingException",
    "RequestLimitExceeded",
    "TooManyRequestsException",
})


def with_retry(fn, max_attempts=5, base_delay=1.0):
    """
    Call fn(), retrying on throttle errors with full-jitter exponential backoff.
    Raises immediately on non-throttle errors. Raises after max_attempts exhausted.
    """
    for attempt in range(max_attempts):
        try:
            return fn()
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code not in _THROTTLE_CODES:
                raise
            if attempt == max_attempts - 1:
                raise
            delay = random.uniform(0, base_delay * (2 ** attempt))
            time.sleep(delay)
