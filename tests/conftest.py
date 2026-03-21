import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture(autouse=True)
def _reset_shared_state():
    """Clear global rate limiter and idempotency cache between tests."""
    from automox_mcp.utils.tooling import _IDEMPOTENCY_CACHE, _RATE_LIMITER

    _RATE_LIMITER._timestamps.clear()
    _IDEMPOTENCY_CACHE.clear()
    yield
    _RATE_LIMITER._timestamps.clear()
    _IDEMPOTENCY_CACHE.clear()
