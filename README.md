# Automox MCP Server

[![CI](https://github.com/AutomoxCommunity/automox-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/AutomoxCommunity/automox-mcp/actions/workflows/ci.yml)
[![Security Scans](https://github.com/AutomoxCommunity/automox-mcp/actions/workflows/security.yml/badge.svg)](https://github.com/AutomoxCommunity/automox-mcp/actions/workflows/security.yml)
[![Publish Release](https://github.com/AutomoxCommunity/automox-mcp/actions/workflows/release.yml/badge.svg)](https://github.com/AutomoxCommunity/automox-mcp/actions/workflows/release.yml)
[![PyPI version](https://badge.fury.io/py/automox-mcp.svg)](https://badge.fury.io/py/automox-mcp)

This project provides a Model Context Protocol (MCP) server that enables Automox customers to access
their Automox console through AI assistants. The server exposes several high-level workflow tools for
managing devices, policies, and user accounts with a focus on common operational tasks.

Rather than a full API wrapper, this package aims to offer a curated set of Automox workflows tailored to
common operational scenarios.

> [!IMPORTANT]
> The project is under active development. Functionality may change before a stable 1.0 release. Contributions and suggestions for additional workflows are welcome! Please provide any feedback through [GitHub Issues](https://github.com/AutomoxCommunity/automox-mcp/issues).

> [!CAUTION]
> Please keep in mind that AI is still nowhere near perfect and it can make mistakes. The data it produces can be incorrect or incomplete. If you see this happening consistently with the MCP server, please open a [GitHub Issue](https://github.com/AutomoxCommunity/automox-mcp/issues) so we can investigate and add stronger guardrails around responses.

## Table of Contents

- [Available Tools](#available-tools)
  - [Device Management (6 tools)](#device-management-6-tools)
  - [Policy Management (9 tools)](#policy-management-9-tools)
  - [Account Management (2 tools)](#account-management-2-tools)
  - [Audit Trail (1 tool)](#audit-trail-1-tool)
  - [Example Workflows](#example-workflows)
  - [Tool Parameters](#tool-parameters)
- [Setup & Usage](#setup--usage)
  - [Prerequisites](#prerequisites)
  - [Finding the values in your console](#finding-the-values-in-your-console)
  - [Environment Configuration](#environment-configuration)
  - [Quick Start (No Installation Required)](#quick-start-no-installation-required)
  - [Run Over HTTP or SSE](#run-over-http-or-sse)
  - [Alternative: Persistent Installation](#alternative-persistent-installation)
- [Editor/Assistant Integrations](#editorassistant-integrations)
  - [If you have Claude CLI installed](#if-you-have-claude-cli-installed)
  - [Using uvx (recommended)](#using-uvx-recommended)
  - [With Individual Environment Variables](#with-individual-environment-variables)
- [Contributing](#contributing)
  - [Getting started](#getting-started)
  - [Testing](#testing)
  - [Running tests](#running-tests)
  - [MCP Scanner](#mcp-scanner)
- [Versioning & Release Notes](#versioning--release-notes)
- [License](#license)
- [Support](#support)

## Available Tools

The MCP server exposes 18 high-level workflow tools designed for common Automox management tasks:

### Device Management (6 tools)
- **`list_devices`** - Summarize device inventory and policy status across the organization. Includes unmanaged devices by default and supports `policy_status`/`managed` filters so you can zero in on, for example, non-compliant managed endpoints.
- **`device_detail`** - Return curated device context (recent policy status, assignments, queued commands, key facts). Pass `include_raw_details=true` only when you explicitly need a sanitized slice of the raw Automox payload.
- **`devices_needing_attention`** - Surface Automox devices flagged for immediate action.
- **`search_devices`** - Search Automox devices by hostname, IP, tag, status, or severity of missing patches.
- **`device_health_metrics`** - Aggregate device health metrics for the organization. Supply `limit` to sample fewer devices (default 500) and `max_stale_devices` to cap the stale-device list for token-friendly responses.
- **`execute_device_command`** - Issue an immediate command to a device (scan, patch_all, patch_specific, reboot).

### Policy Management (9 tools)
- **`policy_health_overview`** - Summarize recent Automox policy activity. Omit `org_uuid` to let the server resolve it from `AUTOMOX_ORG_ID` / `AUTOMOX_ORG_UUID`.
- **`policy_execution_timeline`** - Review recent executions for a policy.
- **`policy_run_results`** - Fetch per-device results (stdout, stderr, exit codes) for a specific execution token returned by `policy_execution_timeline`.
- **`policy_catalog`** - List Automox policies with type and status summaries. Supports `page` (0-indexed) and `limit` pagination; inspect `metadata.pagination.has_more`, read `metadata.notes`, and follow the optional `metadata.suggested_next_call` hint to keep fetching additional slices when needed.
- **`policy_detail`** - Retrieve configuration and recent history for a policy.
- **`apply_policy_changes`** - Preview or submit structured policy create/update operations. Automatically normalizes helper fields (`filter_name`, `filter_names`) and friendly schedule blocks into Automox’s expected payloads, ensuring required fields (e.g., `schedule_days`, `schedule_time`) are present before submission.
- **`patch_approvals_summary`** - Summarize pending patch approvals and their severity.
- **`decide_patch_approval`** - Approve or reject an Automox patch approval request.
- **`execute_policy_now`** - Execute a policy immediately for remediation (all devices or specific device).

### Account Management (2 tools)
- **`invite_user_to_account`** - Invite a user to the Automox account with optional zone assignments.
- **`remove_user_from_account`** - Remove a user from the Automox account by UUID.

### Audit Trail (1 tool)
- **`audit_trail_user_activity`** - Retrieve Automox audit trail events performed by a specific user on a given date, with optional pagination cursor support. Set `include_raw_events=true` to include sanitized event payloads when deeper investigation is required. Pass either the full email address or provide `actor_name`/partial email hints and the tool will resolve the matching Automox user automatically.


### Example Workflows

Below are some real-world examples of how you can utilize the MCP server with your AI assistant.

#### Device Health Summary

Get a quick snapshot of your device health:

```
Ask: "What can you tell me about the health of my devices in Automox?"
```

The MCP server will return a comprehensive summary including:
- Overall fleet health (total devices, compliance rate)
- Device status breakdown (ready, not ready, needs reboot, refreshing)
- Patching status (devices with pending patches, devices needing attention)
- Check-in recency analysis (last 24 hours, 7 days, 30 days, 30+ days)
- Key observations and suggested next steps

#### Reboot a Device

Simple yet effective device management:

```
Ask: "Can you reboot the device 'Testing box' in Automox?"
```

The AI assistant will:
1. Search for devices matching the hostname
2. Present matching devices if there are multiple
3. Execute the reboot command once confirmed
4. Can even verify the reboot was successful by checking device uptime

#### Create and Update Policies

Create a patch policy to keep Firefox up to date:

```
Ask: "Can you create a patch policy that keeps Firefox up to date?
     Make sure to include 'henry' somewhere in the name of the patch policy
     and target the devices in the 'MCP testing' group."
```

The MCP server will:
1. Look up the server group by name
2. Create a patch policy with auto-patching enabled
3. Configure the schedule (weekdays at 2 AM by default)
4. Set up user notifications
5. Display the created policy configuration

You can also easily update policy schedules:

```
Ask: "Can you update the 'Auto-Patch Firefox - henry' policy to only run on weekdays?"
```

The AI will update the schedule from weekend to weekdays automatically.

#### Check the Audit Log

Review user activity in your Automox console:

```
Ask: "What did Mark Hansen do in our Automox console last week?"
```

The MCP server will:
1. Query the audit trail for each day in the specified date range
2. Summarize all activities by day
3. Provide totals and highlight key actions (policy changes, device operations, user management)
4. Identify patterns like policy cleanup or reorganization activities

#### Report Generation

The MCP server supports generating comprehensive reports (works best with Claude Desktop due to PDF generation capabilities):

```
Ask: "Generate a comprehensive report on our policy health and device status"
```

The AI can:
- Gather data from multiple endpoints
- Compile statistics and trends
- Format the information into a readable report
- Export to PDF format (when using Claude Desktop)

> [!NOTE]
> Report generation may take several minutes depending on organization size. Using a lighter model like Haiku can speed this up, though with potential trade-offs in detail. The process is highly customizable based on your needs.

### Tool Parameters

Most tools accept optional parameters for filtering and pagination:
- **Device tools**: `group_id`, `limit`, `include_unmanaged`, `device_id`
- **Policy tools**: `org_uuid` (optional; auto-resolved from configured Automox org), `window_days`, `report_days`, `policy_id`
- **Search tools**: `hostname_contains`, `ip_address`, `tag`, `patch_status`
- **Audit tools**: `date`, `actor_email`, `actor_uuid`, `cursor`, `limit`, `include_raw_events`, `org_uuid` (optional)
- **Execution tools**:
  - `execute_policy_now`: `policy_id` (required), `action` (remediateAll or remediateDevice), `device_id` (optional, required for remediateDevice)
  - `execute_device_command`: `device_id` (required), `command_type` (scan, patch_all, patch_specific, reboot), `patch_names` (optional, required for patch_specific)
  - `apply_policy_changes`: accepts one or more `operations` where each entry contains `action` (`create`/`update`) and a policy payload. The helper accepts convenient shorthands (`filter_name`, `filter_names`), converts friendly `schedule` blocks, and enforces Automox-friendly defaults (e.g., inclusion of `id` during updates).
  - `policy_run_results`: `policy_uuid`, `exec_token`, and optional filters (`org_uuid`, `result_status`, `device_name`, pagination arguments).


## Setup & Usage

### Prerequisites
- Python 3.11 or newer
- [`uv`](https://docs.astral.sh/uv/) (recommended) or pip
- Automox Account info
  - Account UUID
  - Org ID
  - API credentials

#### Finding the values in your console

- **API Key**: Log in to Automox Console → Ellipsis (Top Right) → Secrets & Keys → Add API Key ([Docs](https://docs.automox.com/product/Product_Documentation/Settings/Managing_Keys.htm))
- **Account UUID**: Also found in Secrets & Keys section.
- **Org ID**: Your organization's 6 digit numeric identifier - you can usually find this in the URL when managing your organization in the Automox Console.

### Environment Configuration

Create a `.env` file with your API credentials:

```bash
cp .env.example .env
```

Then edit `.env` to add your credentials:

```bash
AUTOMOX_API_KEY=your-api-key
AUTOMOX_ACCOUNT_UUID=your-account-uuid-here
AUTOMOX_ORG_ID=your-org-id-here
```

### Quick Start (No Installation Required)

The easiest way to run the Automox MCP server is using `uvx`, which automatically downloads and runs the package:

```bash
uvx --env-file .env automox-mcp
```

This approach:
- Requires no installation step
- Automatically uses the latest version
- Loads environment variables from your `.env` file
- Used in MCP client configurations (see Editor/Assistant Integrations below)

### Run Over HTTP or SSE

The CLI entry point now supports all FastMCP transports. Pass `--transport http` to enable the modern streamable HTTP transport or `--transport sse` for Server-Sent Events.

```bash
# Streamable HTTP (recommended)
uvx --env-file .env automox-mcp --transport http --host 127.0.0.1 --port 8000

# Legacy SSE transport (only when your client requires SSE)
uvx --env-file .env automox-mcp --transport sse --host 127.0.0.1 --port 8000
```

If you omit `--host`/`--port`, the CLI defaults to `127.0.0.1:8000`. The same values can be provided with environment variables (`AUTOMOX_MCP_TRANSPORT`, `AUTOMOX_MCP_HOST`, `AUTOMOX_MCP_PORT`, `AUTOMOX_MCP_PATH`) for headless deployments.

### Alternative: Persistent Installation

If you prefer a persistent installation, you can install the package globally:

#### Using uv
```bash
uv tool install automox-mcp
```

#### Using pip
```bash
pip install automox-mcp
```

Then run with environment variables set in your shell:
```bash
export AUTOMOX_API_KEY="your-api-key"
export AUTOMOX_ACCOUNT_UUID="your-account-uuid"
export AUTOMOX_ORG_ID="your-org-id"
automox-mcp
```



## Editor/Assistant Integrations

You can integrate the Automox MCP server with your editor or AI assistant. Here are configuration examples for popular MCP clients:

### If you have Claude CLI installed

```bash
claude mcp add automox-mcp uvx -- --env-file /path/to/.env automox-mcp
```

### Using uvx (recommended)
```json
{
  "mcpServers": {
    "automox-mcp": {
      "command": "uvx",
      "args": [
        "--env-file",
        "/path/to/.env",
        "automox-mcp"
      ]
    }
  }
}
```

### With Individual Environment Variables
```json
{
  "mcpServers": {
    "automox-mcp": {
      "command": "uvx",
      "args": ["automox-mcp"],
      "env": {
        "AUTOMOX_API_KEY": "your-api-key",
        "AUTOMOX_ACCOUNT_UUID": "your-account-uuid-here",
        "AUTOMOX_ORG_ID": "your-org-id-here"
      }
    }
  }
}
```

## Contributing

### Getting started
Clone the repository:

```bash
git clone https://github.com/AutomoxCommunity/automox-mcp.git
cd automox-mcp
```

Install in development mode (the repo pins Python 3.13 via `.python-version`):
```bash
# Ensure the pinned interpreter is available
uv python install

# Create .venv and install project + dev dependencies
uv sync --python 3.13 --dev
```

#### Testing

We recommend using the **MCP Inspector** for interactive debugging. We include a `fastmcp.json` configuration for easy startup.

```bash
fastmcp dev
```
This should open at http://localhost:6274 where you can test tools interactively.

If you want to test locally with something like Claude Code:
```bash
claude mcp add automox-mcp uvx -- --from . --env-file .env automox-mcp
```

### Running tests
```bash
uv run --python 3.13 --dev pytest
```

### MCP Scanner
We use [Cisco's MCP Scanner](https://github.com/cisco-ai-defense/mcp-scanner) for static analysis of the MCP server implementation.

```bash
mcp-scanner \
  --stdio-command uv \
  --stdio-args run automox-mcp \
  --stdio-env AUTOMOX_API_KEY=test-api-key \
  --stdio-env AUTOMOX_ACCOUNT_UUID=test-account \
  --stdio-env AUTOMOX_ORG_ID=0 \
  --stdio-env AUTOMOX_MCP_SKIP_DOTENV=1 \
  --analyzers yara \
  --format summary
```

## Versioning

The project follows [Semantic Versioning](https://semver.org).

When preparing a release:
1. Update `pyproject.toml` with the new version number.
2. Commit the changes and create a matching Git tag (for example, `v0.1.0`).
3. The release workflow will automatically build and publish to PyPI when you push the tag.

## License
This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

## Support
This is a community-driven project, actively maintained but not officially supported by Automox. 

To request assistance, please open a GitHub Issue. This is the appropriate channel for questions, bug reports, feature requests, enhancement suggestions, and documentation updates.
