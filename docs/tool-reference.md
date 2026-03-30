# Tool Reference

Complete reference for all 80 tools, 6 workflow prompts, MCP resources, parameters, and enterprise features exposed by the Automox MCP server.

> **Tip:** You don't need to memorize this. Call `discover_capabilities` from your AI assistant to get a live summary of available tools organized by domain.

## Table of Contents

- [Device Management (8 tools)](#device-management-8-tools)
- [Advanced Device Search (6 tools)](#advanced-device-search-6-tools)
- [Policy Management (12 tools)](#policy-management-12-tools)
- [Policy History v2 (6 tools)](#policy-history-v2-6-tools)
- [Package Management (2 tools)](#package-management-2-tools)
- [Group Management (5 tools)](#group-management-5-tools)
- [Webhook Management (8 tools)](#webhook-management-8-tools)
- [Worklet Catalog (2 tools)](#worklet-catalog-2-tools)
- [Data Extracts (3 tools)](#data-extracts-3-tools)
- [Vulnerability Sync (7 tools)](#vulnerability-sync-7-tools)
- [Compound Workflows (3 tools)](#compound-workflows-3-tools)
- [Events (1 tool)](#events-1-tool)
- [Reports (2 tools)](#reports-2-tools)
- [Account Management (3 tools)](#account-management-3-tools)
- [Audit Trail (2 tools)](#audit-trail-2-tools)
- [Policy Windows (9 tools)](#policy-windows-9-tools)
- [Capability Discovery (1 tool)](#capability-discovery-1-tool)
- [Workflow Prompts (6 prompts)](#workflow-prompts-6-prompts)
- [MCP Resources](#mcp-resources)
- [Tool Parameters](#tool-parameters)
- [Enterprise Features](#enterprise-features)

---

## Device Management (8 tools)

- **`list_devices`** - Summarize device inventory and policy status across the organization. Includes unmanaged devices by default and supports `policy_status`/`managed` filters so you can zero in on, for example, non-compliant managed endpoints.
- **`device_detail`** - Return curated device context (recent policy status, assignments, queued commands, key facts). Pass `include_raw_details=true` only when you explicitly need a sanitized slice of the raw Automox payload.
- **`devices_needing_attention`** - Surface Automox devices flagged for immediate action.
- **`search_devices`** - Search Automox devices by hostname, IP, tag, status, or severity of missing patches. Supports multi-severity filtering (e.g., `["critical", "high"]`).
- **`device_health_metrics`** - Aggregate device health metrics for the organization. Supply `limit` to sample fewer devices (default 500) and `max_stale_devices` to cap the stale-device list for token-friendly responses.
- **`get_device_inventory`** - Retrieve detailed device inventory data (hardware, network, security, services, system, users) via the Console API device-details endpoint. Optionally filter by category.
- **`get_device_inventory_categories`** - List available inventory categories for a device. Categories are dynamic per device.
- **`execute_device_command`** - Issue an immediate command to a device (scan, patch_all, patch_specific, reboot).

## Advanced Device Search (6 tools)

Uses the Server Groups API v2 for structured device queries, saved searches, and UUID-based lookups.

- **`list_saved_searches`** - List saved device searches with names, queries, and metadata.
- **`advanced_device_search`** - Execute an advanced device search using structured query language. Enables complex queries like "find all Windows devices not seen in 30 days" using field-based filtering.
- **`device_search_typeahead`** - Get typeahead suggestions for device search fields. Useful for discovering valid values when building queries.
- **`get_device_metadata_fields`** - Get available fields for device queries. Returns field names and types supported by the advanced search API.
- **`get_device_assignments`** - Get device-to-policy and device-to-group assignments.
- **`get_device_by_uuid`** - Get device details by UUID using the Server Groups API v2.

## Policy Management (12 tools)

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

## Policy History v2 (6 tools)

Richer policy execution reporting via the `/policy-history` API with UUID-based queries, time-range filtering, and aggregate views.

- **`policy_runs_v2`** - List policy runs with time-range filtering, policy name/type filters, and result status filtering.
- **`policy_run_count`** - Get aggregate policy execution counts. Optionally filter by number of days to look back.
- **`policy_runs_by_policy`** - Get policy runs grouped by policy for cross-policy comparison.
- **`policy_history_detail`** - Get policy history details by UUID, including run history and status.
- **`policy_runs_for_policy`** - Get execution runs for a specific policy by UUID with optional day range and sort order.
- **`policy_run_detail_v2`** - Get detailed per-device results for a specific policy run. Supports device name filtering and pagination.

## Package Management (2 tools)

- **`list_device_packages`** - List software packages installed on a specific device. Returns package names, versions, patch status, and severity.
- **`search_org_packages`** - Search packages across the organization. Filter by managed status or packages awaiting installation.

## Group Management (5 tools)

- **`list_server_groups`** - List all server groups with device counts and assigned policies.
- **`get_server_group`** - Get detailed information about a specific server group.
- **`create_server_group`** - Create a new server group with name, refresh interval, and optional parent group, policies, and notes.
- **`update_server_group`** - Update an existing server group.
- **`delete_server_group`** - Delete a server group permanently.

## Webhook Management (8 tools)

- **`list_webhook_event_types`** - List all available webhook event types with descriptions. Use this to discover which events can trigger webhook deliveries.
- **`list_webhooks`** - List all webhook subscriptions for the organization. Supports cursor-based pagination.
- **`get_webhook`** - Retrieve details for a specific webhook subscription.
- **`create_webhook`** - Create a new webhook subscription. The response includes a signing secret that is **only shown once** -- save it immediately. Max 5 webhooks per organization; URL must be HTTPS.
- **`update_webhook`** - Update an existing webhook (partial update). Can change name, URL, enabled status, or event types.
- **`delete_webhook`** - Delete a webhook subscription permanently.
- **`test_webhook`** - Send a test delivery to a webhook endpoint. Returns success status, HTTP status code, and response time.
- **`rotate_webhook_secret`** - Rotate the signing secret for a webhook. The old secret is immediately invalidated. Save the new secret -- it is only shown once.

## Worklet Catalog (2 tools)

- **`search_worklet_catalog`** - Search the Automox community worklet catalog. Returns worklet names, descriptions, categories, and OS compatibility.
- **`get_worklet_detail`** - Get detailed information for a specific community worklet, including evaluation code, remediation code, and requirements.

## Data Extracts (3 tools)

- **`list_data_extracts`** - List available data extracts for the organization. Returns extract names, statuses, and download information.
- **`get_data_extract`** - Get details and download information for a specific data extract.
- **`create_data_extract`** - Request a new data extract for bulk reporting. Returns the extract ID and initial status.

## Vulnerability Sync (7 tools)

Manage vulnerability remediation workflows via the Vuln Sync API. Supports CSV-based import from vulnerability scanners (Qualys, Tenable, etc.).

- **`list_remediation_action_sets`** - List vulnerability remediation action sets for the organization.
- **`get_action_set_detail`** - Get details for a specific vulnerability remediation action set.
- **`get_action_set_actions`** - Get remediation actions for an action set. Shows what patches or changes need to be applied.
- **`get_action_set_issues`** - Get vulnerability issues (CVEs) associated with an action set.
- **`get_action_set_solutions`** - Get solutions for an action set. Shows recommended patches or configurations.
- **`get_upload_formats`** - Get supported CSV upload formats for vulnerability remediation action sets.
- **`upload_action_set`** - Upload a CSV-based vulnerability remediation action set.

## Compound Workflows (3 tools)

- **`get_patch_tuesday_readiness`** - Combined view of pre-patch report, pending approvals, and patch policy schedules. Answers "Are we ready for Patch Tuesday?" in a single call. Includes per-device severity classification computed from CVE data.
- **`get_compliance_snapshot`** - Combined view of non-compliant devices, fleet health metrics, and policy statistics. Answers "What is our compliance posture?" in a single call. Includes compliance rate, device health breakdown, and stale device detection.
- **`get_device_full_profile`** - Complete device profile combining device detail, inventory summary, packages, and policy assignments in a single call. Inventory is summarized with key values per category; packages capped at 25 by default. Metadata includes per-section status, data completeness flag, and item counts for verification.

## Events (1 tool)

- **`list_events`** - List organization events with optional filters by policy, device, user, event name, or date range.

## Reports (2 tools)

- **`prepatch_report`** - Retrieve the pre-patch readiness report showing devices with pending patches before the next scheduled patch window.
- **`noncompliant_report`** - Retrieve the non-compliant devices report showing devices that need attention due to policy failures or missing patches.

## Account Management (3 tools)

- **`invite_user_to_account`** - Invite a user to the Automox account with optional zone assignments.
- **`remove_user_from_account`** - Remove a user from the Automox account by UUID.
- **`list_org_api_keys`** - List API keys for the organization. Returns key names and IDs only — secrets are never exposed.

## Audit Trail (2 tools)

- **`audit_trail_user_activity`** - Retrieve Automox audit trail events performed by a specific user on a given date, with optional pagination cursor support. Set `include_raw_events=true` to include sanitized event payloads when deeper investigation is required. Pass either the full email address or provide `actor_name`/partial email hints and the tool will resolve the matching Automox user automatically.
- **`audit_events_ocsf`** - Query OCSF-formatted audit events from the Audit Service v2. Supports filtering by date, event category (authentication, account_change, entity_management, user_access, web_resource_activity), and event type name. Uses cursor-based pagination for large result sets.

## Policy Windows (9 tools)

Manage maintenance/exclusion windows that prevent policy execution during scheduled periods. Uses the Policy Windows API with org UUID-based endpoints and RFC 5545 RRULE scheduling.

- **`search_policy_windows`** - Search and list maintenance/exclusion windows with optional filtering by group UUIDs, status (`active`/`inactive`), and recurrence type (`recurring`/`once`). Supports pagination via `page`/`size`.
- **`get_policy_window`** - Retrieve details for a specific maintenance window by UUID, including RRULE schedule, duration, assigned groups, and status.
- **`check_group_exclusion_status`** - Check whether one or more server groups are currently within an active exclusion window. Returns a per-group boolean — useful before triggering manual policy runs.
- **`check_window_active`** - Check whether a specific maintenance window is currently active. A window is active when its status is "active", it has at least one group, and the current time falls within an exclusion period.
- **`get_group_scheduled_windows`** - Get upcoming scheduled maintenance periods for a server group with start/end times and window types. Optionally provide a future date limit (ISO 8601 UTC).
- **`get_device_scheduled_windows`** - Get upcoming scheduled maintenance periods for a specific device with start/end times and window types. Optionally provide a future date limit (ISO 8601 UTC).
- **`create_policy_window`** - Create a new maintenance/exclusion window with RFC 5545 RRULE scheduling. Supports recurring windows (e.g., every Monday 2–4 AM) and one-time windows. All fields required.
- **`update_policy_window`** - Update an existing maintenance window. Only `dtstart` is required; all other fields are optional for partial updates.
- **`delete_policy_window`** - Delete a maintenance/exclusion window permanently.

## Capability Discovery (1 tool)

- **`discover_capabilities`** - Return all available tools organized by domain (devices, device_search, policies, policy_history, patches, groups, events, reports, audit, webhooks, worklets, data_extracts, vuln_sync, account, compound, policy_windows). This meta-tool is always loaded regardless of `AUTOMOX_MCP_MODULES` configuration and provides a quick reference for what the server can do.

## Workflow Prompts (6 prompts)

Pre-built guided templates for common admin workflows. These MCP prompts provide step-by-step instructions that structure multi-step operations and reduce hallucination risk.

- **`investigate_noncompliant_device`** - Guided workflow to investigate why a device is non-compliant and remediate it. Walks through device detail, inventory, packages, policy status, execution history, root cause analysis, and remediation.
- **`prepare_patch_tuesday`** - Guided workflow to assess readiness and prepare for Patch Tuesday. Covers readiness checks, pending approvals, policy schedules, at-risk devices, and approval actions.
- **`audit_policy_execution`** - Guided workflow to audit a policy's execution history and identify issues. Includes timeline review, failure analysis, compliance stats, and trend reporting.
- **`onboard_device_group`** - Guided workflow to create and configure a new device group with policies. Covers group creation, policy assignment, worklet discovery, and verification.
- **`triage_failed_policy_run`** - Guided workflow to triage and remediate a failed policy execution. Categorizes failures, investigates top issues, and recommends remediation steps.
- **`review_security_posture`** - Guided workflow to review the organization's fleet security posture. Covers compliance, patches, vulnerabilities, policy health, and recommended actions.

---

## MCP Resources

The server exposes 9 MCP resources that provide reference data and schemas:

| Resource URI | Description |
|---|---|
| `resource://policies/quick-start` | Copy-paste policy creation templates (recommended starting point) |
| `resource://policies/schema` | Full policy schema for create/update operations |
| `resource://policies/schedule-syntax` | Schedule bitmask syntax reference |
| `resource://servergroups/list` | Live server group ID-to-name mapping |
| `resource://webhooks/event-types` | All 39 webhook event types with categories, descriptions, and delivery limits |
| `resource://filters/syntax` | Device filtering reference (search_devices params, policy device_filters, list_devices filters) |
| `resource://patches/categories` | Severity levels, patch_rule options, package fields, and filter pattern syntax |
| `resource://platform/supported-os` | Supported OS matrix (Windows, Mac, Linux) with versions, architectures, shell types, and Linux distros |
| `resource://api/rate-limits` | MCP server rate limiter config, Automox API throttling guidance, and efficiency tips |

---

## Tool Parameters

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

### Special Parameters

- **Write tools** (all 18): accept an optional `request_id` parameter (UUID string) for idempotency. Supplying the same `request_id` on a repeat call returns the cached response without re-executing the operation (TTL: 300 seconds).
- **List tools** (13 tools): accept an optional `output_format` parameter. Use `"json"` (default) for the standard structured response or `"markdown"` for a compact table suited to quick scanning.

### Execution Tools

- `execute_policy_now`: `policy_id` (required), `action` (remediateAll or remediateServer), `device_id` (optional, required for remediateServer)
- `execute_device_command`: `device_id` (required), `command_type` (scan, get_os, refresh, patch, patch_all, patch_specific, reboot), `patch_names` (optional, required for patch_specific)
- `apply_policy_changes`: accepts one or more `operations` where each entry contains `action` (`create`/`update`) and a policy payload. The helper accepts convenient shorthands (`filter_name`, `filter_names`), converts friendly `schedule` blocks, and enforces Automox-friendly defaults (e.g., inclusion of `id` during updates).
- `policy_run_results`: `policy_uuid`, `exec_token`, and optional filters (`org_uuid`, `result_status`, `device_name`, pagination arguments).

---

## Enterprise Features

The following features are built into the server and require no additional configuration unless noted.

### Correlation IDs

Every tool call is automatically assigned a UUID4 correlation ID via FastMCP middleware. The ID flows through to the response `metadata` field and is forwarded to the Automox API as the `X-Correlation-ID` request header. The middleware also logs the tool name, final status, and wall-clock latency at `INFO` level.

No configuration required. Correlation IDs appear in response metadata automatically.

### Token Budget Estimation

The server warns when a response is estimated to exceed 4000 tokens and automatically truncates list data to keep responses within budget. The threshold is configurable:

```bash
AUTOMOX_MCP_TOKEN_BUDGET=4000   # default; set higher to allow larger responses
```

### Idempotency Keys

All 21 idempotent write tools accept an optional `request_id` parameter (any UUID string). Submitting the same `request_id` within 300 seconds returns the cached response without re-executing the underlying API call. The cache holds up to 1000 entries and is stored in-memory (cleared on server restart).

```
# Example: safe to retry -- second call returns the cached result
execute_device_command(device_id=123, command_type="reboot", request_id="550e8400-e29b-41d4-a716-446655440000")
```

### Markdown Table Output

Thirteen list tools accept an optional `output_format` parameter:
- `"json"` (default) -- standard structured JSON response
- `"markdown"` -- compact Markdown table suitable for quick scanning in chat interfaces

```
list_devices(output_format="markdown")
```

### Capability Discovery

The `discover_capabilities` meta-tool returns all available tools organized by domain. It is always available regardless of `AUTOMOX_MCP_MODULES` and is useful for discovering what the server can do without consulting documentation.

### Endpoint Authentication

For HTTP/SSE deployments, the server supports two authentication strategies (first match wins):

**Option 1: Static API Keys** — Simple bearer tokens for trusted clients:

```bash
# Generate a key
automox-mcp --generate-key

# Configure via env var (comma-separated, optional label prefix)
AUTOMOX_MCP_API_KEYS="alice:amx_mcp_abc123,bob:amx_mcp_def456"

# Or via key file (one per line, supports # comments and label:key format)
AUTOMOX_MCP_API_KEY_FILE=/etc/automox-mcp/keys.txt
```

**Option 2: OAuth 2.1 / JWT** — Validate JWTs from an external IdP (Keycloak, Auth0, Azure AD, Okta):

```bash
AUTOMOX_MCP_OAUTH_ISSUER="https://auth.example.com/realms/main"
AUTOMOX_MCP_OAUTH_JWKS_URI="https://auth.example.com/realms/main/protocol/openid-connect/certs"
AUTOMOX_MCP_OAUTH_AUDIENCE="https://mcp.example.com"
AUTOMOX_MCP_OAUTH_SERVER_URL="https://mcp.example.com"
AUTOMOX_MCP_OAUTH_SCOPES="mcp:tools"          # optional
AUTOMOX_MCP_OAUTH_ALGORITHM="RS256"            # optional, default RS256
```

When `AUTOMOX_MCP_OAUTH_SERVER_URL` is set, the server exposes [RFC 9728](https://datatracker.ietf.org/doc/html/rfc9728) Protected Resource Metadata at `/.well-known/oauth-protected-resource/<path>` and returns proper `WWW-Authenticate` headers on 401/403 responses, enabling MCP clients to discover the authorization server automatically.

Both options are independent of the Automox API key (`AUTOMOX_API_KEY`) and have no effect on stdio transport. See [Deployment Security Guide](deployment-security.md) for full details.

### DNS Rebinding Protection

The server validates `Host` and `Origin` headers on all HTTP/SSE connections to prevent [DNS rebinding attacks](https://en.wikipedia.org/wiki/DNS_rebinding), as required by the MCP transport specification. Enabled by default — the server automatically allows the bound host:port and loopback aliases.

```bash
# Add additional allowed origins (e.g., your web dashboard)
AUTOMOX_MCP_ALLOWED_ORIGINS="https://app.example.com,https://dashboard.example.com"

# Add additional allowed hosts
AUTOMOX_MCP_ALLOWED_HOSTS="proxy.internal:443"

# Disable (NOT recommended for production)
AUTOMOX_MCP_DNS_REBINDING_PROTECTION=false
```

### Security Response Headers

All HTTP responses automatically include security headers: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'`, `Cache-Control: no-store`, `Referrer-Policy: strict-origin-when-cross-origin`, and `Permissions-Policy`. Always enabled with no opt-out.
