# Automox MCP Server

[![CI](https://github.com/AutomoxCommunity/automox-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/AutomoxCommunity/automox-mcp/actions/workflows/ci.yml)
[![Security Scans](https://github.com/AutomoxCommunity/automox-mcp/actions/workflows/security.yml/badge.svg)](https://github.com/AutomoxCommunity/automox-mcp/actions/workflows/security.yml)
[![Publish Release](https://github.com/AutomoxCommunity/automox-mcp/actions/workflows/release.yml/badge.svg)](https://github.com/AutomoxCommunity/automox-mcp/actions/workflows/release.yml)
[![PyPI version](https://badge.fury.io/py/automox-mcp.svg)](https://badge.fury.io/py/automox-mcp)

Talk to your Automox console using natural language. This [MCP server](https://modelcontextprotocol.io/) connects AI assistants like Claude to your Automox environment so you can manage devices, check compliance, run policies, and more — just by asking.

```
You:   "Are we ready for Patch Tuesday?"
Claude: Here's your readiness summary — 3 devices need patches,
        2 approvals are pending, and your patch policies run tonight at 2 AM...
```

> [!IMPORTANT]
> The project is under active development. Contributions and suggestions are welcome via [GitHub Issues](https://github.com/AutomoxCommunity/automox-mcp/issues).

> [!CAUTION]
> AI assistants can make mistakes. Data produced by the MCP server may be incorrect or incomplete. If you see this happening consistently, please [open an issue](https://github.com/AutomoxCommunity/automox-mcp/issues).

## Quick Start

### 1. Get your Automox credentials

You need three values from the [Automox Console](https://console.automox.com):

| Value | Where to find it |
|---|---|
| **API Key** | Settings > Secrets & Keys > Add API Key ([docs](https://docs.automox.com/product/Product_Documentation/Settings/Managing_Keys.htm)) |
| **Account UUID** | Settings > Secrets & Keys (shown on the page) |
| **Org ID** | The numeric ID in the URL when viewing your organization |

> Both global and org-scoped API keys work. All three values are always required.

### 2. Create a `.env` file

```bash
AUTOMOX_API_KEY=your-api-key
AUTOMOX_ACCOUNT_UUID=your-account-uuid
AUTOMOX_ORG_ID=your-org-id
```

### 3. Connect to your AI assistant

**Claude Code (CLI):**
```bash
claude mcp add automox-mcp uvx -- --env-file /path/to/.env automox-mcp
```

**Claude Desktop / Cursor / any MCP client** — add to your MCP config:
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

The server exposes 45 tools across devices, policies, patches, groups, webhooks, and more. You don't need to know the tool names — just describe what you want:

| Ask this | What happens |
|---|---|
| "Are we ready for Patch Tuesday?" | Checks pending patches, approvals, and policy schedules |
| "What is our compliance posture?" | Returns compliance rates, non-compliant devices, and health breakdown |
| "Give me the full profile for the Caldera server" | Combines device details, inventory, packages, and policy status |
| "What devices need attention?" | Surfaces devices flagged for immediate action |
| "Reboot the device 'Testing box'" | Searches for the device and issues a reboot command |
| "Create a patch policy for Firefox targeting the 'MCP testing' group" | Creates the policy with sensible defaults |
| "What did Mark Hansen do in Automox last week?" | Queries the audit trail across the date range |

For the full list of tools, parameters, and MCP resources, see the **[Tool Reference](docs/tool-reference.md)**.

> **Tip:** You can also ask the server itself — the `discover_capabilities` tool returns all available tools organized by domain.

## Configuration

### Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `AUTOMOX_API_KEY` | Yes | — | Automox API key |
| `AUTOMOX_ACCOUNT_UUID` | Yes | — | Account UUID from Secrets & Keys |
| `AUTOMOX_ORG_ID` | Yes | — | Numeric organization ID |
| `AUTOMOX_MCP_READ_ONLY` | No | `false` | Disable all write operations (29 of 45 tools remain) |
| `AUTOMOX_MCP_MODULES` | No | all | Comma-separated list of modules to load (see below) |
| `AUTOMOX_MCP_TOKEN_BUDGET` | No | `4000` | Max estimated tokens per response before truncation |
| `AUTOMOX_MCP_SANITIZE_RESPONSES` | No | `true` | Sanitize API data to mitigate prompt injection |
| `AUTOMOX_MCP_TOOL_PREFIX` | No | — | Prefix all tool names (e.g., `automox`) to prevent cross-server collisions |
| `AUTOMOX_MCP_LOG_FORMAT` | No | `text` | Log format: `text` or `json` (structured JSON for SIEM integration) |
| `AUTOMOX_MCP_TRANSPORT` | No | `stdio` | Transport: `stdio`, `http`, or `sse` |
| `AUTOMOX_MCP_HOST` | No | `127.0.0.1` | Bind address for HTTP/SSE |
| `AUTOMOX_MCP_PORT` | No | `8000` | Bind port for HTTP/SSE |
| `AUTOMOX_MCP_ALLOW_REMOTE_BIND` | No | `false` | Allow binding to non-loopback addresses (required for `0.0.0.0` or external IPs) |

### Read-Only Mode

```bash
AUTOMOX_MCP_READ_ONLY=true
```

Disables all write operations. Only read-only tools are registered (29 of 45). Useful for auditing and monitoring.

### Modular Loading

Load only the tool modules you need:

```bash
AUTOMOX_MCP_MODULES=devices,policies
```

Available modules: `audit`, `devices`, `policies`, `users`, `groups`, `events`, `reports`, `packages`, `webhooks`, `compound`

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

## Security

The Automox MCP server is designed for enterprise deployment with defense-in-depth security controls.

**Highlights:**

- **Read-only mode** (`AUTOMOX_MCP_READ_ONLY`) disables all 16 write tools
- **Module filtering** (`AUTOMOX_MCP_MODULES`) for least-privilege tool loading
- **Correlation IDs** on every tool call, forwarded to Automox API as `X-Correlation-ID`
- **Rate limiting** (30 calls/60s) with token budget estimation and auto-truncation
- **API key isolation** — stored as private attribute with per-request auth injection (no header storage)
- **Generic error responses** — no internal paths, connection strings, or API keys in error output
- **Prompt injection mitigation** — API response sanitization strips markdown exfiltration vectors and instruction prefixes
- **Webhook secret handling** — secrets stripped from idempotency cache after creation
- **Structured JSON logging** (`AUTOMOX_MCP_LOG_FORMAT=json`) for SIEM integration
- **Tool name prefixing** (`AUTOMOX_MCP_TOOL_PREFIX`) to prevent cross-server collisions
- **Sigstore-signed releases** with CycloneDX SBOM
- **SSRF prevention** — webhook URLs validated against private/loopback IPs and cloud metadata endpoints
- **Remote bind protection** — non-loopback HTTP/SSE binding requires explicit `--allow-remote-bind` opt-in
- **25 security hardening items** (V-001 through V-018, V-101 through V-107) documented in CHANGELOG and SECURITY.md

For vulnerability reporting and the full threat model, see [SECURITY.md](SECURITY.md).
For deployment hardening (containers, Kubernetes, MCP gateways, TLS, authentication), see the [Deployment Security Guide](docs/deployment-security.md).
Security posture is benchmarked against the [Wiz MCP Security Best Practices](https://www.wiz.io/blog/mcp-security-best-practices) cheat sheet.

> **Note**: The server does not include authentication or TLS termination by design. For network-accessible deployments, place it behind an MCP gateway or authenticating reverse proxy.

## Alternative Installation

The Quick Start above uses `uvx` which requires no installation. If you prefer a persistent install:

```bash
# Using uv
uv tool install automox-mcp

# Using pip
pip install automox-mcp
```

Then set the environment variables in your shell and run `automox-mcp`.

## Contributing

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
  --stdio-command uv \
  --stdio-args run automox-mcp \
  --stdio-env AUTOMOX_API_KEY=test-api-key \
  --stdio-env AUTOMOX_ACCOUNT_UUID=test-account \
  --stdio-env AUTOMOX_ORG_ID=1 \
  --stdio-env AUTOMOX_MCP_SKIP_DOTENV=1 \
  --analyzers yara \
  --format summary
```

## Versioning

Follows [Semantic Versioning](https://semver.org). Update `pyproject.toml`, commit, tag (e.g., `v0.1.0`), and push — the release workflow publishes to PyPI automatically.

## License

MIT License. See [LICENSE](LICENSE).

## Support

Community-driven project, actively maintained but not officially supported by Automox. For questions, bugs, or feature requests, [open a GitHub Issue](https://github.com/AutomoxCommunity/automox-mcp/issues).
