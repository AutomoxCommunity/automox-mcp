"""MCP App: access certification (RBAC) review (issue #182).

A read-first security-hygiene surface. Attaches to the existing read tool
``list_users`` and renders each account user with their RBAC roles and 2FA
status, so an operator can review access and **certify** (acknowledge) or
**flag** each user inline rather than stitching several read calls together.
Certification is an in-session review acknowledgment — it writes nothing.

**Why this App is read-first — a deliberate scope choice, NOT because the API
can't write.** The issue allows *optional* gated changes; acting on a finding
splits three ways, blocked for three distinct reasons (do not conflate them):

* **API-key revocation** — *fully wireable today* and numeric-keyed
  (``list_user_api_keys`` → ``update_user_api_key(is_enabled=False)`` /
  ``delete_user_api_key``). Deferred to a fast-follow (issue #192) — this is the
  obvious next lever, not an API limitation.
* **Role change** — *no API tool.* RBAC role is set only at invite time
  (``account_rbac_role`` on ``invite_user_to_account``); ``update_user`` is
  profile-only. A true API gap.
* **Membership revoke** — *exists and is Tier-1 gated, but unreachable from
  here.* ``remove_user_from_account`` needs a user **UUID**, but ``list_users``
  projects a numeric ``id`` (no UUID). Blocked on the UUID-listing gap (issue
  #193).

So this App ships **read-first / review-only** by choice. The existing Tier-1
account write tools (``invite_user_to_account``, ``update_user``,
``remove_user_from_account``) remain available as direct, host-confirmed tool
calls. Non-Apps hosts use ``list_users`` directly (graceful degradation).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastmcp.apps import UI_MIME_TYPE

from ._app_bridge import MCP_APP_BRIDGE_JS

if TYPE_CHECKING:
    from fastmcp import FastMCP

#: URI of the access-certification review App. Imported by ``tools/account_tools.py``.
ACCESS_CERTIFICATION_APP_URI = "ui://automox/access-certification.html"

_HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Automox — Access Certification</title>
<style>
  :root {
    --bg: #0e1116; --panel: #171b22; --border: #272d39; --text: #e6e9ef;
    --muted: #9aa4b2; --good: #2ea043; --warn: #d29922; --bad: #f85149;
    --accent: #4c8dff; --radius: 10px;
  }
  [data-theme="light"] {
    --bg: #f6f8fa; --panel: #fff; --border: #d8dee4; --text: #1f2328;
    --muted: #636c76; --good: #1a7f37; --warn: #9a6700; --bad: #cf222e;
    --accent: #0969da;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 16px; background: var(--bg); color: var(--text);
    font: 14px/1.5 var(--font-sans, system-ui, -apple-system, "Segoe UI", sans-serif);
  }
  h1 { font-size: 16px; margin: 0 0 2px; }
  .sub { color: var(--muted); font-size: 12px; margin-bottom: 14px; }
  .row {
    display: flex; gap: 12px; align-items: flex-start; padding: 11px 12px;
    background: var(--panel); border: 1px solid var(--border);
    border-radius: var(--radius); margin-bottom: 9px;
  }
  .row.certified { border-color: var(--good); }
  .row.flagged { border-color: var(--warn); }
  .info { flex: 1 1 auto; min-width: 0; }
  .name { font-weight: 600; }
  .email { color: var(--muted); font-size: 12px; }
  .roles { margin-top: 4px; display: flex; flex-wrap: wrap; gap: 5px; }
  .chip {
    background: var(--bg); border: 1px solid var(--border); border-radius: 6px;
    padding: 1px 7px; font-size: 11px;
  }
  .tfa { font-size: 11px; margin-top: 4px; }
  .tfa.off { color: var(--bad); }
  .tfa.on { color: var(--good); }
  .actions { display: flex; flex-direction: column; gap: 6px; flex: 0 0 auto; }
  .btn {
    border: 1px solid var(--border); border-radius: 6px; padding: 4px 10px;
    font-size: 12px; cursor: pointer; background: var(--panel); color: var(--text);
  }
  .btn.certify { border-color: var(--good); color: var(--good); }
  .btn.flag { border-color: var(--warn); color: var(--warn); }
  .btn.active { background: var(--accent); color: #fff; border-color: var(--accent); }
  .empty { padding: 16px 12px; color: var(--muted); }
</style>
</head>
<body>
  <h1>Access Certification</h1>
  <div class="sub" id="sub">Loading users…</div>
  <div id="list"></div>
<script>__MCP_APP_BRIDGE__</script>
<script>
(function () {
  "use strict";
  var App = window.AutomoxApp;
  var els = { sub: document.getElementById("sub"), list: document.getElementById("list") };
  var gotData = false;
  var users = [];
  var state = {};   // userKey -> "certified" | "flagged" | undefined (in-session only)

  function esc(v) {
    return String(v == null ? "" : v)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }
  function userKey(u, i) {
    return String(u.id != null ? u.id : (u.email != null ? u.email : i));
  }
  function fullName(u) {
    var n = [u.firstname, u.lastname].filter(Boolean).join(" ");
    return n || u.name || u.email || "(unnamed user)";
  }
  function roleNames(u) {
    var out = [];
    function add(list) {
      if (!Array.isArray(list)) return;
      for (var i = 0; i < list.length; i++) {
        var r = list[i];
        if (r == null) continue;
        out.push(typeof r === "object" ? (r.name || r.role || r.id) : r);
      }
    }
    add(u.account_rbac_roles);
    add(u.rbac_roles);
    return out;
  }

  function summary() {
    var c = 0, f = 0;
    for (var k in state) {
      if (state[k] === "certified") c++; else if (state[k] === "flagged") f++;
    }
    els.sub.textContent = users.length + " user(s) · " + c + " certified · " + f + " flagged" +
      " · certification is a review acknowledgment (writes nothing)";
  }

  function renderRow(u, i) {
    var key = userKey(u, i);
    var roles = roleNames(u);
    var tfa = u.tfa_type;
    var row = document.createElement("div");
    row.className = "row" + (state[key] ? " " + state[key] : "");
    var roleChips = roles.length
      ? roles.map(function (r) { return '<span class="chip">' + esc(r) + "</span>"; }).join("")
      : '<span class="chip">no roles</span>';
    row.innerHTML =
      '<div class="info">' +
        '<div class="name">' + esc(fullName(u)) + "</div>" +
        '<div class="email">' + esc(u.email || "") + "</div>" +
        '<div class="roles">' + roleChips + "</div>" +
        '<div class="tfa ' + (tfa ? "on" : "off") + '">' +
          (tfa ? "2FA: " + esc(tfa) : "⚠ no 2FA") + "</div>" +
      "</div>" +
      '<div class="actions">' +
        '<button class="btn certify' +
          (state[key] === "certified" ? " active" : "") + '">Certify</button>' +
        '<button class="btn flag' +
          (state[key] === "flagged" ? " active" : "") + '">Flag</button>' +
      "</div>";
    var btns = row.querySelectorAll("button");
    btns[0].addEventListener("click", function () {
      state[key] = state[key] === "certified" ? undefined : "certified";
      rerender();
    });
    btns[1].addEventListener("click", function () {
      state[key] = state[key] === "flagged" ? undefined : "flagged";
      rerender();
    });
    return row;
  }

  function rerender() {
    els.list.innerHTML = "";
    if (!users.length) {
      els.list.innerHTML = '<div class="empty">No users to review.</div>';
      summary();
      return;
    }
    for (var i = 0; i < users.length; i++) els.list.appendChild(renderRow(users[i], i));
    summary();
  }

  function render(env) {
    if (!env || typeof env !== "object") return;
    gotData = true;
    var data = env.data || env;
    users = Array.isArray(data.users) ? data.users : [];
    rerender();
  }

  App.onData(render);
  setTimeout(function () {
    if (!gotData) els.sub.textContent = "Run list_users to review and certify account access here.";
  }, 2000);
})();
</script>
</body>
</html>
"""

_ACCESS_CERTIFICATION_HTML = _HTML_TEMPLATE.replace("__MCP_APP_BRIDGE__", MCP_APP_BRIDGE_JS)


def register(server: FastMCP) -> None:
    """Register the access-certification (RBAC) review App HTML resource."""

    @server.resource(
        ACCESS_CERTIFICATION_APP_URI,
        name="automox_access_certification_app",
        description=(
            "MCP App UI for reviewing account users, their RBAC roles, and 2FA status "
            "and certifying/flagging access inline (read-first; certification writes "
            "nothing) — the review surface for list_users."
        ),
        mime_type=UI_MIME_TYPE,
    )
    def access_certification_app() -> str:
        return _ACCESS_CERTIFICATION_HTML


__all__ = ["register", "ACCESS_CERTIFICATION_APP_URI"]
