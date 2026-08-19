# Automox MCP Server

<!-- mcp-name: com.automox/automox-mcp -->

[![CI](https://github.com/AutomoxCommunity/automox-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/AutomoxCommunity/automox-mcp/actions/workflows/ci.yml)
[![Security Scans](https://github.com/AutomoxCommunity/automox-mcp/actions/workflows/security.yml/badge.svg)](https://github.com/AutomoxCommunity/automox-mcp/actions/workflows/security.yml)
[![Publish Release](https://github.com/AutomoxCommunity/automox-mcp/actions/workflows/release.yml/badge.svg)](https://github.com/AutomoxCommunity/automox-mcp/actions/workflows/release.yml)
[![PyPI version](https://badge.fury.io/py/automox-mcp.svg)](https://badge.fury.io/py/automox-mcp)

The official MCP server for Automox. Talk to your Automox console using natural language — this [MCP server](https://modelcontextprotocol.io/) connects AI assistants like Claude to your Automox environment so you can manage devices, check compliance, run policies, and more, just by asking.

```
You:   "Are we ready for Patch Tuesday?"
Claude: Here's your readiness summary — 3 devices need patches,
        2 approvals are pending, and your patch policies run tonight at 2 AM...
```

> [!IMPORTANT]
> For bug reports or feature requests, use [help.automox.com](https://help.automox.com) or your typical escalation paths.

> [!CAUTION]
> AI assistants can make mistakes. Responses produced by the MCP server may be incorrect or incomplete. If you see this happening consistently, please let us know.

## Table of Contents

- [What's New in 3.0](#whats-new-in-30)
- [Self-Hosted vs. Hosted](#self-hosted-vs-hosted)
- [Quick Start](#quick-start)
- [What Can I Ask?](#what-can-i-ask)
- [Configuration](#configuration)
- [Security](#security)
- [Privacy Policy](#privacy-policy)
- [Alternative Installation](#alternative-installation)
- [Updating](#updating)
- [Migrating to the Hosted Server](#migrating-to-the-hosted-server)
- [Troubleshooting](#troubleshooting)
- [Frequently Asked Questions](#frequently-asked-questions)
- [Development](#development)
- [Versioning](#versioning)
- [License](#license)
- [Support](#support)

## What's New in 3.0

**Automox MCP Server 3.0** adds a centrally hosted option to replace the legacy self-hosted solution. The hosted server supports all the functionality you're already using, plus one new capability.

- **Hosted server:** Automox now runs and maintains a version of this same server for you. Nothing to install, connect your AI client to `https://console.automox.com/api/mcp` with your existing API key. See [Self-Hosted vs. Hosted](#self-hosted-vs-hosted) below.
- **Policy Catalog templates (hosted only):** The hosted service can search Automox's library of best-practice policy templates and create a policy directly from one, so you have a starting point without building a policy from scratch. This is separate from asking about the policies already deployed in your org, this is Automox's own recommended template library.
- **No capability loss:** The hosted service exposes the same tool coverage you already have through this repository.
- **No forced migration:** This self-hosted server and the Claude Desktop extension keep working exactly as they do today. Moving to the hosted service is currently optional (but recommended), see [Migrating to the Hosted Server](#migrating-to-the-hosted-server).
- **Auth is unchanged for now:** Both versions use the same Automox API key. SSO is planned for a future release.

## Self-Hosted vs. Hosted

Both run the same open-source server code. The difference is who installs and runs it, and one capability that's currently hosted-only.

| | **Self-hosted (this repository)** | **Hosted (MCP Server 3.0)** |
|---|---|---|
| **Install** | You install and keep it updated (PyPI, `uvx`, the Claude Desktop extension, or via Claude's Connectors Directory) | Nothing to install, Automox runs it |
| **Where it runs** | Your machine | Automox's multi-tenant service |
| **Auth** | Your Automox API key | Your Automox API key (same model, for now) |
| **Claude Desktop** | Works today via the one-click extension, installable from GitHub Releases or Claude's Connectors Directory | Not yet, Claude Desktop's built-in custom connector requires OAuth, which the hosted service doesn't support yet |
| **Other clients (Claude Code, Cursor, MCP Inspector, etc.)** | Works via your local config | Works today over HTTP with a Bearer token header |
| **Good fit if** | You want to run your own infrastructure, or you use Claude Desktop today | You want zero maintenance and use a client that supports custom HTTP headers |

For self-hosted setup, see [Quick Start](#quick-start) below. For the hosted server, see [Migrating to the Hosted Server](#migrating-to-the-hosted-server), which also covers connecting fresh with no prior install.

## Quick Start

### 1. Get your Automox credentials

You need three values from the [Automox Console](https://console.automox.com):

| Value | Where to find it |
|---|---|
| **API Key** | Use an **org-scoped** key — zone **Settings > Secrets & Keys > Add API Key** ([docs](https://docs.automox.com/product/Product_Documentation/Settings/Managing_Keys.htm)); see key types below |
| **Account UUID** | Settings > Secrets & Keys (shown on the page) |
| **Org ID** | The numeric ID in the URL when viewing your organization |

Automox has **two API key types**, and the difference matters here:

| | **Org-scoped key** (recommended) | **Global / account key** |
|---|---|---|
| Scope | One organization — the zone it was created in | Every org in the account; inherits the key owner's role per org |
| Created at | Zone **Settings > Secrets & Keys** | Account **Global Access Management > Keys** (Full Administrator) |
| Tool coverage | **All tools** (verified: works immediately on the search family) | **Unreliable on the Advanced Device Search family** — `advanced_device_search`, `device_search_typeahead`, saved-search create/read/update/delete, `list_searches_for_device`, `get_device_assignments` — observed returning `403` in most orgs even for full administrators, while working in others; the upstream authorization behavior is inconsistent and the mechanism is unconfirmed |

> **Symptom:** `403` on the search tools while reads work everywhere else usually means the key, not your permissions — switch to an org-scoped key for the target org. API Key and Account UUID are always required. Org ID is recommended but optional — some tools that don't require org context will work without it.

### 2. Create a `.env` file

```bash
AUTOMOX_API_KEY=your-api-key
AUTOMOX_ACCOUNT_UUID=your-account-uuid
AUTOMOX_ORG_ID=your-org-id
```

### 3. Connect to your AI assistant

**Claude Desktop (recommended) — one-click MCPB install:**

> **New:** Automox MCP is now also listed directly in Claude's Connectors Directory. Open Claude Desktop, go to **Settings > Connectors**, and search "Automox" to connect without leaving the app. The manual steps below still work too, nothing about them has changed.

1. Download the latest `automox-mcp-<version>.mcpb` from the [GitHub Releases page](https://github.com/AutomoxCommunity/automox-mcp/releases/latest).
2. Open Claude Desktop → **Settings → Extensions**.
3. Drag the `.mcpb` file into the Extensions window.
4. Paste your API key, Account UUID, and (optionally) Org ID into the prompts.

No `.env` file, no terminal — credentials are stored in Claude Desktop's secure config. The bundle pulls the matching `automox-mcp` release from PyPI on first run.

**Claude Code (CLI):**
```bash
claude mcp add automox-mcp uvx -- --env-file /path/to/.env automox-mcp
```

**Cursor / any other MCP client** — add to your MCP config:
```json
{
  "mcpServers": {
    "automox-mcp": {
      "command": "uvx",
      "args": ["--env-file", "/path/to/.env", "automox-mcp"]
    }
  }
}
```

That's it. Start asking questions.

## What Can I Ask?

The server exposes 130+ tools across devices, policies, patches, groups, webhooks, worklets, vulnerability sync, maintenance windows, and more. You don't need to know the tool names — just describe what you want:

| Ask this | What happens |
|---|---|
| "Are we ready for Patch Tuesday?" | Checks pending patches, approvals, and policy schedules |
| "What is our compliance posture?" | Returns compliance rates, non-compliant devices, and health breakdown |
| "Give me the full profile for the Caldera server" | Combines device details, inventory, packages, and policy status |
| "What devices need attention?" | Surfaces devices flagged for immediate action |
| "Reboot the device 'Testing box'" | Searches for the device and issues a reboot command |
| "Create a patch policy for Firefox targeting the 'MCP testing' group" | Creates the policy with sensible defaults |
| "What did Mark Hansen do in Automox last week?" | Queries the audit trail across the date range |
| "Find all Windows devices not seen in 30 days" | Uses advanced device search with structured queries |
| "Show me vulnerability remediation status" | Lists action sets with issues, solutions, and progress |
| "Search the worklet catalog for USB security" | Browses community worklets with evaluation/remediation code |

For the full list of tools, parameters, and MCP resources, see the **[Tool Reference](docs/tool-reference.md)**.

> **Tip:** You can also ask the server itself — the `discover_capabilities` tool returns all available tools organized by domain.

## Configuration

### Environment Variables

Applies only to self-hosted 2.x servers. Not applicable to the hosted 3.0+ server.

| Variable | Required | Default | Description |
|---|---|---|---|
| `AUTOMOX_API_KEY` | Yes | — | Automox API key (org-scoped recommended — see [key types](#1-get-your-automox-credentials)) |
| `AUTOMOX_ACCOUNT_UUID` | Yes | — | Account UUID from Secrets & Keys |
| `AUTOMOX_ORG_ID` | Recommended | — | Numeric organization ID (required by most tools) |
| `AUTOMOX_MCP_READ_ONLY` | No | `false` | Disable all write operations (85 of 133 tools remain) |
| `AUTOMOX_MCP_ALLOW_APPLY_REMEDIATION_ACTIONS` | No | `false` | Opt in to the `apply_remediation_actions` tool, which patches/runs worklets on endpoints immediately. Off by default even in write mode. |
| `AUTOMOX_MCP_ALLOW_SPLASHTOP_BULK_INSTALL_UNINSTALL` | No | `false` | Opt in to the `splashtop_bulk_install_uninstall` tool, which installs/uninstalls the Splashtop client across an entire server group in one call. Off by default even in write mode. |
| `AUTOMOX_MCP_ALLOW_DELETE_DEVICE` | No | `false` | Opt in to the `delete_device` tool, which permanently deletes a device record and its history (`DELETE /servers/{id}`). Irreversible and not reconstructable through the MCP. Off by default even in write mode. |
| `AUTOMOX_MCP_ALLOW_UPLOAD_POLICY_FILE` | No | `false` | Opt in to the `upload_policy_file` tool, which uploads a **local** installer file to a Required Software policy. Reads from the local filesystem, so it also requires `AUTOMOX_MCP_UPLOAD_ALLOWED_DIRS` and only works on the stdio (local) transport. Off by default even in write mode. |
| `AUTOMOX_MCP_UPLOAD_ALLOWED_DIRS` | No | — | Comma-separated absolute directories `upload_policy_file` may read installers from. Required for that tool to register; paths are canonicalized and must resolve inside an allowed dir. |
| `AUTOMOX_MCP_UPLOAD_MAX_BYTES` | No | `10737418240` | Max installer size for `upload_policy_file` (default 10 GB, Automox's ceiling). |
| `AUTOMOX_MCP_UPLOAD_TIMEOUT_SECONDS` | No | `3600` | Upload read/write timeout for `upload_policy_file` (large installers need more than the default request timeout). |
| `AUTOMOX_MCP_MODULES` | No | all | Comma-separated list of modules to load (see below) |
| `AUTOMOX_MCP_TOKEN_BUDGET` | No | `4000` | Max estimated tokens per response before truncation |
| `AUTOMOX_MCP_SANITIZE_RESPONSES` | No | `true` | Sanitize API data to mitigate prompt injection |
| `AUTOMOX_MCP_TOOL_PREFIX` | No | — | Prefix all tool names (e.g., `automox`) to prevent cross-server collisions |
| `AUTOMOX_MCP_LOG_FORMAT` | No | `text` | Log format: `text` or `json` (structured JSON for SIEM integration) |
| `AUTOMOX_MCP_TRANSPORT` | No | `stdio` | Transport: `stdio`, `http`, `sse`, or `streamable-http` |
| `AUTOMOX_MCP_HOST` | No | `127.0.0.1` | Bind address for HTTP/SSE |
| `AUTOMOX_MCP_PORT` | No | `8000` | Bind port for HTTP/SSE |
| `AUTOMOX_MCP_API_KEYS` | No | — | Comma-separated MCP endpoint API keys for HTTP/SSE Bearer-token auth (e.g., `key1,label:key2`) |
| `AUTOMOX_MCP_API_KEY_FILE` | No | — | Path to a file containing MCP endpoint API keys (one per line) |
| `AUTOMOX_MCP_OAUTH_ISSUER` | No | — | OIDC issuer URL for JWT auth (e.g., `https://auth.example.com/realms/main`) |
| `AUTOMOX_MCP_OAUTH_JWKS_URI` | No | — | JWKS endpoint for JWT key rotation (auto-derived from issuer if omitted) |
| `AUTOMOX_MCP_OAUTH_AUDIENCE` | When JWT auth | — | Expected JWT audience claim (prevents token passthrough); **required** when `AUTOMOX_MCP_OAUTH_ISSUER` is set |
| `AUTOMOX_MCP_OAUTH_SERVER_URL` | No | — | Canonical server URL; enables RFC 9728 Protected Resource Metadata |
| `AUTOMOX_MCP_OAUTH_SCOPES` | No | — | Comma-separated required OAuth scopes |
| `AUTOMOX_MCP_ALLOWED_ORIGINS` | No | — | Extra allowed Origin headers for DNS rebinding protection (comma-separated) |
| `AUTOMOX_MCP_ALLOWED_HOSTS` | No | — | Extra allowed Host headers for DNS rebinding protection (comma-separated) |
| `AUTOMOX_MCP_DNS_REBINDING_PROTECTION` | No | `true` | Set to `false` to disable DNS rebinding protection (not recommended) |
| `AUTOMOX_MCP_ALLOW_REMOTE_BIND` | No | `false` | Allow binding to non-loopback addresses (required for `0.0.0.0` or external IPs) |

### Read-Only Mode

```bash
AUTOMOX_MCP_READ_ONLY=true
```

Disables all write operations. Only read-only tools are registered (85 of 133). Useful for auditing and monitoring.

### Modular Loading

Load only the tool modules you need:

```bash
AUTOMOX_MCP_MODULES=devices,policies
```

Available modules: `audit`, `audit_v2`, `devices`, `device_search`, `policies`, `policy_history`, `users`, `groups`, `events`, `reports`, `packages`, `webhooks`, `worklets`, `data_extracts`, `vuln_sync`, `compound`, `policy_windows`

Both settings can be combined:

```bash
AUTOMOX_MCP_READ_ONLY=true
AUTOMOX_MCP_MODULES=devices,policies
```

### HTTP Transport

For non-stdio deployments:

```bash
uvx --env-file .env automox-mcp --transport http --host 127.0.0.1 --port 8000
```

### Endpoint Authentication

When deploying over HTTP or SSE, you can require authentication on the MCP endpoint (separate from the Automox API key). Two strategies are supported:

**Static API keys** (simple):
```bash
automox-mcp --generate-key                         # generate a key
export AUTOMOX_MCP_API_KEYS="amx_mcp_a1b2c3..."    # or use a key file
```

**OAuth 2.1 / JWT** (enterprise IdP integration):
```bash
export AUTOMOX_MCP_OAUTH_ISSUER="https://auth.example.com/realms/main"
export AUTOMOX_MCP_OAUTH_AUDIENCE="https://mcp.example.com"
export AUTOMOX_MCP_OAUTH_SERVER_URL="https://mcp.example.com"  # enables RFC 9728 metadata
```

Clients must include `Authorization: Bearer <token>` on every request. Unauthenticated requests receive `401 Unauthorized` with proper `WWW-Authenticate` headers. No effect on stdio transport.

## Security

The Automox MCP server is designed for enterprise deployment with defense-in-depth security controls.

**Highlights:**

- **Read-only mode** (`AUTOMOX_MCP_READ_ONLY`) disables all 48 write tools
- **Module filtering** (`AUTOMOX_MCP_MODULES`) for least-privilege tool loading
- **Correlation IDs** on every tool call, forwarded to Automox API as `X-Correlation-ID`
- **Rate limiting** (30 calls/60s) with token budget estimation and auto-truncation
- **API key isolation** — stored as private attribute with per-request auth injection (no header storage)
- **Generic error responses** — no internal paths, connection strings, or API keys in error output
- **Prompt injection mitigation** — API response sanitization with Unicode normalization, homoglyph defense, HTML tag/script stripping, and reference-style markdown stripping
- **Webhook secret handling** — secrets stripped from idempotency cache after creation
- **Structured JSON logging** (`AUTOMOX_MCP_LOG_FORMAT=json`) for SIEM integration
- **Tool name prefixing** (`AUTOMOX_MCP_TOOL_PREFIX`) to prevent cross-server collisions
- **Sigstore-signed releases** with CycloneDX SBOM
- **SSRF prevention** — webhook URLs validated against private/loopback IPs and cloud metadata endpoints
- **MCP endpoint authentication** — static API keys or OAuth 2.1/JWT with audience binding and RFC 9728 Protected Resource Metadata
- **DNS rebinding protection** — Origin and Host header validation on all HTTP/SSE connections per the MCP transport spec
- **Security response headers** — `X-Content-Type-Options`, `X-Frame-Options`, `CSP`, `Cache-Control: no-store`, `Strict-Transport-Security` on all HTTP responses
- **Authentication rate limiting** — blocks IPs after repeated auth failures to mitigate brute-force attacks
- **Remote bind protection** — non-loopback HTTP/SSE binding requires explicit `--allow-remote-bind` opt-in
- **MCP Tool Annotations** on all 130+ tools — `readOnlyHint`, `destructiveHint`, `idempotentHint`, and `openWorldHint` per the MCP Protocol specification, enabling client-side confirmation dialogs and safety guardrails
- **Interactive MCP Apps** (`io.modelcontextprotocol/ui`) — inline review/approval surfaces for consequential flows: compliance triage, patch approval, policy blast-radius, remediation apply, and RBAC access certification. Apps-capable hosts render them inline; other hosts degrade gracefully to the structured tool output. Write-flow Apps drive the **existing gated tools** through the host's confirmation — no new tools, no new gates — and ship under the host's deny-all CSP (self-contained, no external/CDN loads)
- **61 security hardening items** (V-001 through V-182, S-001 through S-006) documented in CHANGELOG and SECURITY.md

**Capability model.** The server wraps **100% of the published Automox Console API and Webhooks API**, with a single deliberate exception — **secret-exposing endpoints are never wrapped** (API-key decrypt, password-setting). Every destructive operation is either *ask-first* (host confirmation) or *gated* behind a default-off env flag. Concretely, three categorical rules:

- **Secrets are never handled** — the server never returns secret material and never lets the model set it. Credentials enter only via environment/config; decrypt endpoints are not wrapped, password-setting is excluded, and secret fields are redacted from every projection. This is the **only** intentional omission.
- **Destructive operations are two-tier.** Single-target, recoverable actions are **ask-first** (`destructiveHint: true`, surfaced as a host confirmation dialog, disabled entirely by read-only mode). Operations where per-call confirmation can't protect you — fleet-scale, self-lockout, or arbitrary model-authored code execution — are **gated** behind explicit, default-off env flags (`AUTOMOX_MCP_ALLOW_APPLY_REMEDIATION_ACTIONS`, `AUTOMOX_MCP_ALLOW_SPLASHTOP_BULK_INSTALL_UNINSTALL`, `AUTOMOX_MCP_ALLOW_DELETE_DEVICE`). Device deletion is **gated**, not omitted.

The full coverage map, the gating principle, and every intentional omission are documented in [API Coverage & Intentional Omissions](docs/api-coverage.md).

For vulnerability reporting and the full threat model, see [SECURITY.md](SECURITY.md).
For deployment hardening (containers, Kubernetes, MCP gateways, TLS, authentication), see the [Deployment Security Guide](docs/deployment-security.md).
Security posture is benchmarked against the [Wiz MCP Security Best Practices](https://www.wiz.io/blog/mcp-security-best-practices) cheat sheet.

> **Note**: For network-accessible deployments, enable endpoint authentication (static keys via `AUTOMOX_MCP_API_KEYS` or JWT via `AUTOMOX_MCP_OAUTH_ISSUER`) and/or place the server behind an MCP gateway or authenticating reverse proxy. TLS termination is the deployer's responsibility.

## Privacy Policy

The Automox MCP server acts as a stateless proxy between your AI assistant and the Automox API.

**Data collection:** The server does not collect, store, or transmit any user data beyond what is required to fulfill API requests to the Automox platform. API credentials are read from environment variables at startup and used solely for authenticating requests to the Automox API.

**Data usage:** All data retrieved from the Automox API is returned directly to the AI assistant that initiated the request. The server performs response sanitization (Unicode normalization, HTML stripping) for prompt injection defense, but does not analyze, aggregate, or repurpose API data for any other purpose.

**Third-party sharing:** The server does not share data with any third parties. It communicates exclusively with the Automox API (`console.automox.com`) using the credentials you provide. No telemetry, analytics, or usage data is sent to the server authors or any other service.

**Data retention:** The server retains no persistent data between sessions. In-memory caches (idempotency keys, rate-limit counters) are cleared when the process exits. Structured logs, when enabled, are written to stderr and are the deployer's responsibility to manage and retain.

See the [Automox MCP Server Privacy Policy](https://www.automox.com/legal/automox-mcp-server-privacy-policy) for the full privacy policy (mirrored in [`PRIVACY.md`](PRIVACY.md)).

## Alternative Installation

The Quick Start above uses `uvx` which requires no installation. If you prefer a persistent install:

```bash
# Using uv
uv tool install automox-mcp

# Using pip
pip install automox-mcp
```

Then set the environment variables in your shell and run `automox-mcp`.

## Updating

If you already have the server installed, update to the latest version:

```bash
# uvx (Quick Start method) — force a cache refresh
uvx --refresh automox-mcp

# uv tool install
uv tool upgrade automox-mcp

# pip
pip install --upgrade automox-mcp
```

> **Note:** `uvx` automatically refreshes its cache roughly every 7 days, so most users will pick up new releases without action. Run `uvx --refresh` to get the latest immediately.

## Migrating to the Hosted Server

Automox MCP Server 3.0 (hosted) runs the same tools as this repository, just without a local install to maintain. Migrating is two steps: remove your local server, then connect to the hosted one. There's no in-place upgrade and nothing to convert, no config file to move and no data to port. If you've never run the Automox MCP server before, skip straight to Step 2, there's no package to install.

**Step 1: Remove the local server**

Claude Code:

```bash
claude mcp remove automox
```

Cursor or other config-based clients: remove the `automox-mcp` entry from your MCP config file. Claude Desktop extension removal steps are still being finalized and will be added here once confirmed. In the meantime, it's safe to leave the extension installed and running while you set up and test the hosted connection separately.

**Step 2: Connect to the hosted server**

Claude Code:

```bash
claude mcp add --transport http automox \
  https://console.automox.com/api/mcp \
  --header "Authorization: Bearer YOUR_AUTOMOX_API_KEY"
```

Open a new session and ask something like, "What's our compliance posture?"

MCP Inspector (for evaluation or debugging):

```bash
npx @modelcontextprotocol/inspector
```

In the UI: Transport Type = Streamable HTTP, URL = `https://console.automox.com/api/mcp`, Authentication → Bearer Token = your API key (paste the raw key). Click Connect, then Tools → List Tools.

Other MCP clients (Cursor and similar), any client that supports streamable HTTP with custom headers:

```
URL:      https://console.automox.com/api/mcp
Header:   Authorization: Bearer YOUR_AUTOMOX_API_KEY
```

Your permissions in Automox apply exactly as they do in the console and API. The MCP acts as you. Your self-hosted installation will keep working during a transition period — there's no rush to switch.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Adding the hosted server fails in Claude Desktop's "custom connector" screen | Claude Desktop's built-in custom connector only supports signing in with OAuth. The hosted service doesn't have OAuth yet, it only accepts an API key, so pasting the hosted URL in there will fail. This is a different thing from the Automox MCP desktop extension: install that instead (one-click `.mcpb` install, also in Claude's Connectors Directory). It runs the server locally on your machine and connects using the same API key you already have, so you still get full functionality in Claude Desktop, just through the extension rather than the custom connector screen. |
| `401 Unauthorized` | The `Authorization: Bearer` header is missing or the key is wrong. Send the key exactly as `Bearer <key>`. |
| "OAuth Authentication Failed" or an error about invalid JSON | Your client fell back to OAuth discovery after a `401`. Fix the Bearer header rather than trying a custom header name. |
| `403 Forbidden` on some tools | Check your key's scope. Use an org-scoped key. Some user-management features require admin scopes. |
| Answers look off | AI assistants can make mistakes. Verify important results in the Automox Console before acting on them. |

## Frequently Asked Questions

**Does my self-hosted 2.x server stop working?** No. Your existing self-hosted installation continues to work, there's no change to it or to how you get it. The hosted service is simply a new option if you'd like to use it, on your own timeline, with no requirement to switch.

**Do I lose any capabilities by moving to the hosted service?** No. The hosted service runs the same tools you already have access to today.

**Will I need to switch to SSO?** Not yet. The hosted service uses the same API key model you use today. SSO and per-user authentication are planned for a future release, and we'll provide clear migration guidance when that happens.

**I use Claude Desktop. What should I do?** Keep using the Automox MCP desktop extension for now. Claude Desktop's native connector option requires OAuth, which the hosted service doesn't support yet.

Need help? Reach out through [help.automox.com](https://help.automox.com).

## Development

```bash
git clone https://github.com/AutomoxCommunity/automox-mcp.git
cd automox-mcp
uv python install
uv sync --python 3.13 --dev
```

### Testing

Interactive debugging with MCP Inspector:
```bash
fastmcp dev
```

Run unit tests:
```bash
uv run --python 3.13 --dev pytest
```

Run production smoke tests (requires Automox credentials):
```bash
uv run python tests/smoke_production.py
```

### MCP Scanner

Static analysis with [Cisco's MCP Scanner](https://github.com/cisco-ai-defense/mcp-scanner):

```bash
mcp-scanner \
  --analyzers yara \
  --format summary \
  stdio \
  --stdio-command uv \
  --stdio-arg run \
  --stdio-arg automox-mcp \
  --stdio-env AUTOMOX_API_KEY=test-api-key \
  --stdio-env AUTOMOX_ACCOUNT_UUID=test-account \
  --stdio-env AUTOMOX_ORG_ID=1 \
  --stdio-env AUTOMOX_MCP_SKIP_DOTENV=1
```

## Versioning

Follows [Semantic Versioning](https://semver.org). Update `pyproject.toml`, commit, tag (e.g., `v0.1.0`), and push — the release workflow publishes to PyPI automatically.

## License

MIT License. See [LICENSE](LICENSE).

## Support

The official Automox MCP server. For questions, bugs, or feature requests use [help.automox.com](https://help.automox.com).

To report a security vulnerability, see [SECURITY.md](SECURITY.md) — please do not open a public issue.
