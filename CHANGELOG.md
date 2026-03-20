# Changelog

All notable changes to the Automox MCP Server will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

#### Phase 2: Compound Tools, Inventory & Resources (8 new tools, 4 new resources)

- **Compound Workflows** (3 tools)
  - `get_patch_tuesday_readiness` — Combined pre-patch report + pending approvals + patch policy schedules with per-device severity classification
  - `get_compliance_snapshot` — Combined non-compliant report + device health metrics + policy stats with computed compliance rate
  - `get_device_full_profile` — Device detail + inventory summary + packages + policy assignments in one call with section status tracking and data completeness verification

- **Device Inventory** (2 tools)
  - `get_device_inventory` — Retrieve device inventory via Console API (`/device-details/orgs/{uuid}/devices/{uuid}/inventory`) with category filtering (Hardware, Health, Network, Security, Services, Summary, System, Users)
  - `get_device_inventory_categories` — List available inventory categories for a device (dynamic per device)

- **Policy CRUD** (3 tools)
  - `clone_policy` — Clone an existing policy with optional name and server group overrides; includes fallback ID lookup when API returns empty body
  - `delete_policy` — Permanently delete a policy by ID
  - `policy_compliance_stats` — Per-policy compliance rates from `/policystats` endpoint

- **MCP Resources** (4 new, 9 total)
  - `resource://filters/syntax` — Device filtering reference for search_devices, policy device_filters, and list_devices
  - `resource://patches/categories` — Severity levels, patch_rule options, package fields, and filter pattern syntax
  - `resource://platform/supported-os` — Supported OS matrix (Windows, Mac, Linux) with versions, architectures, shell types, and Linux distros — verified against official Automox docs with source URLs
  - `resource://api/rate-limits` — MCP server rate limiter config, Automox API throttling guidance, and efficiency tips

### Changed

- `summarize_policies` — Policy type detection now checks `policy_type_name` field first; maps `custom` to `worklet` in catalog output
- `summarize_policies` — Inactive policy filtering now uses `status` field when `active`/`enabled`/`is_active` flags are absent
- `summarize_policies` — Preview dict now includes `server_groups`, `schedule_days`, and `schedule_time` fields
- `get_prepatch_report` — Now paginates automatically to fetch all devices; computes per-device severity from CVE data; distinguishes `total_org_devices` from `devices_needing_patches`
- `get_compliance_snapshot` — Health field mappings corrected (`device_status_breakdown`, `check_in_recency_breakdown`)
- `describe_device` — Inventory call now uses proper org UUID resolution instead of relying on device response containing org_uuid
- `search_devices` — Multi-severity filtering now works (parses JSON string arrays); uses list-of-tuples for repeated query params
- `policy_resources.py` — Shell types corrected to Bash only for Mac/Linux, PowerShell only for Windows; added worklet terminology
- `platform_resources.py` — OS lists updated from official Automox docs; package statuses replaced with actual API fields; added source URLs and last_verified dates
- `README.md` — Updated to document all 44 tools, 9 resources, 10 modules, and new compound/inventory capabilities
- API client `get()` method now accepts `Sequence[tuple[str, Any]]` params for repeated query keys

### Fixed

- Policy type detection: `policy_type_name` not checked, causing patch policies to be unrecognized in compound tools
- Inactive policy filtering: `status: "inactive"` policies not filtered when `active`/`enabled` fields absent from API response
- Prepatch report severity: API summary didn't account for all devices; now computed per-device from CVE data
- Prepatch report total: `total` field from API means org device count, not devices needing patches
- Compound tool field mappings: `id` vs `policy_id`, missing schedule/server_groups fields in patch tuesday readiness
- Compliance snapshot: `status_breakdown` and `check_in_recency` empty due to field name mismatch with device health workflow
- Clone policy: API returns empty body; added fallback name-based lookup for new policy ID
- Clone policy: 500 errors from sending read-only fields; expanded `_READ_ONLY_POLICY_FIELDS` set
- Multi-severity search: JSON string array `'["critical", "high"]'` not parsed; added JSON deserialization

#### Phase 1: Core Gaps (18 new tools)

- **Package Management** (2 tools)
  - `list_device_packages` — List software packages installed on a specific device with version, patch status, and severity
  - `search_org_packages` — Search packages across the organization; filter by managed status or packages awaiting installation

- **Group Management** (5 tools)
  - `list_server_groups` — List all server groups with device counts and assigned policies
  - `get_server_group` — Retrieve detailed information for a specific server group
  - `create_server_group` — Create a new server group with name, refresh interval, parent group, policies, and notes
  - `update_server_group` — Update an existing server group
  - `delete_server_group` — Delete a server group permanently

- **Webhook Management** (8 tools)
  - `list_webhook_event_types` — List all 39 available webhook event types with descriptions
  - `list_webhooks` — List all webhook subscriptions for the organization with cursor-based pagination
  - `get_webhook` — Retrieve details for a specific webhook subscription
  - `create_webhook` — Create a new webhook subscription (returns one-time signing secret)
  - `update_webhook` — Partial update of an existing webhook (name, URL, enabled, event types)
  - `delete_webhook` — Delete a webhook subscription permanently
  - `test_webhook` — Send a test delivery to a webhook endpoint
  - `rotate_webhook_secret` — Rotate the signing secret (old secret immediately invalidated)

- **Events** (1 tool)
  - `list_events` — List organization events with filters by policy, device, user, event name, or date range

