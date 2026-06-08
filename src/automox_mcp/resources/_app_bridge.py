"""Shared host bridge for Automox MCP App UIs (issue #179+).

A single hand-rolled implementation of the ``io.modelcontextprotocol/ui``
(ext-apps) host↔iframe contract, embedded inline by every write-flow App UI so
each HTML resource stays fully self-contained (no SDK/CDN import, runs under the
host's default deny-all CSP). It exposes a small global, ``window.AutomoxApp``:

* ``onData(cb)``      — ``cb(envelope)`` fires with the entry tool's structured
  ``{data, metadata}`` output on first load and on every subsequent push.
* ``callTool(name, args)`` — returns a ``Promise`` resolving to the called
  tool's ``CallToolResult`` (used by review UIs to drive an existing, already
  destructive-gated write tool; the host mediates and may require confirmation).
* ``onTheme(cb)``     — ``cb("light"|"dark")``; the theme is also applied to
  ``document.documentElement[data-theme]`` automatically.

Protocol: the view posts ``ui/initialize`` then ``ui/notifications/initialized``;
the host streams ``ui/notifications/tool-result`` (the structured output) and
answers ``tools/call`` requests correlated by JSON-RPC id. A ``window.openai``
fallback covers the OpenAI Apps SDK, and a standalone branch degrades without
throwing when no host bridge is present.
"""

from __future__ import annotations

#: Inline JS implementing window.AutomoxApp. Embed inside a ``<script>`` tag.
MCP_APP_BRIDGE_JS = """
(function () {
  "use strict";
  var PROTOCOL_VERSION = "2026-01-26";
  var dataCbs = [], themeCbs = [], pending = {}, nextCallId = 100, initialized = false;

  function post(msg) {
    try { (window.parent || window).postMessage(msg, "*"); } catch (e) {}
  }
  function sendInitialized() {
    if (initialized) return;
    initialized = true;
    post({ jsonrpc: "2.0", method: "ui/notifications/initialized", params: {} });
  }
  function emitData(env) {
    if (!env) return;
    for (var i = 0; i < dataCbs.length; i++) { try { dataCbs[i](env); } catch (e) {} }
  }
  function emitTheme(t) {
    if (t !== "light" && t !== "dark") return;
    document.documentElement.setAttribute("data-theme", t);
    for (var i = 0; i < themeCbs.length; i++) { try { themeCbs[i](t); } catch (e) {} }
  }
  function extractEnvelope(p) {
    if (!p || typeof p !== "object") return null;
    if (p.structuredContent) return p.structuredContent;
    if (p.result && p.result.structuredContent) return p.result.structuredContent;
    if (p.data || p.metadata) return p;
    return null;
  }

  // ext-apps: call a server tool via a JSON-RPC tools/call, correlated by id.
  function extCallTool(name, args) {
    return new Promise(function (resolve, reject) {
      var id = "call-" + (nextCallId++);
      pending[id] = { resolve: resolve, reject: reject };
      post({ jsonrpc: "2.0", id: id, method: "tools/call",
             params: { name: name, arguments: args || {} } });
      setTimeout(function () {
        if (pending[id]) { delete pending[id]; reject(new Error("tool call timed out")); }
      }, 60000);
    });
  }

  window.addEventListener("message", function (ev) {
    var msg = ev.data;
    if (!msg || typeof msg !== "object") return;
    if (msg.id != null && pending[msg.id]) {            // response to a tools/call we issued
      var p = pending[msg.id]; delete pending[msg.id];
      if (msg.error) reject_(p, msg.error); else p.resolve(msg.result);
      return;
    }
    if (msg.id === 1 && msg.result) {                   // response to our ui/initialize
      var ctx = msg.result.hostContext || msg.result;
      if (ctx && ctx.theme) emitTheme(ctx.theme);
      sendInitialized();
      return;
    }
    if (msg.method === "ui/notifications/host-context-changed") {
      if (msg.params && msg.params.theme) emitTheme(msg.params.theme);
      return;
    }
    if (msg.method === "ui/notifications/tool-result" ||
        msg.method === "ui/notifications/tool-input" ||
        msg.method === "ui/render") {
      emitData(extractEnvelope(msg.params));
      return;
    }
    var direct = extractEnvelope(msg);                  // defensive: some hosts post directly
    if (direct) emitData(direct);
  });
  function reject_(p, err) { p.reject(new Error((err && err.message) || "tool call failed")); }

  // OpenAI Apps SDK fallback (window.openai).
  var usingOpenAI = !!window.openai;
  if (usingOpenAI) {
    if (window.openai.toolOutput) emitData(window.openai.toolOutput);
    if (window.openai.theme) emitTheme(window.openai.theme);
    window.addEventListener("openai:set_globals", function (e) {
      var g = e && e.detail && e.detail.globals;
      if (g && "toolOutput" in g) emitData(window.openai.toolOutput);
      if (g && "theme" in g) emitTheme(window.openai.theme);
    });
  }

  window.AutomoxApp = {
    onData: function (cb) { if (typeof cb === "function") dataCbs.push(cb); },
    onTheme: function (cb) { if (typeof cb === "function") themeCbs.push(cb); },
    callTool: function (name, args) {
      if (usingOpenAI && typeof window.openai.callTool === "function") {
        return Promise.resolve(window.openai.callTool(name, args || {}));
      }
      return extCallTool(name, args);
    },
    requestId: function () {
      try { return window.crypto.randomUUID(); } catch (e) { return "req-" + (nextCallId++); }
    }
  };

  // boot
  if (window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches) {
    emitTheme("light");
  }
  post({ jsonrpc: "2.0", id: 1, method: "ui/initialize",
         params: { capabilities: {}, clientInfo: { name: "Automox App", version: "1.0.0" },
                   protocolVersion: PROTOCOL_VERSION } });
  setTimeout(sendInitialized, 800);   // ack even if the host skips the init reply
})();
"""

__all__ = ["MCP_APP_BRIDGE_JS"]
