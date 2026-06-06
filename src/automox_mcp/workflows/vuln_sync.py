"""Vulnerability Sync / Remediations workflows for Automox MCP."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..client import AutomoxClient
from ..utils.response import extract_list as _extract_list


def _summarize_action_set(item: Mapping[str, Any]) -> dict[str, Any]:
    """Extract key fields from an action set record.

    The Automox `/orgs/{org}/remediations/action-sets` API returns
    `id`, `configuration_id`, `organization_id`, `status`, `source`
    (object with `name`/`type`), `statistics` (nested counts under
    `issues`/`devices`/`solutions`), `created_at`, `updated_at`,
    `error`, plus user attribution fields. Earlier revisions looked
    for top-level `name`, `issue_count`, `action_count`,
    `solution_count` — none of which the API emits — so both list and
    detail endpoints returned only the 5 keys the API does have at top
    level (id/status/source/created_at/updated_at), creating bug #4a
    "no detail enrichment". Note: there is no top-level "action count"
    in the API; the closest analogue is `solution_count` (sum of per-
    solution-type counts) or `vulnerability_count` (sum of
    `vulnerability_count` across solutions).
    """
    entry: dict[str, Any] = {}
    for key in (
        "id",
        "configuration_id",
        "organization_id",
        "status",
        "source",
        "created_at",
        "updated_at",
        "error",
    ):
        val = item.get(key)
        if val is not None:
            entry[key] = val

    # Pull a flat `name` out of the `source` object when possible so
    # callers don't need to navigate the nested shape.
    source = item.get("source")
    if isinstance(source, Mapping):
        source_name = source.get("name")
        if source_name and "name" not in entry:
            entry["name"] = source_name

    # Flatten the per-bucket counts in `statistics` into top-level
    # totals so the summary surfaces them at a glance.
    stats = item.get("statistics")
    if isinstance(stats, Mapping):
        issues = stats.get("issues")
        if isinstance(issues, Mapping):
            issue_count = 0
            for bucket in issues.values():
                if isinstance(bucket, Mapping):
                    bucket_count = bucket.get("count")
                    if isinstance(bucket_count, int):
                        issue_count += bucket_count
            entry["issue_count"] = issue_count

        solutions = stats.get("solutions")
        if isinstance(solutions, Mapping):
            solution_count = 0
            vulnerability_count = 0
            for bucket in solutions.values():
                if isinstance(bucket, Mapping):
                    bucket_count = bucket.get("count")
                    if isinstance(bucket_count, int):
                        solution_count += bucket_count
                    bucket_vulns = bucket.get("vulnerability_count")
                    if isinstance(bucket_vulns, int):
                        vulnerability_count += bucket_vulns
            entry["solution_count"] = solution_count
            entry["vulnerability_count"] = vulnerability_count

        devices = stats.get("devices")
        if isinstance(devices, Mapping):
            matched = devices.get("matched_count")
            if isinstance(matched, int):
                entry["matched_device_count"] = matched

        # Also expose the full statistics block for callers that want
        # the raw nested shape (per-issue-type, per-solution-type counts).
        entry["statistics"] = dict(stats)

    return entry


async def list_remediation_action_sets(
    client: AutomoxClient,
    *,
    org_id: int,
    page: int | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """List vulnerability remediation action sets."""
    params: dict[str, Any] = {}
    if page is not None:
        params["page"] = page
    if limit is not None:
        params["limit"] = limit
    response = await client.get(
        f"/orgs/{org_id}/remediations/action-sets",
        params=params or None,
    )

    items = _extract_list(response)
    summaries = [_summarize_action_set(item) for item in items]

    return {
        "data": {
            "total_action_sets": len(summaries),
            "action_sets": summaries,
        },
        "metadata": {"deprecated_endpoint": False},
    }


async def get_action_set_detail(
    client: AutomoxClient,
    *,
    org_id: int,
    action_set_id: int,
) -> dict[str, Any]:
    """Get details for a specific action set."""
    response = await client.get(
        f"/orgs/{org_id}/remediations/action-sets/{action_set_id}",
    )

    if isinstance(response, Mapping):
        detail = _summarize_action_set(response)
    else:
        detail = {}

    return {
        "data": detail,
        "metadata": {
            "deprecated_endpoint": False,
            "field_notes": {
                "status": (
                    "Action-set processing lifecycle. Observed live on this tenant "
                    "via a full upload-to-completion poll (2026-06-06): the value "
                    "set is {'building','ready'} and the transition order is building "
                    "-> ready (settled in ~2s). 'building' is emitted by the API "
                    "itself in the upload create response (HTTP 201 body, "
                    "statistics=null), NOT merely a wrapper default. 'ready' is the "
                    "confirmed TERMINAL value (stable across 0/15/31/46s polls; "
                    "updated_at advanced 2s past created_at then held). 'active' is "
                    "the spec example value only (ActionSet.status example:'active') "
                    "and was NOT reproduced in this probe. The spec defines no enum, "
                    "so the value set is open and values beyond building/ready (e.g. "
                    "an error state) are possible but unobserved here. As a cross-"
                    "check, non-zero issue_count/solution_count indicate processing "
                    "produced results regardless of the status string."
                ),
            },
        },
    }


async def get_action_set_issues(
    client: AutomoxClient,
    *,
    org_id: int,
    action_set_id: int,
    page: int | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Get vulnerability issues for an action set."""
    params: dict[str, Any] = {}
    if page is not None:
        params["page"] = page
    if limit is not None:
        params["limit"] = limit
    response = await client.get(
        f"/orgs/{org_id}/remediations/action-sets/{action_set_id}/issues",
        params=params or None,
    )

    issues = _extract_list(response)

    return {
        "data": {
            "action_set_id": action_set_id,
            "total_issues": len(issues),
            "issues": issues,
        },
        "metadata": {"deprecated_endpoint": False},
    }


