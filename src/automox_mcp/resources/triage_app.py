"""Read-only MCP App: a non-compliant **triage** surface for ``get_compliance_snapshot``.

This is the dependency-free MCP Apps pilot (issue #178). ``prefab_ui`` is not
installed, so we use the low-level path:

* a plain ``ui://automox/triage.html`` resource (FastMCP auto-resolves the
  ``text/html;profile=mcp-app`` MIME for ``ui://`` URIs), and
* an ``AppConfig`` attached to ``get_compliance_snapshot`` (see
  ``tools/compound_tools.py``) so Apps-capable hosts render this UI inline.

The HTML is fully self-contained: inline CSS + vanilla JS, **no external
imports**. It embeds the shared ``window.AutomoxApp`` bridge (``_app_bridge``)
— the same hand-rolled ``io.modelcontextprotocol/ui`` (ext-apps) contract used
by the write-flow Apps, so all four UIs stay consistent. Embedding the bridge
inline (rather than importing the ``@modelcontextprotocol/ext-apps`` SDK from a
CDN) keeps the page inside the host's default deny-all CSP — no
``connect``/``resource`` domains are required — which is the right posture for a
security product and works in locked-down/offline hosts. A ``window.openai``
fallback covers the OpenAI Apps SDK, and a standalone branch degrades without
errors when no host bridge is present.

**Read-only:** there are no destructive backend tools here. The only tool the
UI drives through the bridge is the **read** tool ``list_server_groups``, used
to resolve a device's ``server_group_id`` to a human-readable group name (same
name-surfacing treatment as the policy blast-radius App). Non-Apps hosts simply
receive the structured snapshot from ``get_compliance_snapshot`` unchanged
(graceful degradation); this UI is purely additive.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastmcp.apps import UI_MIME_TYPE

from ._app_bridge import MCP_APP_BRIDGE_JS

if TYPE_CHECKING:
    from fastmcp import FastMCP

#: URI of the triage App HTML resource. Imported by ``tools/compound_tools.py``
#: to wire the ``AppConfig`` so the two stay in sync.
TRIAGE_APP_URI = "ui://automox/triage.html"

_TRIAGE_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Automox — Compliance Triage</title>
<style>
  :root {
    --bg: #0e1116; --panel: #171b22; --border: #272d39; --text: #e6e9ef;
    --muted: #9aa4b2; --good: #2ea043; --warn: #d29922; --bad: #f85149;
    --radius: 10px;
  }
  [data-theme="light"] {
    --bg: #f6f8fa; --panel: #fff; --border: #d8dee4; --text: #1f2328;
    --muted: #636c76; --good: #1a7f37; --warn: #9a6700; --bad: #cf222e;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 16px; background: var(--bg); color: var(--text);
    font: 14px/1.5 var(--font-sans, system-ui, -apple-system, "Segoe UI", sans-serif);
  }
  h1 { font-size: 16px; margin: 0 0 2px; }
  .sub { color: var(--muted); font-size: 12px; margin-bottom: 16px; }
  .cards {
    display: grid; gap: 10px; margin-bottom: 18px;
    grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  }
  .card {
    background: var(--panel); border: 1px solid var(--border);
    border-radius: var(--radius); padding: 12px;
  }
  .card .n { font-size: 22px; font-weight: 650; }
  .card .l {
    color: var(--muted); font-size: 11px; text-transform: uppercase;
    letter-spacing: .04em;
  }
  .n.good { color: var(--good); } .n.warn { color: var(--warn); }
  .n.bad { color: var(--bad); }
  section {
    background: var(--panel); border: 1px solid var(--border);
    border-radius: var(--radius); margin-bottom: 14px; overflow: hidden;
  }
  section > h2 {
    font-size: 13px; margin: 0; padding: 10px 12px; display: flex;
    justify-content: space-between; border-bottom: 1px solid var(--border);
  }
  section > h2 .count { color: var(--muted); font-weight: 500; }
  table { width: 100%; border-collapse: collapse; }
  th, td {
    text-align: left; padding: 7px 12px; font-size: 12px;
    border-bottom: 1px solid var(--border);
  }
  th { color: var(--muted); font-weight: 500; }
  tr:last-child td { border-bottom: 0; }
  .pill {
    display: inline-block; padding: 1px 7px; border-radius: 999px;
    font-size: 11px; border: 1px solid var(--border);
  }
  .pill.bad { color: var(--bad); border-color: var(--bad); }
  .pill.warn { color: var(--warn); border-color: var(--warn); }
  .empty { padding: 14px 12px; color: var(--muted); font-size: 12px; }
  .note {
    font-size: 11px; color: var(--muted); padding: 8px 12px;
    border-top: 1px dashed var(--border);
  }
  .chips { display: flex; flex-wrap: wrap; gap: 6px; padding: 10px 12px; }
  .chip {
    background: var(--bg); border: 1px solid var(--border);
    border-radius: 6px; padding: 3px 8px; font-size: 12px;
  }
  code { font-size: 11px; }
  .status { color: var(--bad); font-size: 11px; margin-top: 10px; }
</style>
</head>
<body>
  <h1>Compliance Triage</h1>
  <div class="sub" id="sub">Loading compliance snapshot…</div>
  <div class="cards" id="cards"></div>
  <section id="noncompliant">
    <h2>Non-compliant devices <span class="count"></span></h2>
    <div class="body"></div>
  </section>
  <section id="stale">
    <h2>Stale devices <span class="count"></span></h2>
    <div class="body"></div>
  </section>
  <section id="policies">
    <h2>Policy summary <span class="count"></span></h2>
    <div class="body"></div>
  </section>
  <div class="status" id="status"></div>
<script>__MCP_APP_BRIDGE__</script>
<script>
(function () {
  "use strict";
  var App = window.AutomoxApp;
  var gotData = false;
  var lastEnv = null;
  var groupNames = {};          // server_group id -> name (resolved via list_server_groups)
  var groupNamesLoaded = false;

  var els = {
    sub: document.getElementById("sub"),
    cards: document.getElementById("cards"),
    status: document.getElementById("status"),
    nc: document.querySelector("#noncompliant .body"),
    ncCount: document.querySelector("#noncompliant .count"),
    stale: document.querySelector("#stale .body"),
    staleCount: document.querySelector("#stale .count"),
    policies: document.querySelector("#policies .body"),
    policiesCount: document.querySelector("#policies .count")
  };

  function esc(v) {
    return String(v == null ? "" : v)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }
  function field(obj, keys) {
    for (var i = 0; i < keys.length; i++) {
      var k = keys[i];
      if (obj && obj[k] != null && obj[k] !== "") return obj[k];
    }
    return null;
  }
  function rateClass(rate) {
    if (rate == null) return "";
    if (rate >= 95) return "good";
    if (rate >= 80) return "warn";
    return "bad";
  }
  function card(label, value, cls) {
    var nClass = cls === "rate" ? rateClass(value) : "";
    var suffix = cls === "rate" && value != null ? "%" : "";
    var shown = value == null ? "—" : esc(value) + suffix;
    return '<div class="card"><div class="n ' + nClass + '">' + shown +
      '</div><div class="l">' + esc(label) + "</div></div>";
  }

  // Resolve server-group ids -> names once via the read tool, then re-render so
  // the Group column shows names, not bare ids (same treatment as the policy
  // blast-radius App). Harmless no-op if listing is unavailable or no bridge.
  function groupLabel(id) {
    var nm = groupNames[String(id)];
    return nm ? esc(nm) + " (" + esc(id) + ")" : "group " + esc(id);
  }
  function ensureGroupNames() {
    if (groupNamesLoaded || !App || typeof App.callTool !== "function") return;
    groupNamesLoaded = true;
    App.callTool("list_server_groups", {}).then(function (res) {
      var d = (res && res.structuredContent && res.structuredContent.data) || {};
      var list = d.groups || d.server_groups;
      if (!Array.isArray(list)) {
        for (var k in d) { if (Array.isArray(d[k])) { list = d[k]; break; } }
      }
      (list || []).forEach(function (g) {
        if (g && g.id != null && g.name != null) groupNames[String(g.id)] = g.name;
      });
      if (lastEnv) render(lastEnv);
    }).catch(function () {});
  }

  // A device's display name and group, surfaced against the live snapshot shape:
  // non-compliant rows carry server_name / server_group_id; stale rows carry
  // display_name (and no group). Falls back gracefully across both shapes.
  function deviceName(d) {
    return field(d, ["name", "custom_name", "server_name", "hostname", "display_name"]) ||
      ("device " + (field(d, ["server_id", "device_id", "id"]) || "?"));
  }
  function groupCell(d) {
    var gname = field(d, ["group_name", "group", "server_group"]);
    if (gname != null && typeof gname !== "object") return esc(gname);
    var gid = field(d, ["server_group_id", "group_id", "groupId"]);
    return gid != null ? groupLabel(gid) : "—";
  }

  function deviceRows(devices) {
    return devices.map(function (d) {
      d = d || {};
      var os = field(d, ["os_family", "platform", "os", "os_version"]);
      var flags = [];
      if (d.needs_reboot || d.needsReboot) flags.push('<span class="pill warn">reboot</span>');
      if (d.connected === false) flags.push('<span class="pill bad">offline</span>');
      return "<tr><td>" + esc(deviceName(d)) + "</td><td>" + esc(os || "—") +
        "</td><td>" + groupCell(d) + "</td><td>" +
        (flags.join(" ") || "—") + "</td></tr>";
    }).join("");
  }

  function renderTable(target, countEl, devices, summary, emptyMsg) {
    var list = Array.isArray(devices) ? devices : [];
    countEl.textContent = list.length ? String(list.length) : "";
    if (!list.length) {
      target.innerHTML = '<div class="empty">' + esc(emptyMsg) + "</div>";
      return;
    }
    var html = "<table><thead><tr><th>Device</th><th>OS</th><th>Group</th>" +
      "<th>State</th></tr></thead><tbody>" + deviceRows(list) + "</tbody></table>";
    if (summary && summary.has_more) {
      html += '<div class="note">Showing ' + esc(summary.returned) + " of " +
        esc(summary.total) + ". Call <code>" + esc(summary.follow_up_tool) +
        "</code> for the full list.</div>";
    }
    target.innerHTML = html;
  }

  function renderPolicies(summary) {
    if (!summary) {
      els.policies.innerHTML = '<div class="empty">No policy data.</div>';
      return;
    }
    els.policiesCount.textContent =
      summary.total_policies != null ? String(summary.total_policies) : "";
    var chips = [];
    function addChips(obj) {
      if (!obj) return;
      Object.keys(obj).forEach(function (k) {
        chips.push('<span class="chip">' + esc(k) + ": " + esc(obj[k]) + "</span>");
      });
    }
    addChips(summary.by_type);
    addChips(summary.by_status);
    els.policies.innerHTML = chips.length
      ? '<div class="chips">' + chips.join("") + "</div>"
      : '<div class="empty">No policies.</div>';
  }

  function render(envelope) {
    if (!envelope || typeof envelope !== "object") return;
    gotData = true;
    lastEnv = envelope;
    var data = envelope.data || envelope;        // tolerate {data,metadata} or bare data
    var meta = envelope.metadata || {};
    var ov = data.compliance_overview || {};
    els.sub.textContent = "Fleet compliance posture" +
      (meta.detail_limit != null ? " · detail limit " + meta.detail_limit : "");
    els.cards.innerHTML =
      card("Compliance", ov.compliance_rate_percent, "rate") +
      card("Total devices", ov.total_devices) +
      card("Compliant", ov.compliant_devices) +
      card("Non-compliant", ov.noncompliant_devices);

    var sections = meta.section_summaries || {};
    var nc = data.noncompliant_report || {};
    var ncDevices = Array.isArray(nc.devices) ? nc.devices : [];
    // If any non-compliant device targets a server group, resolve names (async;
    // re-renders when the read returns).
    if (ncDevices.some(function (d) {
      return d && (d.server_group_id != null || d.group_id != null || d.groupId != null);
    })) ensureGroupNames();
    renderTable(els.nc, els.ncCount, nc.devices,
      sections["noncompliant_report.devices"], "No non-compliant devices.");
    var dh = data.device_health || {};
    renderTable(els.stale, els.staleCount, dh.stale_devices,
      sections["device_health.stale_devices"], "No stale devices.");
    renderPolicies(data.policy_summary);

    els.status.textContent =
      meta.errors && meta.errors.length ? "Some sections failed: " + meta.errors.join("; ") : "";
  }

  // The shared bridge applies the host theme to documentElement automatically.
  App.onData(render);
  setTimeout(function () {
    if (!gotData) {
      els.sub.textContent =
        "Open this view from an Automox compliance snapshot to see live triage data.";
    }
  }, 2000);
})();
</script>
</body>
</html>
"""

_TRIAGE_HTML = _TRIAGE_TEMPLATE.replace("__MCP_APP_BRIDGE__", MCP_APP_BRIDGE_JS)


def register(server: FastMCP) -> None:
    """Register the read-only triage App HTML resource (``ui://automox/triage.html``)."""

    @server.resource(
        TRIAGE_APP_URI,
        name="automox_triage_app",
        description=(
            "Read-only MCP App UI for the non-compliant triage surface, rendered "
            "inline by Apps-capable hosts as the interactive view for "
            "get_compliance_snapshot."
        ),
        mime_type=UI_MIME_TYPE,
    )
    def triage_app() -> str:
        return _TRIAGE_HTML


__all__ = ["register", "TRIAGE_APP_URI"]
