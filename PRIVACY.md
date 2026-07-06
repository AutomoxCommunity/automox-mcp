# Privacy Policy

_Last updated: 2026-05-29_

The canonical, hosted version of this policy is published at <https://www.automox.com/legal/automox-mcp-server-privacy-policy>. This file mirrors it for in-repo reference.

The Automox MCP server is an open-source, locally executed Model Context Protocol (MCP) server that lets a user's own AI assistant interact with the Automox API. It runs on the user's machine (typically inside a desktop AI client such as Claude Desktop, packaged as an MCPB Desktop Extension) and acts as a stateless proxy between that assistant and `console.automox.com`.

This document describes how data is handled when the server is run as distributed (PyPI package, Docker image, or MCPB bundle published by Automox). Self-hosted deployments may differ; this policy applies to the upstream artifact only.

This policy covers **only the local MCP server**. Data transmitted to, and stored within, the Automox platform (`console.automox.com`) — including device, policy, and account data the server reads or writes on your behalf — is governed by the **[Automox Privacy Policy](https://www.automox.com/legal/privacy-policy)**. The "does not collect / store / share" statements below describe the behavior of the local proxy, not the data-handling practices of the Automox platform it connects to.

## Data collection

The Automox MCP server does not collect, store, or transmit any user data beyond what is required to fulfill API requests to the Automox platform.

API credentials (`AUTOMOX_API_KEY`, `AUTOMOX_ACCOUNT_UUID`, `AUTOMOX_ORG_ID`) are read from environment variables at startup and used solely for authenticating requests to the Automox API. Credentials are held in process memory for the lifetime of the server process and are never logged, persisted to disk, or sent to any host other than `console.automox.com`.

## Data usage

All data retrieved from the Automox API is returned directly to the AI assistant that initiated the request. The server performs response sanitization (Unicode normalization, HTML stripping) for prompt-injection defense, but does not analyze, aggregate, or repurpose API data for any other purpose.

The server does not phone home. There is no telemetry, no crash reporting, no usage analytics, and no remote configuration channel.

## Third-party sharing

The server does not share data with any third parties. It communicates exclusively with the Automox API at `console.automox.com` using the credentials the user provides. No telemetry, analytics, or usage data is sent to the server authors or any other service.

Tool calls that contact additional Automox-controlled endpoints (for example, Splashtop remote-control flows initiated through the Automox console) follow the same model: they hit Automox-operated infrastructure, not third-party services.

## Data retention

The server retains no persistent data between sessions. In-memory caches (idempotency keys, rate-limit counters, paginated cursors) are cleared when the process exits. Structured logs, when enabled, are written to `stderr` and are the deployer's responsibility to manage and retain — Automox does not collect those logs.

## User control

* **Read-only mode** — Setting `AUTOMOX_MCP_READ_ONLY=true` (or toggling "Read-only mode" in the MCPB user-config UI) disables every write tool. Only read-only tools are registered with the host.
* **Tool annotations** — Every tool exposes MCP `readOnlyHint`, `destructiveHint`, `idempotentHint`, and `openWorldHint` annotations so the host client can surface confirmation prompts before destructive actions.
* **Credential revocation** — API keys can be rotated or revoked at any time in the Automox Console under **Settings → Secrets & Keys**. Revocation takes effect immediately on the Automox side; the local server holds no cached authorization beyond the live credential.

## Source code and verification

The full source code is available at <https://github.com/AutomoxCommunity/automox-mcp>. Network egress can be verified at runtime — the server only opens HTTPS connections to `console.automox.com` (plus any Automox-operated subdomains required by the specific tool being invoked).

## Contact

Security or privacy questions: see [`SECURITY.md`](SECURITY.md) for the disclosure process, or contact <security@automox.com>.