async def get_action_set_solutions(
    client: AutomoxClient,
    *,
    org_id: int,
    action_set_id: int,
    page: int | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Get solutions for an action set."""
    params: dict[str, Any] = {}
    if page is not None:
        params["page"] = page
    if limit is not None:
        params["limit"] = limit
    response = await client.get(
        f"/orgs/{org_id}/remediations/action-sets/{action_set_id}/solutions",
        params=params or None,
    )

    solutions = _extract_list(response)

    return {
        "data": {
            "action_set_id": action_set_id,
            "total_solutions": len(solutions),
            "solutions": solutions,
        },
        "metadata": {
            "deprecated_endpoint": False,
            # Legend only — the raw `solutions` payload is forwarded verbatim
            # (no per-item severity/status mutation). The spec types these
            # fields as bare strings with no enum; vocabulary notes below mark
            # what was/wasn't confirmed against the live tenant. Device status
            # vocabulary was extended by a full gated patch-now execution on a
            # device-bearing test org (2026-06-06, issue #165); the 2026-06-05
            # probe had only observed rapid7-solution entries.
            "field_notes": {
                "vulnerabilities[].severity": (
                    "Per-CVE severity string. The remediation API does NOT enumerate "
                    "this field (spec types it `{type: string}` with example values "
                    "low/medium/high). 'critical' was observed live on this tenant, "
                    "consistent with the lowercase patch-severity scale "
                    "(no_known_cves/none/unknown/low/medium/high/critical, "
                    "ceiling=critical) rather than the capitalized OCSF severity scale "
                    "(Low/High/Critical/Fatal) — but the FULL emitted value set and the "
                    "ceiling were NOT confirmed (the live sample showed only 'critical'), "
                    "so the scale/ceiling remains spec-derived / unverified-live. Treat "
                    "the value as the vendor/source-reported rating; cross-check "
                    "authoritative CVSS for the CVE id before asserting 'this is the "
                    "most/least severe'."
                ),
                "devices[].status": (
                    "Per-device remediation status. Spec types it `{type: string}` "
                    "with the single example 'pending'; no enum. Observed live across "
                    "a full gated patch-now execution (2026-06-06): the value set is "
                    "{'not-started','in_progress'} with transition order not-started "
                    "-> in_progress. 'not-started' is the PRE-execution value (also "
                    "held by sibling devices in the same action set that were not "
                    "targeted — status is per-device and execution-scoped, not "
                    "action-set-wide). 'in_progress' is emitted within seconds of the "
                    "execute call returning HTTP 202. NOTE THE SEPARATOR "
                    "INCONSISTENCY: 'not-started' is hyphenated, 'in_progress' is "
                    "underscored — do not assume a uniform convention. The spec's "
                    "'pending' example was NOT seen live. A TERMINAL value "
                    "(completed/failed/etc.) exists by inference — the device held "
                    "'in_progress' for a full ~24-minute poll while its InstallUpdate "
                    "command sat queued (the agent accepted but had not reported "
                    "back) — but the terminal string was NOT captured and remains "
                    "unconfirmed. The value set is open; confirm any status against "
                    "the device's patch/command-queue history before asserting "
                    "meaning."
                ),
                "solutions[].status": (
                    "A solution-LEVEL status string is defined in the spec for the "
                    "rapid7-solution and solution_type 'unmatched' (schema "
                    "UnmatchedCVE) sub-types (example 'pending'). Confirmed live "
                    "(2026-06-06) NULL/absent on automox-patch solutions across the "
                    "entire lifecycle (pre-execution, immediately post-execution, and "
                    "~24 min of polling); the prior 2026-06-05 probe likewise found "
                    "no solution-level status on rapid7-solution entries. For both "
                    "automox-patch and rapid7-solution sub-types observed on this "
                    "tenant, status lives on devices[] only. Spec-defined / "
                    "not-observed-live: do not rely on a solution-level status being "
                    "present; if one appears, apply the same undocumented free-string "
                    "caveat as devices[].status. ADDITIONAL CONFIRMED PROVENANCE: "
                    "patch-now execution does NOT create a persistent policy object — "
                    "the work dispatches as a direct device command (InstallUpdate, "
                    "policy_id=0 in the command queue), so do not look for a policy "
                    "named after the action set."
                ),
            },
        },
    }


async def get_upload_formats(
    client: AutomoxClient,
    *,
    org_id: int,
) -> dict[str, Any]:
    """Get supported CSV upload formats for action sets."""
    response = await client.get(
        f"/orgs/{org_id}/remediations/action-sets/upload/formats",
    )

    formats = _extract_list(response)

    return {
        "data": {
            "total_formats": len(formats),
            "formats": formats,
        },
        "metadata": {"deprecated_endpoint": False},
    }


async def upload_action_set(
    client: AutomoxClient,
    *,
    org_id: int,
    csv_content: str,
    source: str = "generic",
    filename: str = "action-set.csv",
) -> dict[str, Any]:
    """Upload a CSV-based remediation action set (``multipart/form-data``).

    Wraps ``POST /orgs/{org}/remediations/action-sets/upload``. Per the live
    contract (confirmed 2026-05-31): ``source`` is a **query parameter** (enum
    ``generic|qualys|tenable|crowd-strike|rapid7``) and the multipart body
    carries ``file`` (the CSV) plus ``format`` (the same enum). The action set's
    display name is derived from the uploaded ``filename``. Returns the created
    action set; ``status`` is typically ``building`` (processing is async).

    The previous implementation POSTed JSON and was non-functional — the live
    endpoint requires a real multipart upload (see #106).
    """
    response = await client.post_multipart(
        f"/orgs/{org_id}/remediations/action-sets/upload",
        params={"source": source},
        files={"file": (filename, csv_content.encode("utf-8"), "text/csv")},
        data={"format": source},
    )

    # The endpoint returns the created action set (the live tenant returns a
    # single object; the spec types it as a one-element array — handle both).
    if isinstance(response, list) and response:
        first = response[0]
        result = dict(first) if isinstance(first, Mapping) else {}
    elif isinstance(response, Mapping):
        result = dict(response)
    else:
        result = {}

    return {
        "data": {
            "id": result.get("id"),
            "status": result.get("status", "building"),
            "source": result.get("source"),
            "organization_id": result.get("organization_id"),
            "message": "Action set upload submitted.",
        },
        "metadata": {"deprecated_endpoint": False, "org_id": org_id},
    }


async def delete_action_set(
    client: AutomoxClient,
    *,
    org_id: int,
    action_set_id: int,
) -> dict[str, Any]:
    """Delete a single Vuln Sync action set.

    Wraps ``DELETE /orgs/{org}/remediations/action-sets/{actionSetID}``. This is
    console metadata (not endpoint state) and is reconstructable by re-uploading
    the source CSV, so it is exposed as Tier-1 ask-first (confirmation-only, no
    env gate).
    """
    await client.delete(
        f"/orgs/{org_id}/remediations/action-sets/{action_set_id}",
    )

    return {
        "data": {
            "action_set_id": action_set_id,
            "deleted": True,
        },
        "metadata": {"deprecated_endpoint": False, "org_id": org_id},
    }


async def delete_action_sets_bulk(
    client: AutomoxClient,
    *,
    org_id: int,
    action_set_ids: list[int],
) -> dict[str, Any]:
    """Delete multiple Vuln Sync action sets in one atomic call.

    Wraps the native bulk endpoint ``DELETE /orgs/{org}/remediations/action-sets``
    with a JSON body of ``{"ids": [...]}`` (schema ``delete-action-set``,
    ``console-api.yaml`` ``2026-05-08``); the upstream responds ``204``. Action
    sets are console metadata, reconstructable via re-upload, so this is exposed
    Tier-1 ask-first (confirmation-only, no env gate).
    """
    ids = list(action_set_ids)
    await client.delete(
        f"/orgs/{org_id}/remediations/action-sets",
        json_data={"ids": ids},
    )

    return {
        "data": {
            "requested": len(ids),
            "deleted_count": len(ids),
            "deleted": ids,
        },
        "metadata": {"deprecated_endpoint": False, "org_id": org_id},
    }


async def apply_remediation_actions(
    client: AutomoxClient,
    *,
    org_id: int,
    action_set_id: int,
    actions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Execute remediation actions (patch-now / patch-with-worklet) on devices.

    Wraps ``POST /orgs/{orgID}/remediations/action-sets/{actionSetID}/actions``.
    This immediately patches or runs worklets on the specified devices — the
    upstream endpoint returns ``202 Accepted`` and the work runs asynchronously.
    Maps snake_case inputs (``solution_id``/``worklet_id``) to the API's
    camelCase body.
    """
    api_actions: list[dict[str, Any]] = []
    for action in actions:
        item: dict[str, Any] = {
            "action": action["action"],
            "solutionId": action["solution_id"],
            "devices": action["devices"],
        }
        if action.get("worklet_id") is not None:
            item["workletId"] = action["worklet_id"]
        api_actions.append(item)

    response = await client.post(
        f"/orgs/{org_id}/remediations/action-sets/{action_set_id}/actions",
        json_data={"actions": api_actions},
    )

    total_devices = sum(len(action.get("devices") or []) for action in actions)

    return {
        "data": {
            "action_set_id": action_set_id,
            "actions_submitted": len(api_actions),
            "total_device_targets": total_devices,
            "status": "accepted",
            "response": response if isinstance(response, Mapping) else None,
        },
        "metadata": {"deprecated_endpoint": False, "org_id": org_id},
    }
