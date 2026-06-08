"""Write-flow MCP App: policy change + blast-radius review (issue #180).

Attaches to the existing ``apply_policy_changes`` write tool, which has a
``preview`` flag. The intended flow: the model calls
``apply_policy_changes(operations, preview=true)``; an Apps-capable host renders
this review UI inline, showing each proposed operation (create/update) and its
**targeting scope** (server groups + device filters) — the affected-device scope
of the change. The operator can optionally resolve the concrete affected device
set on demand (the UI calls the read tool ``preview_policy_device_filters`` via
the host bridge), then **Apply**, which re-invokes ``apply_policy_changes`` with
``preview=false`` using the original operations captured from the tool input.

Safety: no new write tool, no new gate. ``apply_policy_changes`` is a Tier-1
*ask-first* destructive tool registered only in write mode; the host confirmation
dialog remains the gate when the UI issues the apply (see ``docs/api-coverage.md``).
Non-Apps hosts use ``apply_policy_changes`` directly (graceful degradation).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastmcp.apps import UI_MIME_TYPE

from ._app_bridge import MCP_APP_BRIDGE_JS

if TYPE_CHECKING:
    from fastmcp import FastMCP

#: URI of the policy blast-radius review App. Imported by ``tools/policy_tools.py``.
POLICY_BLAST_RADIUS_APP_URI = "ui://automox/policy-blast-radius.html"

_HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Automox — Policy Change Review</title>
<style>
  :root {
    --bg: #0e1116; --panel: #171b22; --border: #272d39; --text: #e6e9ef;
    --muted: #9aa4b2; --good: #2ea043; --bad: #f85149; --accent: #4c8dff;
    --warn: #d29922; --radius: 10px;
  }
  [data-theme="light"] {
    --bg: #f6f8fa; --panel: #fff; --border: #d8dee4; --text: #1f2328;
    --muted: #636c76; --good: #1a7f37; --bad: #cf222e; --accent: #0969da;
    --warn: #9a6700;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 16px; background: var(--bg); color: var(--text);
    font: 14px/1.5 var(--font-sans, system-ui, -apple-system, "Segoe UI", sans-serif);
  }
  h1 { font-size: 16px; margin: 0 0 2px; }
  .sub { color: var(--muted); font-size: 12px; margin-bottom: 14px; }
  .op {
    background: var(--panel); border: 1px solid var(--border);
    border-radius: var(--radius); padding: 12px; margin-bottom: 10px;
  }
  .op .head { display: flex; gap: 8px; align-items: baseline; }
  .tag {
    font-size: 10px; text-transform: uppercase; letter-spacing: .04em;
    border: 1px solid var(--accent); color: var(--accent); border-radius: 999px;
    padding: 1px 7px;
  }
  .op .name { font-weight: 600; }
  .op .type { color: var(--muted); font-size: 12px; }
  .scope { font-size: 12px; color: var(--muted); margin-top: 6px; }
  .scope b { color: var(--text); font-weight: 600; }
  .warn { color: var(--warn); font-size: 12px; margin-top: 6px; }
  .devbtn, .btn {
    border: 1px solid var(--border); border-radius: 6px; padding: 5px 10px;
    font-size: 12px; cursor: pointer; background: var(--panel); color: var(--text);
  }
  .devbtn { margin-top: 8px; }
  .devices { font-size: 12px; color: var(--muted); margin-top: 6px; }
  details.scope > summary { cursor: pointer; }
  details.scope > summary::marker { color: var(--muted); }
  .devlist { margin: 6px 0 0 4px; padding-left: 10px; border-left: 2px solid var(--border); }
  .devrow { font-size: 12px; color: var(--text); padding: 1px 0; }
  .devrow .dim { color: var(--muted); }
  .bar {
    position: sticky; bottom: 0; display: flex; gap: 8px; align-items: center;
    padding: 10px 0; background: var(--bg); border-top: 1px solid var(--border);
  }
  .btn.apply { border-color: var(--good); color: var(--good); }
  .btn:disabled { opacity: .5; cursor: default; }
  .empty { padding: 16px 12px; color: var(--muted); }
  .barstatus { font-size: 12px; color: var(--muted); }
  .barstatus.err { color: var(--bad); }
</style>
</head>
<body>
  <h1>Policy Change Review</h1>
  <div class="sub" id="sub">Loading proposed policy changes…</div>
  <div id="ops"></div>
  <div class="bar" id="bar" style="display:none">
    <button class="btn apply" id="apply">Apply changes</button>
    <span class="barstatus" id="barstatus"></span>
  </div>
<script>__MCP_APP_BRIDGE__</script>
<script>
(function () {
  "use strict";
  var App = window.AutomoxApp;
  var els = {
    sub: document.getElementById("sub"),
    ops: document.getElementById("ops"),
    bar: document.getElementById("bar"),
    apply: document.getElementById("apply"),
    barstatus: document.getElementById("barstatus")
  };
  var gotData = false;
  var inputArgs = null;   // the {operations, preview} the entry tool was called with
  var lastEnv = null;
  var groupNames = {};         // server_group id -> name (resolved via list_server_groups)
  var groupNamesLoaded = false;

  function esc(v) {
    return String(v == null ? "" : v)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  // Resolve server-group ids -> names once via the read tool, then re-render so
  // the scope shows names, not bare ids. Harmless no-op if listing is unavailable.
  function groupLabel(id) {
    var nm = groupNames[String(id)];
    return nm ? esc(nm) + " (" + esc(id) + ")" : "group " + esc(id);
  }
  function ensureGroupNames() {
    if (groupNamesLoaded) return;
    groupNamesLoaded = true;
    App.callTool("list_server_groups", {}).then(function (res) {
      var d = (res && res.structuredContent && res.structuredContent.data) || {};
      var list = d.server_groups || d.groups;
      if (!Array.isArray(list)) {
        for (var k in d) { if (Array.isArray(d[k])) { list = d[k]; break; } }
      }
      (list || []).forEach(function (g) {
        if (g && g.id != null && g.name != null) groupNames[String(g.id)] = g.name;
      });
      if (lastEnv) render(lastEnv);
    }).catch(function () {});
  }

  // Render a resolved device set as a list of names (custom_name/name) + OS.
  function deviceRows(devs) {
    if (!devs.length) return '<div class="devrow dim">No devices.</div>';
    return devs.map(function (d) {
      d = d || {};
      var nm = d.custom_name || d.name || d.hostname || ("device " + (d.id != null ? d.id : "?"));
      var os = [d.os_family, d.os_version].filter(Boolean).join(" ");
      return '<div class="devrow">' + esc(nm) +
        (os ? ' <span class="dim">— ' + esc(os) + "</span>" : "") + "</div>";
    }).join("");
  }

  function targeting(body) {
    body = body || {};
    var cfg = body.configuration || {};
    var groups = body.server_groups || cfg.server_groups;
    var filters = body.device_filters || cfg.device_filters;
    return {
      groups: Array.isArray(groups) ? groups : null,
      filters: Array.isArray(filters) ? filters : null
    };
  }

  function opCard(op) {
    var body = (op.request && op.request.body) || {};
    var t = targeting(body);
    var action = (op.action || "").toLowerCase() === "update" ? "Update" : "Create";
    var card = document.createElement("div");
    card.className = "op";
    var scopeBits = [];
    if (t.groups) {
      scopeBits.push("<b>" + t.groups.length + "</b> server group(s): " +
        t.groups.map(groupLabel).join(", "));
    }
    if (t.filters) scopeBits.push("<b>" + t.filters.length + "</b> device filter(s)");
    if (!scopeBits.length) scopeBits.push("targeting unchanged / not specified");
    var nameText = esc(op.policy_name || ("policy " + (op.policy_id || "")));
    card.innerHTML =
      '<div class="head"><span class="tag">' + action + "</span>" +
        '<span class="name">' + nameText + "</span>" +
        '<span class="type">' + esc(op.policy_type_name || "") + "</span></div>" +
      '<div class="scope">Affected scope: ' + scopeBits.join(" · ") + "</div>" +
      (Array.isArray(op.warnings) && op.warnings.length
        ? '<div class="warn">⚠ ' + esc(op.warnings.join("; ")) + "</div>" : "") +
      '<div class="devices"></div>';
    var devBox = card.querySelector(".devices");
    // On-demand: resolve the concrete affected device set (needs server_groups).
    if (t.groups && t.groups.length) {
      var btn = document.createElement("button");
      btn.className = "devbtn";
      btn.textContent = "Resolve affected devices";
      btn.addEventListener("click", function () {
        btn.disabled = true; devBox.textContent = "Resolving…";
        App.callTool("preview_policy_device_filters", {
          device_filters: t.filters || undefined, server_groups: t.groups
        }).then(function (res) {
          var d = (res && res.structuredContent && res.structuredContent.data) || {};
          var devs = Array.isArray(d.devices) ? d.devices : [];
          var n = d.total_devices != null ? d.total_devices : devs.length;
          devBox.innerHTML = '<details class="scope" open><summary><b>' + esc(n) +
            "</b> device(s) would be targeted</summary>" +
            '<div class="devlist">' + deviceRows(devs) + "</div></details>";
        }).catch(function (e) {
          devBox.textContent = "Could not resolve devices: " + ((e && e.message) || "error");
          btn.disabled = false;
        });
      });
      card.appendChild(btn);
    }
    return card;
  }

  function render(env) {
    if (!env || typeof env !== "object") return;
    gotData = true;
    lastEnv = env;
    var data = env.data || env;
    var ops = Array.isArray(data.operations) ? data.operations : [];
    var isPreview = data.preview !== false;
    // Resolve server-group names if any operation targets groups (async; re-renders).
    var anyGroups = ops.some(function (op) {
      var t = targeting((op.request && op.request.body) || {});
      return t.groups && t.groups.length;
    });
    if (anyGroups) ensureGroupNames();
    els.sub.textContent = ops.length + " proposed change(s)" +
      (isPreview ? " · preview" : " · already applied");
    els.ops.innerHTML = "";
    if (!ops.length) {
      els.ops.innerHTML = '<div class="empty">No proposed policy changes.</div>';
      els.bar.style.display = "none";
      return;
    }
    for (var i = 0; i < ops.length; i++) els.ops.appendChild(opCard(ops[i]));
    // Only offer Apply on a preview, and only if we captured the original operations.
    if (isPreview) {
      els.bar.style.display = "flex";
      if (!(inputArgs && Array.isArray(inputArgs.operations))) {
        els.apply.disabled = true;
        els.barstatus.textContent = "Apply unavailable — confirm the change from chat.";
      }
    } else {
      els.bar.style.display = "none";
    }
  }

  els.apply.addEventListener("click", function () {
    if (!(inputArgs && Array.isArray(inputArgs.operations))) return;
    els.apply.disabled = true;
    els.barstatus.className = "barstatus";
    els.barstatus.textContent = "Applying…";
    App.callTool("apply_policy_changes", {
      operations: inputArgs.operations, preview: false, request_id: App.requestId()
    }).then(function () {
      els.barstatus.textContent = "Applied ✓";
    }).catch(function (e) {
      els.apply.disabled = false;
      els.barstatus.className = "barstatus err";
      els.barstatus.textContent = "Failed: " + ((e && e.message) || "error");
    });
  });

  App.onInput(function (args) { inputArgs = args || null; });
  App.onData(render);
  setTimeout(function () {
    if (!gotData) {
      els.sub.textContent =
        "Run apply_policy_changes with preview=true to review a change and its blast radius here.";
    }
  }, 2000);
})();
</script>
</body>
</html>
"""

_POLICY_BLAST_RADIUS_HTML = _HTML_TEMPLATE.replace("__MCP_APP_BRIDGE__", MCP_APP_BRIDGE_JS)


def register(server: FastMCP) -> None:
    """Register the policy blast-radius review App HTML resource."""

    @server.resource(
        POLICY_BLAST_RADIUS_APP_URI,
        name="automox_policy_blast_radius_app",
        description=(
            "MCP App UI for reviewing a proposed policy change and its affected-device "
            "scope (blast radius) before applying — the review surface for "
            "apply_policy_changes (preview mode)."
        ),
        mime_type=UI_MIME_TYPE,
    )
    def policy_blast_radius_app() -> str:
        return _POLICY_BLAST_RADIUS_HTML


__all__ = ["register", "POLICY_BLAST_RADIUS_APP_URI"]
