"""Write-flow MCP App: remediation-apply review — the gated operation (issue #181).

Remediation-apply is the most consequential operation the server exposes, so it
gets the most design care. It attaches to the **read** tool
``get_action_set_solutions`` (which surfaces, per solution, the vulnerabilities
and the affected devices with their status — exactly "what will be applied,
where"). The review UI **is** the mitigation the gating policy asks for: the
operator sees the full apply payload before confirming.

Each solution offers a single **patch-now** apply that builds
``{action_set_id, actions: [{action: "patch-now", solution_id, devices: [...]}]}``
and calls the existing, env-gated ``apply_remediation_actions`` through the host
``CallTool`` bridge. ``patch-with-worklet`` (arbitrary model-authored code — the
opaque/arbitrary trigger the env gate exists for) is **deliberately not offered
in the UI**; that path stays a direct, explicitly-constructed tool call.

Safety: no new tool, no new gate. ``apply_remediation_actions`` keeps its Tier-2
gate — it is registered only when ``AUTOMOX_MCP_ALLOW_APPLY_REMEDIATION_ACTIONS``
is set (and write mode is on). When the gate is off the tool is absent, the
bridge call fails, and the UI shows that the apply is disabled (graceful
degradation; the review remains fully usable).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastmcp.apps import UI_MIME_TYPE

from ._app_bridge import MCP_APP_BRIDGE_JS

if TYPE_CHECKING:
    from fastmcp import FastMCP

#: URI of the remediation-apply review App. Imported by ``tools/vuln_sync_tools.py``.
REMEDIATION_APPLY_APP_URI = "ui://automox/remediation-apply.html"

_HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Automox — Remediation Apply Review</title>
<style>
  :root {
    --bg: #0e1116; --panel: #171b22; --border: #272d39; --text: #e6e9ef;
    --muted: #9aa4b2; --good: #2ea043; --bad: #f85149; --warn: #d29922;
    --accent: #4c8dff; --radius: 10px;
  }
  [data-theme="light"] {
    --bg: #f6f8fa; --panel: #fff; --border: #d8dee4; --text: #1f2328;
    --muted: #636c76; --good: #1a7f37; --bad: #cf222e; --warn: #9a6700;
    --accent: #0969da;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 16px; background: var(--bg); color: var(--text);
    font: 14px/1.5 var(--font-sans, system-ui, -apple-system, "Segoe UI", sans-serif);
  }
  h1 { font-size: 16px; margin: 0 0 2px; }
  .sub { color: var(--muted); font-size: 12px; margin-bottom: 12px; }
  .banner {
    border: 1px solid var(--warn); color: var(--warn); border-radius: var(--radius);
    padding: 9px 12px; font-size: 12px; margin-bottom: 14px;
  }
  .sol {
    background: var(--panel); border: 1px solid var(--border);
    border-radius: var(--radius); padding: 12px; margin-bottom: 10px;
  }
  .sol .head { display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; }
  .tag {
    font-size: 10px; text-transform: uppercase; letter-spacing: .04em;
    border: 1px solid var(--accent); color: var(--accent); border-radius: 999px;
    padding: 1px 7px;
  }
  .sev { font-size: 10px; border-radius: 999px; padding: 1px 7px; border: 1px solid var(--border); }
  .sev.critical, .sev.high { color: var(--bad); border-color: var(--bad); }
  .summary { font-size: 12px; margin-top: 4px; }
  .scope { font-size: 12px; color: var(--muted); margin-top: 6px; }
  .scope b { color: var(--text); }
  .cves { font-size: 11px; color: var(--muted); margin-top: 4px; word-break: break-word; }
  .btn {
    border: 1px solid var(--border); border-radius: 6px; padding: 5px 10px;
    font-size: 12px; cursor: pointer; background: var(--panel); color: var(--text);
    margin-top: 8px;
  }
  .btn.apply { border-color: var(--bad); color: var(--bad); }
  .btn:disabled { opacity: .5; cursor: default; }
  .rowstatus { font-size: 11px; color: var(--muted); margin-top: 6px; }
  .rowstatus.err { color: var(--bad); }
  .empty { padding: 16px 12px; color: var(--muted); }
</style>
</head>
<body>
  <h1>Remediation Apply Review</h1>
  <div class="sub" id="sub">Loading remediation solutions…</div>
  <div class="banner">
    ⚠ Applying runs <b>patch-now</b> on the listed devices immediately (async). Review the
    affected devices below before confirming. This operation is gated and must be explicitly
    enabled on the server (<code>AUTOMOX_MCP_ALLOW_APPLY_REMEDIATION_ACTIONS</code>).
  </div>
  <div id="list"></div>
<script>__MCP_APP_BRIDGE__</script>
<script>
(function () {
  "use strict";
  var App = window.AutomoxApp;
  var els = { sub: document.getElementById("sub"), list: document.getElementById("list") };
  var gotData = false;
  var actionSetId = null;

  function esc(v) {
    return String(v == null ? "" : v)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }
  function solutionId(s) {
    if (s.id != null) return s.id;                       // top-level int id (the apply id)
    if (s.solution_id != null) return s.solution_id;
    return s.solution_details && s.solution_details.solution_id;
  }
  function solutionTitle(s) {
    var d = s.solution_details;
    if (d && typeof d === "object" && d.solution_summary) return d.solution_summary;
    if (typeof d === "string") return d;
    return s.solution_type || ("solution " + solutionId(s));
  }
  function deviceIds(s) {
    var devs = Array.isArray(s.devices) ? s.devices : [];
    var ids = [];
    for (var i = 0; i < devs.length; i++) {
      var d = devs[i] || {};
      var id = d.id != null ? d.id : (d.device_id != null ? d.device_id : d.server_id);
      if (id != null) ids.push(id);
    }
    return ids;
  }
  function maxSeverity(s) {
    var order = { critical: 4, high: 3, medium: 2, low: 1 };
    var best = null, bestRank = 0;
    var vulns = Array.isArray(s.vulnerabilities) ? s.vulnerabilities : [];
    for (var i = 0; i < vulns.length; i++) {
      var sev = (vulns[i] && vulns[i].severity) || "";
      var rank = order[String(sev).toLowerCase()] || 0;
      if (rank > bestRank) { bestRank = rank; best = sev; }
    }
    return best;
  }

  function solCard(s) {
    var sid = solutionId(s);
    var devs = deviceIds(s);
    var vulns = Array.isArray(s.vulnerabilities) ? s.vulnerabilities : [];
    var sev = maxSeverity(s);
    var card = document.createElement("div");
    card.className = "sol";
    var cveList = vulns.map(function (v) {
      return esc((v && v.id) || "") + (v && v.severity ? " (" + esc(v.severity) + ")" : "");
    }).filter(Boolean).join(", ");
    card.innerHTML =
      '<div class="head"><span class="tag">' + esc(s.remediation_type || "patch") + "</span>" +
        (sev
          ? '<span class="sev ' + esc(String(sev).toLowerCase()) + '">' + esc(sev) + "</span>"
          : "") +
        "</div>" +
      '<div class="summary">' + esc(solutionTitle(s)) + "</div>" +
      '<div class="scope">Targets <b>' + devs.length + "</b> device(s) · " +
        vulns.length + " vulnerability(ies)</div>" +
      (cveList ? '<div class="cves">' + cveList + "</div>" : "") +
      '<div class="rowstatus"></div>';
    var statusEl = card.querySelector(".rowstatus");
    var btn = document.createElement("button");
    btn.className = "btn apply";
    btn.textContent = "Apply patch-now to " + devs.length + " device(s)";
    if (sid == null || !devs.length) {
      btn.disabled = true;
      statusEl.textContent =
        sid == null ? "No solution id — cannot apply." : "No devices to target.";
    }
    btn.addEventListener("click", function () {
      btn.disabled = true;
      statusEl.className = "rowstatus";
      statusEl.textContent = "Applying…";
      App.callTool("apply_remediation_actions", {
        action_set_id: actionSetId,
        actions: [{ action: "patch-now", solution_id: sid, devices: devs }],
        request_id: App.requestId()
      }).then(function () {
        statusEl.textContent = "Applied (async, 202) ✓";
      }).catch(function (err) {
        btn.disabled = false;
        statusEl.className = "rowstatus err";
        statusEl.textContent = "Failed: " + ((err && err.message) || "error") +
          " — apply may be disabled (AUTOMOX_MCP_ALLOW_APPLY_REMEDIATION_ACTIONS).";
      });
    });
    card.insertBefore(btn, statusEl);
    return card;
  }

  function render(env) {
    if (!env || typeof env !== "object") return;
    gotData = true;
    var data = env.data || env;
    actionSetId = data.action_set_id;
    var solutions = Array.isArray(data.solutions) ? data.solutions : [];
    els.sub.textContent = (data.total_solutions != null ? data.total_solutions : solutions.length) +
      " solution(s) for action set " + esc(actionSetId);
    els.list.innerHTML = "";
    if (!solutions.length) {
      els.list.innerHTML = '<div class="empty">No remediation solutions in this action set.</div>';
      return;
    }
    for (var i = 0; i < solutions.length; i++) els.list.appendChild(solCard(solutions[i]));
  }

  App.onData(render);
  setTimeout(function () {
    if (!gotData) {
      els.sub.textContent =
        "Run get_action_set_solutions to review an action set's remediations and apply them here.";
    }
  }, 2000);
})();
</script>
</body>
</html>
"""

_REMEDIATION_APPLY_HTML = _HTML_TEMPLATE.replace("__MCP_APP_BRIDGE__", MCP_APP_BRIDGE_JS)


def register(server: FastMCP) -> None:
    """Register the remediation-apply review App HTML resource."""

    @server.resource(
        REMEDIATION_APPLY_APP_URI,
        name="automox_remediation_apply_app",
        description=(
            "MCP App UI for reviewing an action set's remediation solutions and the "
            "devices they target before applying patch-now — the review/confirmation "
            "surface for the gated apply_remediation_actions."
        ),
        mime_type=UI_MIME_TYPE,
    )
    def remediation_apply_app() -> str:
        return _REMEDIATION_APPLY_HTML


__all__ = ["register", "REMEDIATION_APPLY_APP_URI"]
