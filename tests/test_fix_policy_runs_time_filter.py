"""Bug #17: list_policy_runs_v2 time filter must compare datetimes, not strings.

The upstream policy-report-api ignores time filter params, so the workflow
filters client-side. The old code did a raw lexicographic STRING compare of
run_time against start_time/end_time. A bare-date end_time='2026-06-18' makes
'2026-06-18T16:52:44.313Z' > '2026-06-18' true, so every run on that day was
silently dropped — "runs through June 18" returned none of that day's runs.
Mixed 'Z' vs '+00:00' forms also sorted wrong. The fix parses both sides into
tz-aware datetimes and normalizes a bare date to an inclusive day boundary.
"""

from typing import Any, cast

import pytest
from conftest import StubClient

from automox_mcp.client import AutomoxClient
from automox_mcp.workflows.policy_history import list_policy_runs_v2

_ORG_UUID = "11111111-2222-3333-4444-555555555555"


def _make_client(**kwargs: Any) -> StubClient:
    client = StubClient(**kwargs)
    client.org_uuid = _ORG_UUID
    return client


def _run(uuid: str, run_time: str) -> dict[str, Any]:
    # policy_name is set so the call always engages the client-side filter
    # path even when only a time bound is exercised.
    return {"policy_uuid": uuid, "policy_name": "Patch All", "run_time": run_time}


# run_time as the live API emits it: full ISO-8601 with millis + trailing Z.
_RUNS_JUNE_18 = [
    _run("r-early", "2026-06-18T00:00:01.000Z"),
    _run("r-mid", "2026-06-18T16:52:44.313Z"),
    _run("r-late", "2026-06-18T23:59:59.999Z"),
]


@pytest.mark.asyncio
async def test_bare_date_end_time_includes_whole_day() -> None:
    """end_time='2026-06-18' must INCLUDE every run on 2026-06-18, not drop
    them via a lexicographic string compare (the core bug #17)."""
    client = _make_client(get_responses={"/policy-history/policy-runs": [_RUNS_JUNE_18]})
    result = await list_policy_runs_v2(
        cast(AutomoxClient, client),
        org_id=42,
        end_time="2026-06-18",
    )
    returned = sorted(r["policy_uuid"] for r in result["data"]["runs"])
    assert returned == ["r-early", "r-late", "r-mid"]


@pytest.mark.asyncio
async def test_bare_date_end_time_excludes_next_day() -> None:
    """The inclusive end-of-day boundary must not bleed into the next day."""
    runs = [
        _run("keep", "2026-06-18T23:59:59.999Z"),
        _run("drop", "2026-06-19T00:00:00.000Z"),
    ]
    client = _make_client(get_responses={"/policy-history/policy-runs": [runs]})
    result = await list_policy_runs_v2(
        cast(AutomoxClient, client),
        org_id=42,
        end_time="2026-06-18",
    )
    returned = [r["policy_uuid"] for r in result["data"]["runs"]]
    assert returned == ["keep"]


@pytest.mark.asyncio
async def test_bare_date_start_time_inclusive_at_start_of_day() -> None:
    """start_time='2026-06-18' anchors to 00:00:00 UTC, so a run at the very
    start of the day is included and the prior day is excluded."""
    runs = [
        _run("prev", "2026-06-17T23:59:59.999Z"),
        _run("boundary", "2026-06-18T00:00:00.000Z"),
        _run("later", "2026-06-18T12:00:00.000Z"),
    ]
    client = _make_client(get_responses={"/policy-history/policy-runs": [runs]})
    result = await list_policy_runs_v2(
        cast(AutomoxClient, client),
        org_id=42,
        start_time="2026-06-18",
    )
    returned = sorted(r["policy_uuid"] for r in result["data"]["runs"])
    assert returned == ["boundary", "later"]


@pytest.mark.asyncio
async def test_mixed_zone_forms_compare_correctly() -> None:
    """A 'Z' run_time and a '+00:00' bound denote the same instant and must
    not sort wrong the way raw string comparison would."""
    runs = [
        _run("before", "2026-06-18T09:59:59Z"),
        _run("after", "2026-06-18T10:00:01Z"),
    ]
    client = _make_client(get_responses={"/policy-history/policy-runs": [runs]})
    result = await list_policy_runs_v2(
        cast(AutomoxClient, client),
        org_id=42,
        start_time="2026-06-18T10:00:00+00:00",
    )
    returned = [r["policy_uuid"] for r in result["data"]["runs"]]
    assert returned == ["after"]


@pytest.mark.asyncio
async def test_full_timestamp_end_time_inclusive_at_bound() -> None:
    """A full-timestamp end_time keeps inclusive-at-the-bound semantics."""
    runs = [
        _run("at-bound", "2026-06-18T10:00:00Z"),
        _run("past-bound", "2026-06-18T10:00:00.001Z"),
    ]
    client = _make_client(get_responses={"/policy-history/policy-runs": [runs]})
    result = await list_policy_runs_v2(
        cast(AutomoxClient, client),
        org_id=42,
        end_time="2026-06-18T10:00:00Z",
    )
    returned = [r["policy_uuid"] for r in result["data"]["runs"]]
    assert returned == ["at-bound"]


@pytest.mark.asyncio
async def test_unparseable_bound_does_not_crash() -> None:
    """An unparseable bound degrades gracefully: the tool returns rather than
    raising, and the unparseable bound is treated as no bound."""
    client = _make_client(get_responses={"/policy-history/policy-runs": [_RUNS_JUNE_18]})
    result = await list_policy_runs_v2(
        cast(AutomoxClient, client),
        org_id=42,
        end_time="not-a-date",
    )
    returned = sorted(r["policy_uuid"] for r in result["data"]["runs"])
    assert returned == ["r-early", "r-late", "r-mid"]


@pytest.mark.asyncio
async def test_unparseable_run_time_not_dropped() -> None:
    """A run whose run_time can't be parsed isn't silently excluded by a
    range filter (graceful degradation, not a crash)."""
    runs = [
        _run("good", "2026-06-18T12:00:00Z"),
        _run("bad", "garbage-timestamp"),
    ]
    client = _make_client(get_responses={"/policy-history/policy-runs": [runs]})
    result = await list_policy_runs_v2(
        cast(AutomoxClient, client),
        org_id=42,
        end_time="2026-06-18",
    )
    returned = sorted(r["policy_uuid"] for r in result["data"]["runs"])
    assert returned == ["bad", "good"]
