# Release notes

### v2.2.0 — Interactive in-host review surfaces (2026-06-08) [Feature]

**Review and act on fleet posture visually, right inside your AI assistant.** This release adds five interactive surfaces that render directly in supported hosts: a compliance-triage dashboard, a patch-approval queue, a policy-change blast-radius preview, a remediation-apply review, and an RBAC access-certification review. Instead of reading a wall of text, operators see compliance state, affected devices, and pending decisions laid out visually — and for action-oriented flows they can act in-session, with every change still routed through the assistant's standard confirmation before anything is written.
Caveat: The interactive surfaces require an MCP Apps–capable host; on any other assistant the same information is returned as clean structured data, so nothing is lost.

### v2.1.0 — Clearer, self-describing tool output (2026-06-06) [Improvement]

**Your AI assistant interprets device, policy, and compliance data more accurately.** Tool outputs now carry plain-language explanations of their own status codes, units, and severity values, so the assistant reads your fleet data correctly instead of inferring meaning. The result is more reliable answers about compliance state, patch readiness, and device health — with no change to how you use the tools.

### v2.0.1–v2.0.3 — Sharper device search and precise policy targeting (2026-06-02 → 2026-06-04) [Improvement]

**Advanced Device Search returns exactly the devices that match.** Filter by OS family, group, tag, or any supported attribute and get back a precise, narrowed result set; saved searches create and update dependably, including name- or description-only edits, and type-ahead responds as you build a query. Policy device-filters apply across every policy type, the policy-impact preview reports the affected-device count, and large package inventories return in full.
Caveat: Advanced Device Search is most reliable with an org-scoped API key; the credentials section of the README explains the key types.

### v2.0.0 — Capability and safety model; full published-API coverage (2026-06-01) [Feature]

**Complete, principled coverage of the Automox platform — with safety built in.** This release establishes a clear capability model: the server wraps 100% of the published Console and Webhooks APIs, with the single deliberate exception of secret-exposing endpoints, which it never calls. It adds single-device update, action-set management, installer upload to Required Software policies, and webhook-delivery troubleshooting. High-blast-radius destructive actions (fleet-scale operations, device deletion) follow a consistent, opt-in model: they are off by default and require explicit enablement, so an assistant can never trigger them by accident.
Upgrade: Operators who enabled remediation execution via the older `AUTOMOX_MCP_ALLOW_REMEDIATION` flag must switch to `AUTOMOX_MCP_ALLOW_APPLY_REMEDIATION_ACTIONS`; fleet-wide Splashtop install/uninstall now requires its own opt-in flag. If a flag is unset the capability stays safely withheld.

### v1.2.0 — Major capability expansion (2026-05-30) [Feature]

**Manage identity, access, remediation, and multi-zone policy from your assistant.** This release broadens the surface substantially: account-wide and per-user API key management; visibility into users, zones, and RBAC roles; remediation execution; bulk device tagging; cloning patch policies across zones; richer device search; organization and tier visibility; and policy-run reporting. API-key tools never return secret material.
Caveat: Remediation execution changes endpoint state and is opt-in, disabled by default.

### v1.0.36 — Splashtop Remote Control (2026-05-28) [Feature]

**Drive remote-control sessions through the integration.** Check device and session status and initiate, install, or disconnect Splashtop remote sessions from your assistant.
Caveat: Initiating a session returns a launch link rather than starting control directly, and attended access requires end-user consent — so this is not one-click remote takeover. Remote Control availability depends on your Automox entitlements; confirm current packaging before quoting specifics.

### v1.0.35 — Saved searches and bulk policy assignment (2026-05-28) [Feature]

**Reuse device searches and attach policies in bulk.** Create, update, delete, and reuse saved Advanced Device Searches, and assign policies to the devices a search returns — turning a one-off query into a repeatable targeting workflow.

### v1.0.34 — Faster fleet queries (2026-05-28) [Improvement]

**Device-health and inventory lookups return substantially faster on larger fleets** — roughly a 3–4× speedup on multi-page queries in testing, with no change to results.

### v1.0.20 — One-click install in Claude Desktop (2026-04-29) [Feature]

**Install the Automox MCP server with a drag-and-drop Desktop Extension** — no manual JSON configuration. The server is also published to PyPI and the MCP Registry.

### v1.0.19 — Official Automox MCP server (2026-04-28) [Improvement]

**Now published under Automox's verified namespace in the MCP Registry** as the official Automox MCP server.
Caveat: "Official" designates the publisher; support is community-driven and is not covered by Automox commercial support contracts.

### v1.0.15 — Per-tool safety hints (2026-04-11) [Improvement]

**Every tool declares machine-readable safety hints** — read-only vs. destructive, idempotent or not — so MCP clients can show the right confirmation prompts and guardrails before a write action runs.

### v1.0.4–v1.0.5 — Safer AI workflows (2026-03-30) [Improvement]

**Destructive AI workflows ask for confirmation before they run.** Guided workflows that could reboot or patch devices require an explicit confirmation step, and the server enforces strong authentication and input validation throughout.

### v1.0.0 — General availability (2026-03-29) [Feature]

**Manage your fleet end to end through an AI assistant.** The GA release ships a broad tool surface — device inventory, patch readiness, policy management and cross-zone cloning, server groups, webhooks, worklet search, policy-execution and audit reporting, and maintenance-window scheduling — plus guided workflows for common tasks like Patch Tuesday prep, non-compliant-device investigation, policy-history audits, and security-posture review. It is enterprise-ready out of the box: OAuth 2.1 / JWT and bearer-token authentication, a read-only mode for audit and reporting use cases, and security hardening throughout. API key and webhook secrets are never exposed to the assistant.
Caveat: Connecting requires an MCP-capable host (such as Claude Desktop or another MCP client).

### v0.1.0 — First release (2025-11-13) [Feature]

**The first Automox MCP server.** Initial release letting you query and manage devices, policies, account information, and audit data through an AI assistant — the foundation the GA release built on.
