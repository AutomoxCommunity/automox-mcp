"""Crash-guard regression tests for policy workflows.

Covers two known-uncertain upstream-type defects:

* ``describe_policy`` decoded ``schedule_days`` guarded only by
  ``is not None``. A non-int value (e.g. the string ``"62"``) reached
  ``_decode_schedule_days_bitmask`` and raised ``TypeError`` on ``bitmask &
  0xFE``. The sibling ``summarize_policies`` already gates on
  ``isinstance(..., int)``; ``describe_policy`` must degrade the same way.
* ``summarize_policy_activity`` iterated the runs list without an
  ``isinstance(item, Mapping)`` guard and accepted any ``Sequence`` under
  ``data``. A ``data`` that is a string (or a list of scalars) made the loop
  call ``item.get(...)`` and raise ``AttributeError``.

Fixtures mirror the existing ``test_workflows_policy`` ``StubClient`` style.
"""

import copy
from typing import Any, cast
from uuid import UUID

import pytest

from automox_mcp.client import AutomoxClient
from automox_mcp.workflows.policy import (
    describe_policy,
    summarize_policy_activity,
)


class StubClient:
    """Minimal Automox client stub: feed canned GET responses per path."""

    def __init__(self, *, get_responses: dict[str, list[Any]] | None = None) -> None:
        self._get_responses = {key: list(value) for key, value in (get_responses or {}).items()}
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []

    async def get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        self.calls.append(("GET", path, params))
        responses = self._get_responses.get(path)
        if not responses:
            raise AssertionError(f"Unexpected GET request: {path}")
        return copy.deepcopy(responses.pop(0))


_ORG_UUID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


# ---------------------------------------------------------------------------
# describe_policy degrades when schedule_days is a non-int
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_describe_policy_non_int_schedule_days_degrades() -> None:
    """A string ``schedule_days`` must not crash the tool; it is skipped, not
    decoded (no schedule_interpretation), and the policy still returns."""
    policy = {
        "id": 10,
        "name": "Patch Everything",
        "policy_type_name": "patch",
        # Upstream-uncertain type: a string where an int bitmask is expected.
        "schedule_days": "62",
        "schedule_time": "02:00",
    }
    stub = StubClient(get_responses={"/policies/10": [policy]})

    result = await describe_policy(
        cast(AutomoxClient, stub),
        org_id=42,
        policy_id=10,
        include_recent_runs=0,
    )

    assert result["data"]["policy"]["id"] == 10
    # Decode was skipped — no interpretation / _important block confabulated.
    assert "schedule_interpretation" not in result["data"]
    assert "_important" not in result["data"]


@pytest.mark.asyncio
async def test_describe_policy_int_schedule_days_still_decodes() -> None:
    """Regression sibling: a real int bitmask still decodes (the guard does
    not over-reach and suppress valid values)."""
    policy = {
        "id": 11,
        "name": "Weekday Patching",
        "policy_type_name": "patch",
        "schedule_days": 62,  # Mon-Fri
        "schedule_time": "02:00",
    }
    stub = StubClient(get_responses={"/policies/11": [policy]})

    result = await describe_policy(
        cast(AutomoxClient, stub),
        org_id=42,
        policy_id=11,
        include_recent_runs=0,
    )

    assert (
        result["data"]["schedule_interpretation"]["interpretation"]
        == "Weekdays (Monday through Friday)"
    )


# ---------------------------------------------------------------------------
# summarize_policy_activity tolerates non-list / non-dict runs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_summarize_policy_activity_data_is_string() -> None:
    """A 200 body whose ``data`` is a string must yield zero runs, not an
    AttributeError from iterating per-character and calling ``.get``."""
    stub = StubClient(
        get_responses={
            "/policy-history/policy-run-count": [{"policy_runs": 0}],
            "/policy-history/policy-runs": [{"data": "not-a-list"}],
        }
    )

    result = await summarize_policy_activity(cast(AutomoxClient, stub), org_uuid=_ORG_UUID)

    assert result["data"]["total_runs_considered"] == 0
    assert result["data"]["status_breakdown"] == {}
    assert result["data"]["top_failing_policies"] == []


@pytest.mark.asyncio
async def test_summarize_policy_activity_data_is_list_of_scalars() -> None:
    """A ``data`` list of non-dict elements is skipped item-by-item via the
    Mapping guard — a sane empty summary, no crash."""
    stub = StubClient(
        get_responses={
            "/policy-history/policy-run-count": [{"policy_runs": 0}],
            "/policy-history/policy-runs": [{"data": ["alpha", 1, None]}],
        }
    )

    result = await summarize_policy_activity(cast(AutomoxClient, stub), org_uuid=_ORG_UUID)

    # All three list elements considered, but none counted (non-Mapping skipped).
    assert result["data"]["total_runs_considered"] == 3
    assert result["data"]["status_breakdown"] == {}
    assert result["data"]["top_failing_policies"] == []


@pytest.mark.asyncio
async def test_summarize_policy_activity_bare_string_response() -> None:
    """A bare non-list response (string) yields zero runs (the list-only
    acceptance rejects it)."""
    stub = StubClient(
        get_responses={
            "/policy-history/policy-run-count": [{"policy_runs": 0}],
            "/policy-history/policy-runs": ["unexpected-bare-string"],
        }
    )

    result = await summarize_policy_activity(cast(AutomoxClient, stub), org_uuid=_ORG_UUID)

    assert result["data"]["total_runs_considered"] == 0
    assert result["data"]["status_breakdown"] == {}