- **Reports** (2 tools)
  - `prepatch_report` — Pre-patch readiness report showing devices with pending patches
  - `noncompliant_report` — Non-compliant devices report for devices needing attention

#### MCP Resources

- `resource://webhooks/event-types` — Static reference of all 39 webhook event types organized by category (device, policy, worklet, device_group, organization, audit) with descriptions and delivery limits

#### Configuration

- **Read-Only Mode** (`AUTOMOX_MCP_READ_ONLY`) — When set to `true`, all 16 destructive tools are excluded at registration time, leaving 28 read-only tools. Useful for audit, reporting, and monitoring use cases.
- **Modular Architecture** (`AUTOMOX_MCP_MODULES`) — Comma-separated list of module names to selectively load. Available modules: `audit`, `devices`, `policies`, `users`, `groups`, `events`, `reports`, `packages`, `webhooks`, `compound`. Unset loads all modules.

#### Infrastructure

- New workflow modules: `packages.py`, `groups.py`, `events.py`, `reports.py`, `webhooks.py`
- New tool modules: `package_tools.py`, `group_tools.py`, `event_tools.py`, `report_tools.py`, `webhook_tools.py`
- New resource module: `webhook_resources.py`
- Dynamic module registry in `tools/__init__.py` with graceful `ImportError` handling for missing modules
- `is_read_only()` and `get_enabled_modules()` utility functions in `utils/tooling.py`

### Changed

- `tools/__init__.py` — Rewritten with modular architecture; tool modules are now dynamically loaded from a registry using `importlib.import_module`
- `device_tools.py` — `register()` accepts `read_only` keyword; `execute_device_command` gated behind `if not read_only`
- `policy_tools.py` — `register()` accepts `read_only` keyword; `decide_patch_approval`, `apply_policy_changes`, `execute_policy_now` gated behind `if not read_only`
- `account_tools.py` — `register()` accepts `read_only` keyword; `invite_user_to_account`, `remove_user_from_account` gated behind `if not read_only`
- `audit_tools.py` — `register()` accepts `read_only` keyword (no destructive tools to gate)
- `workflows/__init__.py` — Exports all new workflow functions; `__all__` alphabetically sorted
- `resources/__init__.py` — Registers webhook resources
- `server.py` — Updated server instructions to document new capabilities, resources, and webhook guidance; added startup validation for `AUTOMOX_ORG_ID`
- `README.md` — Updated to document all 44 tools, 9 MCP resources, read-only mode, modular architecture, and new configuration options

### Fixed

- `tools/__init__.py` — `groups` module `has_writes` flag corrected from `False` to `True` (group CRUD tools were not gated by read-only mode)
- `webhook_tools.py`, `policy_tools.py` — Fixed `org_id` falsy-value check: `or` operator replaced with explicit `None` comparison to prevent `org_id=0` from being silently overwritten
- `webhook_resources.py` — Corrected webhook event type count from 38 to 39
- `workflows/devices.py` — Fixed parameter shadowing: local `policy_status` variable renamed to `device_policy_status` to avoid shadowing the function parameter `policy_status_filter`
- `workflows/__init__.py` — Fixed `__all__` ordering (`audit_trail_user_activity` before `apply_policy_changes`, `summarize_patch_approvals` before `summarize_policies`)

### Security

- **V-001**: Audit workflow now redacts sensitive fields (`token`, `secret`, `key`, `password`) from API error payloads before surfacing them in tool responses
- **V-002**: Webhook schemas use `uuid.UUID` type for `org_uuid` and `webhook_id` parameters, rejecting malformed/traversal inputs at the Pydantic validation layer
- **V-003**: Webhook `create` and `update` operations enforce HTTPS-only URLs via Pydantic `model_validator`
- **V-004**: Report `limit` parameters (`GetPrepatchReportParams`, `GetNeedsAttentionReportParams`) bounded with `le=500` to prevent unbounded result sets
- **V-005**: HTTP client debug logging no longer includes request parameters, preventing accidental credential exposure in log output
- **V-006**: All 9 tool module `_call()` wrappers now include catch-all exception handling (`except ToolError: raise` + `except Exception` → `ToolError`), preventing raw stack traces from leaking to MCP clients
- **V-007**: `AUTOMOX_ORG_ID` validated as a positive integer at server startup; non-numeric or non-positive values raise `RuntimeError` before any tools are registered
- **V-008**: Policy workflow narrowed 3 broad `except Exception` handlers to `except (AutomoxAPIError, ValueError, TypeError, KeyError)` with structured debug logging

### Optimized

- `webhook_resources.py` — Webhook event types JSON precomputed at module load instead of being rebuilt on every resource request
- `schemas.py`, `group_tools.py` — `policies` parameter typed as `list[int]` (was untyped `list`) for stronger input validation
- `tools/__init__.py` — Replaced `__import__` with `importlib.import_module` for clearer dynamic imports
- `workflows/devices.py` — Early `break` in `list_device_inventory` when limit is reached, avoiding unnecessary iteration
- `workflows/audit.py` — Removed unreachable dead code in `_email_looks_valid`
- `workflows/devices.py` — Simplified `_normalize_status` priority loop: replaced sorted-list iteration with set-based check

## [0.1.0] - 2025-01-01

### Added

- Initial release with 18 tools across 4 domains (devices, policies, account, audit)
- 4 MCP resources (policy quick-start, schema, schedule-syntax, server group list)
- FastMCP 2.0 framework with stdio, HTTP, and SSE transport support
- Rate limiting, error formatting, and org UUID resolution utilities
- Pydantic input validation for all tool parameters
- Python 3.11+ support
