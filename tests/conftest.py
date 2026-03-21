import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Clear the global rate limiter between tests to prevent cross-test pollution."""
    from automox_mcp.utils.tooling import _RATE_LIMITER

    _RATE_LIMITER._timestamps.clear()
    yield
    _RATE_LIMITER._timestamps.clear()
