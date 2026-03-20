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
  - [Device Management (8 tools)](#device-management-8-tools)
  - [Policy Management (12 tools)](#policy-management-12-tools)
  - [Package Management (2 tools)](#package-management-2-tools)
  - [Group Management (5 tools)](#group-management-5-tools)
  - [Webhook Management (8 tools)](#webhook-management-8-tools)
  - [Compound Workflows (3 tools)](#compound-workflows-3-tools)
  - [Events (1 tool)](#events-1-tool)
  - [Reports (2 tools)](#reports-2-tools)
  - [Account Management (2 tools)](#account-management-2-tools)
  - [Audit Trail (1 tool)](#audit-trail-1-tool)
  - [MCP Resources](#mcp-resources)
  - [Example Workflows](#example-workflows)
  - [Tool Parameters](#tool-parameters)
- [Configuration](#configuration)
  - [Read-Only Mode](#read-only-mode)
  - [Modular Architecture](#modular-architecture)
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

The MCP server exposes 44 workflow tools designed for common Automox management tasks:

### Device Management (8 tools)
- **`list_devices`** - Summarize device inventory and policy status across the organization. Includes unmanaged devices by default and supports `policy_status`/`managed` filters so you can zero in on, for example, non-compliant managed endpoints.
- **`device_detail`** - Return curated device context (recent policy status, assignments, queued commands, key facts). Pass `include_raw_details=true` only when you explicitly need a sanitized slice of the raw Automox payload.
- **`devices_needing_attention`** - Surface Automox devices flagged for immediate action.
- **`search_devices`** - Search Automox devices by hostname, IP, tag, status, or severity of missing patches. Supports multi-severity filtering (e.g., `["critical", "high"]`).
- **`device_health_metrics`** - Aggregate device health metrics for the organization. Supply `limit` to sample fewer devices (default 500) and `max_stale_devices` to cap the stale-device list for token-friendly responses.
- **`get_device_inventory`** - Retrieve detailed device inventory data (hardware, network, security, services, system, users) via the Console API device-details endpoint. Optionally filter by category.
- **`get_device_inventory_categories`** - List available inventory categories for a device. Categories are dynamic per device.
- **`execute_device_command`** - Issue an immediate command to a device (scan, patch_all, patch_specific, reboot).

### Policy Management (12 tools)
- **`policy_health_overview`** - Summarize recent Automox policy activity. Omit `org_uuid` to let the server resolve it from `AUTOMOX_ORG_ID` / `AUTOMOX_ORG_UUID`.
- **`policy_execution_timeline`** - Review recent executions for a policy.
- **`policy_run_results`** - Fetch per-device results (stdout, stderr, exit codes) for a specific execution token returned by `policy_execution_timeline`.
- **`policy_catalog`** - List Automox policies with type and status summaries. Supports `page` (0-indexed) and `limit` pagination; inspect `metadata.pagination.has_more`, read `metadata.notes`, and follow the optional `metadata.suggested_next_call` hint to keep fetching additional slices when needed.
- **`policy_detail`** - Retrieve configuration and recent history for a policy.
- **`policy_compliance_stats`** - Retrieve per-policy compliance statistics showing compliant vs. non-compliant device counts and compliance rates.
- **`apply_policy_changes`** - Preview or submit structured policy create/update operations. Automatically normalizes helper fields (`filter_name`, `filter_names`) and friendly schedule blocks into Automox's expected payloads, ensuring required fields (e.g., `schedule_days`, `schedule_time`) are present before submission.
- **`patch_approvals_summary`** - Summarize pending patch approvals and their severity.
- **`decide_patch_approval`** - Approve or reject an Automox patch approval request.
- **`execute_policy_now`** - Execute a policy immediately for remediation (all devices or specific device).
- **`clone_policy`** - Clone an existing policy with optional name and server group overrides.
- **`delete_policy`** - Permanently delete a policy by ID.

### Package Management (2 tools)
- **`list_device_packages`** - List software packages installed on a specific device. Returns package names, versions, patch status, and severity.
- **`search_org_packages`** - Search packages across the organization. Filter by managed status or packages awaiting installation.

### Group Management (5 tools)
- **`list_server_groups`** - List all server groups with device counts and assigned policies.
- **`get_server_group`** - Get detailed information about a specific server group.
- **`create_server_group`** - Create a new server group with name, refresh interval, and optional parent group, policies, and notes.
- **`update_server_group`** - Update an existing server group.
- **`delete_server_group`** - Delete a server group permanently.

### Webhook Management (8 tools)
- **`list_webhook_event_types`** - List all available webhook event types with descriptions. Use this to discover which events can trigger webhook deliveries.
- **`list_webhooks`** - List all webhook subscriptions for the organization. Supports cursor-based pagination.
- **`get_webhook`** - Retrieve details for a specific webhook subscription.
- **`create_webhook`** - Create a new webhook subscription. The response includes a signing secret that is **only shown once** -- save it immediately. Max 5 webhooks per organization; URL must be HTTPS.
- **`update_webhook`** - Update an existing webhook (partial update). Can change name, URL, enabled status, or event types.
- **`delete_webhook`** - Delete a webhook subscription permanently.
- **`test_webhook`** - Send a test delivery to a webhook endpoint. Returns success status, HTTP status code, and response time.
- **`rotate_webhook_secret`** - Rotate the signing secret for a webhook. The old secret is immediately invalidated. Save the new secret -- it is only shown once.

### Compound Workflows (3 tools)
- **`get_patch_tuesday_readiness`** - Combined view of pre-patch report, pending approvals, and patch policy schedules. Answers "Are we ready for Patch Tuesday?" in a single call. Includes per-device severity classification computed from CVE data.
- **`get_compliance_snapshot`** - Combined view of non-compliant devices, fleet health metrics, and policy statistics. Answers "What is our compliance posture?" in a single call. Includes compliance rate, device health breakdown, and stale device detection.
- **`get_device_full_profile`** - Complete device profile combining device detail, inventory summary, packages, and policy assignments in a single call. Inventory is summarized with key values per category; packages capped at 25 by default. Metadata includes per-section status, data completeness flag, and item counts for verification.

### Events (1 tool)
- **`list_events`** - List organization events with optional filters by policy, device, user, event name, or date range.

### Reports (2 tools)
- **`prepatch_report`** - Retrieve the pre-patch readiness report showing devices with pending patches before the next scheduled patch window.
- **`noncompliant_report`** - Retrieve the non-compliant devices report showing devices that need attention due to policy failures or missing patches.

### Account Management (2 tools)
- **`invite_user_to_account`** - Invite a user to the Automox account with optional zone assignments.
- **`remove_user_from_account`** - Remove a user from the Automox account by UUID.

### Audit Trail (1 tool)
- **`audit_trail_user_activity`** - Retrieve Automox audit trail events performed by a specific user on a given date, with optional pagination cursor support. Set `include_raw_events=true` to include sanitized event payloads when deeper investigation is required. Pass either the full email address or provide `actor_name`/partial email hints and the tool will resolve the matching Automox user automatically.

### MCP Resources

The server also exposes 9 MCP resources that provide reference data and schemas:

| Resource URI | Description |
|---|---|
| `resource://policies/quick-start` | Copy-paste policy creation templates (recommended starting point) |
| `resource://policies/schema` | Full policy schema for create/update operations |
| `resource://policies/schedule-syntax` | Schedule bitmask syntax reference |
| `resource://servergroups/list` | Live server group ID-to-name mapping |
| `resource://webhooks/event-types` | All 39 webhook event types with categories, descriptions, and delivery limits |
| `resource://filters/syntax` | Device filtering reference (search_devices params, policy device_filters, list_devices filters) |
| `resource://patches/categories` | Severity levels, patch_rule options, package fields, and filter pattern syntax |
| `resource://platform/supported-os` | Supported OS matrix (Windows, Mac, Linux) with versions, architectures, shell types, and Linux distros -- verified against official Automox docs |
| `resource://api/rate-limits` | MCP server rate limiter config, Automox API throttling guidance, and efficiency tips |

### Example Workflows

Below are some real-world examples of how you can utilize the MCP server with your AI assistant.

#### Patch Tuesday Readiness

Check if your organization is ready for Patch Tuesday:

```
Ask: "Are we ready for Patch Tuesday?"
```

The MCP server will return a combined view including:
- Devices needing patches with per-device severity (critical, high, medium, etc.)
- Pending patch approvals
- Active patch policy schedules with days, times, and target groups
- A readiness summary with accurate counts

#### Full Device Profile

Get a complete picture of any device:

```
Ask: "Give me the full profile for the Caldera server"
```

The MCP server will return in a single call:
- Device details (OS, agent version, status, IP, group)
- Hardware/software inventory summarized by category (hardware, network, security, etc.)
- Installed packages
- Policy assignments and compliance status
- Pending commands and device facts

#### Compliance Snapshot

Understand your organization's compliance posture:

```
Ask: "What is our compliance posture?"
```

The MCP server will return:
- Compliance rate (compliant vs. non-compliant devices)
- Non-compliant devices with failing policies identified
- Device health breakdown (status, check-in recency)
- Stale devices that haven't checked in recently
- Policy summary by type (worklet, patch, required software)

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
- **Device tools**: `group_id`, `limit`, `include_unmanaged`, `device_id`, `category`
- **Policy tools**: `org_uuid` (optional; auto-resolved from configured Automox org), `window_days`, `report_days`, `policy_id`
- **Search tools**: `hostname_contains`, `ip_address`, `tag`, `patch_status`, `severity` (string or list)
- **Package tools**: `device_id`, `include_unmanaged`, `awaiting`, `page`, `limit`
- **Group tools**: `group_id`, `name`, `refresh_interval`, `parent_server_group_id`, `policies`, `page`, `limit`
- **Webhook tools**: `org_uuid` (optional; auto-resolved), `webhook_id`, `name`, `url`, `event_types`, `enabled`, `cursor`, `limit`
- **Event tools**: `policy_id`, `server_id`, `user_id`, `event_name`, `start_date`, `end_date`, `page`, `limit`
- **Report tools**: `group_id`, `limit`, `offset`
- **Compound tools**: `group_id`, `device_id`, `max_packages`
- **Audit tools**: `date`, `actor_email`, `actor_uuid`, `cursor`, `limit`, `include_raw_events`, `org_uuid` (optional)
- **Execution tools**:
  - `execute_policy_now`: `policy_id` (required), `action` (remediateAll or remediateDevice), `device_id` (optional, required for remediateDevice)
  - `execute_device_command`: `device_id` (required), `command_type` (scan, patch_all, patch_specific, reboot), `patch_names` (optional, required for patch_specific)
  - `apply_policy_changes`: accepts one or more `operations` where each entry contains `action` (`create`/`update`) and a policy payload. The helper accepts convenient shorthands (`filter_name`, `filter_names`), converts friendly `schedule` blocks, and enforces Automox-friendly defaults (e.g., inclusion of `id` during updates).
  - `policy_run_results`: `policy_uuid`, `exec_token`, and optional filters (`org_uuid`, `result_status`, `device_name`, pagination arguments).

## Configuration

### Read-Only Mode

Set `AUTOMOX_MCP_READ_ONLY=true` to disable all write operations. In this mode, only read-only tools are registered (28 of 44 tools). Destructive tools like `execute_device_command`, `apply_policy_changes`, `create_webhook`, `delete_server_group`, `clone_policy`, `delete_policy`, etc. will not be available.

This is useful for auditing, reporting, and monitoring use cases where you want to prevent accidental modifications.

```bash
AUTOMOX_MCP_READ_ONLY=true
```

### Modular Architecture

Set `AUTOMOX_MCP_MODULES` to a comma-separated list of module names to load only the tools you need. This reduces the tool surface area for focused use cases and improves token efficiency.

Available modules: `audit`, `devices`, `policies`, `users`, `groups`, `events`, `reports`, `packages`, `webhooks`, `compound`

```bash
# Only load device and policy tools
AUTOMOX_MCP_MODULES=devices,policies

# Only load webhook management
AUTOMOX_MCP_MODULES=webhooks

# Load compound tools for high-level workflows
AUTOMOX_MCP_MODULES=compound

# Load everything (default when variable is unset)
# AUTOMOX_MCP_MODULES=
```

Both `AUTOMOX_MCP_READ_ONLY` and `AUTOMOX_MCP_MODULES` can be combined. For example, to expose only read-only device and policy tools:

```bash
AUTOMOX_MCP_READ_ONLY=true
AUTOMOX_MCP_MODULES=devices,policies
```

## Setup & Usage

### Prerequisites
- Python 3.11 or newer
- [`uv`](https://docs.astral.sh/uv/) (recommended) or pip
- Automox Account info
  - Account UUID
  - Org ID
  - API credentials

> [!NOTE]
> Both global and org-scoped API keys work. However, all three environment variables (`AUTOMOX_API_KEY`, `AUTOMOX_ACCOUNT_UUID`, `AUTOMOX_ORG_ID`) are always required. The MCP server uses `AUTOMOX_ORG_ID` to scope every API call to a specific organization, so even a global key needs to be paired with the target org ID.

#### Finding the values in your console

- **API Key**: Log in to Automox Console -> Ellipsis (Top Right) -> Secrets & Keys -> Add API Key ([Docs](https://docs.automox.com/product/Product_Documentation/Settings/Managing_Keys.htm)). Both global and org-scoped keys are supported.
- **Account UUID**: Also found in Secrets & Keys section.
- **Org ID**: Your organization's numeric identifier -- you can usually find this in the URL when managing your organization in the Automox Console. This is required even when using a global API key, as it tells the server which organization to operate against.

### Environment Configuration

Create a `.env` file with your API credentials:

```bash
cp .env.example .env
```

Then edit `.env` to add your credentials:

```bash
# Required
AUTOMOX_API_KEY=your-api-key
AUTOMOX_ACCOUNT_UUID=your-account-uuid-here
AUTOMOX_ORG_ID=your-org-id-here

# Optional
# AUTOMOX_MCP_READ_ONLY=true          # Disable all write operations
# AUTOMOX_MCP_MODULES=devices,policies # Load only specific tool modules
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
  --stdio-env AUTOMOX_ORG_ID=1 \
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
