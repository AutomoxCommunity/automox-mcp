#!/usr/bin/env python3
"""One-shot probe for issue #68 — what does summary["total"] mean on
/reports/needs-attention?

Question: in get_noncompliant_report (workflows/reports.py:266-270), the loop
terminates when `len(device_list) >= summary["total"]`. The prepatch sibling
explicitly warns that summary["total"] is a *patch* count, not a device count.
If the same is true for needs-attention, the noncompliant report's loop
terminates early/late and may return the wrong device set.

This probe:
  1. Calls /reports/needs-attention with a small limit to force pagination.
  2. Iterates pages until empty, recording the summary on page 0 and the
     cumulative device count.
  3. Compares summary.total to the final device count.

Outputs a single verdict line:
  - DEVICE_COUNT: summary.total matches the total device count → current
    early-break is safe, just needs a comment.
  - NOT_DEVICE_COUNT: summary.total differs from device count → current
    early-break drops devices; remove it and rely on empty-page termination.
  - AMBIGUOUS: indeterminate (single page, missing field, etc.)

Run:
    set -a && . ~/automox/.env && set +a && \
        uv run python tests/probe_issue_68.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

from automox_mcp.client import AutomoxClient


async def main() -> int:
    if not os.environ.get("AUTOMOX_API_KEY") or not os.environ.get("AUTOMOX_ACCOUNT_UUID"):
        print("ERROR: AUTOMOX_API_KEY and AUTOMOX_ACCOUNT_UUID must be set", file=sys.stderr)
        return 2

    client = AutomoxClient()
    page_size = 10  # small to force pagination on most tenants
    offset = 0
    page_idx = 0
    all_devices: list[dict] = []
    first_summary: dict = {}

    print("Probing /reports/needs-attention...")
    print(f"  page_size={page_size}")
    print()

    while page_idx < 30:  # safety cap
        params = {"limit": page_size, "offset": offset}
        report = await client.get("/reports/needs-attention", params=params)

        # Extract devices + summary in the same way the workflow does
        if isinstance(report, dict):
            block = report.get("nonCompliant", report)
            devices = block.get("devices", []) if isinstance(block, dict) else []
            summary = (
                {k: v for k, v in block.items() if k != "devices"}
                if isinstance(block, dict)
                else {}
            )
        elif isinstance(report, list):
            # Array shape — no summary at all
            devices = report
            summary = {}
        else:
            devices = []
            summary = {}

        if page_idx == 0:
            first_summary = summary
            print(f"page 0 summary keys: {list(summary.keys())}")
            if summary:
                print(f"page 0 summary:\n{json.dumps(summary, indent=2, default=str)}")
            print()

        print(f"page {page_idx}: offset={offset}, len(devices)={len(devices)}")
        all_devices.extend(devices)
        if len(devices) < page_size:
            break
        offset += page_size
        page_idx += 1

    print()
    print(f"Total devices accumulated: {len(all_devices)}")
    summary_total = first_summary.get("total")
    print(f"summary['total'] from page 0: {summary_total!r}")

    # Other counts the API might surface
    for k in ("total", "totalDevices", "deviceCount", "count", "pageCount"):
        if k in first_summary:
            print(f"  summary[{k!r}]: {first_summary[k]!r}")

    print()
    if summary_total is None:
        print("VERDICT: AMBIGUOUS — summary.total not present on this tenant.")
        return 1
    if summary_total == len(all_devices):
        print(
            f"VERDICT: DEVICE_COUNT — summary.total ({summary_total}) "
            f"equals device count ({len(all_devices)}). "
            "Current early-break is safe; add a clarifying comment."
        )
        return 0
    print(
        f"VERDICT: NOT_DEVICE_COUNT — summary.total ({summary_total}) "
        f"!= device count ({len(all_devices)}). "
        "Current early-break may drop devices; remove it and rely on empty-page termination."
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
