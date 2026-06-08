"""Write-flow MCP App: patch-approval review surface (issue #179).

The flagship interactive flow. Attaches to the existing **read** tool
``patch_approvals_summary`` (which lists approvals awaiting a decision) via an
``AppConfig``; Apps-capable hosts render this review UI inline, fed by that
tool's structured output. The operator reviews each pending approval (software,
CVEs, policy) and clicks Approve/Reject, which calls the existing **write** tool
``decide_patch_approval`` through the host ``CallTool`` bridge.

Safety: no new write tool and no new gate. ``decide_patch_approval`` is a
Tier-1 *ask-first* destructive tool (``destructiveHint: true``, registered only
when write mode is enabled) — the host surfaces its confirmation dialog when the
UI issues the call, so the interactive review UI is the *context* and the host
confirmation remains the gate (see ``docs/api-coverage.md``). Non-Apps hosts
ignore the App link and use ``patch_approvals_summary`` / ``decide_patch_approval``
as plain tools (graceful degradation).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastmcp.apps import UI_MIME_TYPE

from ._app_bridge import MCP_APP_BRIDGE_JS

if TYPE_CHECKING:
    from fastmcp import FastMCP

#: URI of the patch-approval review App. Imported by ``tools/policy_tools.py`` to
#: wire the ``AppConfig`` on ``patch_approvals_summary``.
PATCH_APPROVAL_APP_URI = "ui://automox/patch-approval.html"

_HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Automox — Patch Approval Review</title>
<style>
  :root {
    --bg: #0e1116; --panel: #171b22; --border: #272d39; --text: #e6e9ef;
    --muted: #9aa4b2; --good: #2ea043; --bad: #f85149; --accent: #4c8dff;
    --radius: 10px;
  }
  [data-theme="light"] {
    --bg: #f6f8fa; --panel: #fff; --border: #d8dee4; --text: #1f2328;
    --muted: #636c76; --good: #1a7f37; --bad: #cf222e; --accent: #0969da;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 16px; background: var(--bg); color: var(--text);
    font: 14px/1.5 var(--font-sans, system-ui, -apple-system, "Segoe UI", sans-serif);
  }
  h1 { font-size: 16px; margin: 0 0 2px; }
  .sub { color: var(--muted); font-size: 12px; margin-bottom: 16px; }
  .row {
    display: flex; gap: 12px; align-items: flex-start; padding: 12px;
    background: var(--panel); border: 1px solid var(--border);
    border-radius: var(--radius); margin-bottom: 10px;
  }
  .row.done { opacity: .6; }
  .row.done.approve { border-color: var(--good); }
  .row.done.reject { border-color: var(--bad); }
  .info { flex: 1 1 auto; min-width: 0; }
  .title { font-weight: 600; }
  .meta { color: var(--muted); font-size: 12px; }
  .meta .policy { color: var(--text); }
  .cves { font-size: 11px; color: var(--muted); margin-top: 2px; word-break: break-word; }
  .actions { display: flex; flex-direction: column; gap: 6px; flex: 0 0 auto; width: 180px; }
  .notes {
    background: var(--bg); color: var(--text); border: 1px solid var(--border);
    border-radius: 6px; padding: 5px 8px; font-size: 12px; width: 100%;
  }
  .btn {
    border: 1px solid var(--border); border-radius: 6px; padding: 5px 8px;
    font-size: 12px; cursor: pointer; background: var(--panel); color: var(--text);
  }
  .btn:disabled { opacity: .5; cursor: default; }
  .btn.approve { border-color: var(--good); color: var(--good); }
  .btn.reject { border-color: var(--bad); color: var(--bad); }
  .rowstatus {
    flex: 0 0 auto; width: 90px; font-size: 11px; color: var(--muted); text-align: right;
  }
  .empty { padding: 16px 12px; color: var(--muted); }
  .status { color: var(--bad); font-size: 11px; margin-top: 10px; }
</style>
</head>
<body>
  <h1>Patch Approval Review</h1>
  <div class="sub" id="sub">Loading pending approvals…</div>
  <div id="list"></div>
  <div class="status" id="status"></div>
<script>__MCP_APP_BRIDGE__</script>
<script>
(function () {
  "use strict";
  var App = window.AutomoxApp;
  var els = {
    sub: document.getElementById("sub"),
    list: document.getElementById("list"),
    status: document.getElementById("status")
  };
  var gotData = false;

  function esc(v) {
    return String(v == null ? "" : v)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function approvalRow(a) {
    var id = a.approval_id;
    var sw = a.software || {};
    var swText = [sw.version, sw.os_family].filter(Boolean).join(" · ");
    var cves = Array.isArray(a.cves) ? a.cves.join(", ") : "";
    if (a.cves_truncated) cves += " (+" + a.cves_truncated + " more)";
    var policy = a.policy ? (a.policy.name || ("policy " + a.policy.id)) : "—";
    var row = document.createElement("div");
    row.className = "row";
    row.innerHTML =
      '<div class="info">' +
        '<div class="title">' + esc(a.title || ("approval " + id)) + "</div>" +
        '<div class="meta">' + esc(swText || "—") +
          ' · <span class="policy">' + esc(policy) + "</span></div>" +
        (cves ? '<div class="cves">' + esc(cves) + "</div>" : "") +
      "</div>" +
      '<div class="actions">' +
        '<input class="notes" type="text" placeholder="notes (optional)" />' +
        '<button class="btn approve">Approve</button>' +
        '<button class="btn reject">Reject</button>' +
      "</div>" +
      '<div class="rowstatus"></div>';
    var notesEl = row.querySelector(".notes");
    var statusEl = row.querySelector(".rowstatus");
    var btns = row.querySelectorAll("button");
    function decide(decision) {
      for (var i = 0; i < btns.length; i++) btns[i].disabled = true;
      statusEl.textContent = "Submitting…";
      App.callTool("decide_patch_approval", {
        approval_id: id,
        decision: decision,
        notes: notesEl.value || null,
        request_id: App.requestId()
      }).then(function () {
        row.className = "row done " + decision;
        statusEl.textContent = decision === "approve" ? "Approved" : "Rejected";
      }).catch(function (err) {
        for (var i = 0; i < btns.length; i++) btns[i].disabled = false;
        statusEl.textContent = "Failed: " + ((err && err.message) || "error");
      });
    }
    row.querySelector(".approve").addEventListener("click", function () { decide("approve"); });
    row.querySelector(".reject").addEventListener("click", function () { decide("reject"); });
    return row;
  }

  function render(env) {
    if (!env || typeof env !== "object") return;
    gotData = true;
    var data = env.data || env;
    var approvals = Array.isArray(data.approvals) ? data.approvals : [];
    // Awaiting a decision == manual_approval is null (the decision axis).
    var pending = approvals.filter(function (a) { return a && a.manual_approval == null; });
    var decided = approvals.length - pending.length;
    els.sub.textContent = pending.length + " awaiting decision" +
      (decided ? " · " + decided + " already decided" : "") +
      (data.total_approvals_considered != null
        ? " · " + data.total_approvals_considered + " considered"
        : "");
    els.list.innerHTML = "";
    if (!pending.length) {
      els.list.innerHTML = '<div class="empty">No approvals awaiting a decision.</div>';
      return;
    }
    for (var i = 0; i < pending.length; i++) els.list.appendChild(approvalRow(pending[i]));
  }

  App.onData(render);
  setTimeout(function () {
    if (!gotData) {
      els.sub.textContent =
        "Open this from the Automox patch-approvals summary to review and approve patches.";
    }
  }, 2000);
})();
</script>
</body>
</html>
"""

_PATCH_APPROVAL_HTML = _HTML_TEMPLATE.replace("__MCP_APP_BRIDGE__", MCP_APP_BRIDGE_JS)


def register(server: FastMCP) -> None:
    """Register the patch-approval review App HTML resource."""

    @server.resource(
        PATCH_APPROVAL_APP_URI,
        name="automox_patch_approval_app",
        description=(
            "MCP App UI for reviewing and approving/rejecting pending Automox patch "
            "approvals inline, the review surface for patch_approvals_summary."
        ),
        mime_type=UI_MIME_TYPE,
    )
    def patch_approval_app() -> str:
        return _PATCH_APPROVAL_HTML


__all__ = ["register", "PATCH_APPROVAL_APP_URI"]
