# Changelog

All notable changes to the Automox MCP Server will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.11] - 2026-04-01

### Changed

- Applied `ruff format` to fix formatting in `src/automox_mcp/tools/__init__.py` and `tests/test_prompts.py`

### Fixed

- **MCP Scanner CI failure** — `mcp-scanner` v4.x requires the `stdio` subcommand and `--stdio-arg` (singular, repeatable) instead of `--stdio-args` (which consumed only one token, causing `automox-mcp` to be misinterpreted as a subcommand)
- **MCP Scanner arg ordering** — Moved `--analyzers` and `--format` global options before the `stdio` subcommand where the CLI parser expects them, and changed dummy `AUTOMOX_ORG_ID` from `0` to `1` to pass server validation (positive integer required)
- **Zizmor `superfluous-actions` warning** — Replaced `softprops/action-gh-release` action in `release.yml` with a `gh release create` script step, since the `gh` CLI is pre-installed on GitHub runners
- **4 flaky rate-limit tests failing on fresh CI runners** — Tests now create explicit `AuthRateLimitMiddleware` instances instead of relying on shared module-level state that could carry over between test runs

## [1.0.10] - 2026-04-01

### Changed

- **Upgraded fastmcp from 2.13.0.2 to 3.2.0** — Major version upgrade to resolve 4 CVEs (GHSA-rcfx-77hg-w2wv, CVE-2025-69196, CVE-2025-64340, CVE-2026-27124). Updated internal API usage from `_tool_manager._tools` to `local_provider._components` and `get_tools()` to `list_tools()`. The `_apply_tool_prefix` helper now uses `model_copy()` for immutable tool renaming. Added `_get_tool_names()` public helper for test access to registered tool names.

### Security

- **16 dependency CVEs resolved** — All vulnerabilities flagged by the CI `pip-audit` gate have been fixed via `[tool.uv] constraint-dependencies` pins:

  | Package | Old | New | CVEs |
  |---------|-----|-----|------|
  | authlib | 1.6.5 | 1.6.9 | CVE-2025-68158 |
  | cryptography | 46.0.3 | 46.0.6 | CVE-2026-26007, CVE-2026-34073 |
  | fastmcp | 2.13.0.2 | 3.2.0 | GHSA-rcfx-77hg-w2wv, CVE-2025-69196, CVE-2025-64340, CVE-2026-27124 |
  | jaraco-context | 6.0.1 | 6.1.2 | CVE-2026-23949 |
  | mcp | 1.21.0 | 1.26.0 | CVE-2025-66416 |
  | pygments | 2.19.2 | 2.20.0 | CVE-2026-4539 |
  | pyjwt | 2.10.1 | 2.12.1 | CVE-2026-32597 |
  | python-multipart | 0.0.20 | 0.0.22 | CVE-2026-24486 |
  | requests | 2.32.5 | 2.33.1 | CVE-2026-25645 |
  | urllib3 | 2.5.0 | 2.6.3 | CVE-2025-66418, CVE-2025-66471, CVE-2026-21441 |
  | diskcache | 5.6.3 | removed | CVE-2025-69872 (dropped by fastmcp 3.x) |

## [1.0.9] - 2026-04-01

### Fixed

- **CI coverage gate failure (89.35% < 90%)** — Added 23 tests covering `AuthRateLimitMiddleware` (rate limiting, blocking, cleanup, hard-cap eviction), `_env_flag` helper, missing-Host 400 response, IPv6 host parsing, and `events.py` edge cases (paginated dict responses, `count_only`, non-mapping items, `None` response). Coverage raised from 89.35% to 90.75%.

## [1.0.8] - 2026-04-01

### Fixed

- **E501 line-too-long lint failures in CI** — Reformatted 8 lines across `auth.py`, `schemas.py`, `transport_security.py`, and `workflows/devices.py` that exceeded the 100-character limit, plus applied `ruff format` to 12 files for consistent style.
- **mypy failures in CI when checking test files** — CI ran `mypy .` which checked test stubs/fakes against production type signatures. Added `exclude = ["tests/"]` to mypy config so test files with intentional type mismatches (fake clients, stub servers) are not type-checked. Fixed 3 real src issues: `client.py` `org_id` type annotation, `transport_security.py` `Any` return, and `tooling.py` `Mapping` index assignment.

## [1.0.7] - 2026-03-31

### Fixed

- **OIDC auto-discovery passes discovery URL as JWKS URL** — When `AUTOMOX_MCP_OAUTH_JWKS_URI` is omitted, the server now fetches the OIDC discovery document and extracts the actual `jwks_uri` field. Previously, the `/.well-known/openid-configuration` URL itself was passed to `JWTVerifier`, which expects a JWKS document with a top-level `keys` array — resulting in zero keys found and all tokens rejected (V-172).
- **`AUTOMOX_MCP_OAUTH_JWKS_URI` missing HTTPS validation** — Added HTTPS enforcement for the JWKS URI, consistent with the existing issuer URL check. Fetching JWKS over cleartext HTTP is vulnerable to MITM key substitution (V-173).
- **`AUTOMOX_MCP_OAUTH_PUBLIC_KEY` file path fallthrough** — When the value looks like a file path but the file does not exist, the server now raises a `RuntimeError` at startup instead of silently passing the raw path string as a PEM key literal, which would fail opaquely at token verification time (V-174).
- **Sunday bitmask value incorrect in schedule reference resource** — The `bitmask_values` JSON resource listed Sunday as `1` instead of `128`. The text resource and `policy_crud.py` already used the correct value (V-175).
- **`schedule_weeks_of_month` Pydantic constraint rejects valid values** — Changed `le=30` to `le=62`. The auto-default is 62 (all 5 weeks with trailing zero) and the docs specify 1–62 as the valid range, but Pydantic validation rejected values above 30 (V-176).
- **Week-of-month bitmask documentation shows wrong individual values** — Updated from `1=first, 2=second, 4=third, 8=fourth, 16=fifth` to the correct trailing-zero pattern `2=first, 4=second, 8=third, 16=fourth, 32=fifth` matching the code (V-177).
- **`groups.py` crash on null `policies` field** — `len(group.get("policies", []))` returns `None` when the key exists with a null value. Changed to `group.get("policies") or []` (V-178).
- **Rate limiter memory cap only evicts blocked IPs** — Hard cap eviction now also trims `_failures` entries when `_blocked_until` eviction alone is insufficient. Under sustained IP rotation, `_failures` could previously grow past `_MAX_TRACKED_IPS` (V-179).
- **Code block sanitizer misses non-allowlisted language labels** — Fenced code blocks with language labels not in the shell allowlist (e.g., ` ```javascript `, ` ```ruby `) now match the catch-all pattern. Previously, only shell-like labels and unlabeled blocks were stripped (V-180).

### Security

- **V-172**: OIDC discovery document parsed to extract actual JWKS URI.
- **V-173**: HTTPS enforcement on JWKS URI prevents cleartext key fetch.
- **V-174**: Fail-fast on missing public key file prevents opaque auth failures.
- **V-175**: Correct Sunday bitmask in schedule reference resource.
- **V-176**: `schedule_weeks_of_month` validation accepts full valid range (0–62).
- **V-177**: Week-of-month bitmask documentation aligned with trailing-zero pattern.
- **V-178**: Null-safe policy count in group summaries.
- **V-179**: Rate limiter eviction covers both `_blocked_until` and `_failures` dicts.
- **V-180**: Code block sanitizer strips all fenced blocks regardless of language label.

## [1.0.6] - 2026-03-30

### Fixed

- **Blocking DNS resolution freezes async event loop** — Webhook URL validation now runs DNS resolution in a `ThreadPoolExecutor` instead of blocking the event loop for up to 3 seconds. All concurrent tool calls were stalled during hostname resolution (V-165).
- **Webhook `ListWebhooksParams` missing input bounds** — Added `ge=1, le=500` on `limit` and `max_length=2000` on `cursor`, consistent with other paginated schemas (V-166).
- **`_deep_merge_dicts` unbounded recursion** — Policy update merge now caps recursion at 10 levels, preventing stack overflow from adversarially nested configuration payloads (V-167).
- **Device UUID from API used in URL path without format validation** — `_resolve_device_uuid` now validates the API-returned UUID against `[a-fA-F0-9\-]+` before interpolation into URL paths, preventing path injection if the upstream API returned a malformed value (V-168).
- **Presigned `download_url` tokens exposed to LLM** — Data extract responses now return `has_download_url: true` instead of the raw URL. Presigned cloud storage URLs contain embedded auth credentials (`X-Amz-Security-Token`, `sig=`) that should not be cached in LLM context (V-169).
- **Idempotency cache TOCTOU allows duplicate writes** — Replaced the non-atomic check-then-execute-then-store pattern with an atomic `reserve()` method that inserts an in-flight sentinel during the check. Concurrent duplicate `request_id` values now return a duplicate marker instead of both executing (V-170).
- **`account_uuid` not format-validated before URL path interpolation** — `AutomoxClient` now validates `AUTOMOX_ACCOUNT_UUID` against `[a-zA-Z0-9\-]+` at construction time, preventing path injection via malformed environment variables (V-171).

### Security

- **V-165**: Non-blocking DNS resolution in webhook SSRF validation (ThreadPoolExecutor).
- **V-166**: Webhook cursor/limit input bounds consistent with other schemas.
- **V-167**: Policy merge recursion depth limit prevents stack overflow DoS.
- **V-168**: Device UUID format validation before URL path interpolation.
- **V-169**: Presigned URL redaction in data extract responses.
- **V-170**: Atomic idempotency reservation prevents duplicate write operations.
- **V-171**: Account UUID format validation at client construction.

## [1.0.5] - 2026-03-30

### Fixed

- **HMAC+JWKS key confusion attack** — JWT algorithm validation now rejects HMAC algorithms when a JWKS URI is configured (not just when a public key is set). An attacker who set `AUTOMOX_MCP_OAUTH_ALGORITHM=HS256` with a JWKS URI could use the JWKS-fetched public key as the HMAC shared secret (V-150).
- **Sanitization bypass for strings in lists** — `sanitize_dict()` now sanitizes bare strings inside list structures. Previously, a payload like `{"tags": ["SYSTEM: override instructions"]}` would pass the instruction prefix through to the LLM unsanitized (V-151).
- **Unsanitized user input reflected in error message** — `normalize_policy_operations_input` now sanitizes the `operation` field value before embedding it in the error message sent to the LLM. A crafted value could inject prompt instructions via the error path (V-152).
- **Unbounded memory growth in auth rate limiter** — `AuthRateLimitMiddleware` now periodically cleans up expired `_blocked_until` entries and empty `_failures` deques, with a hard cap of 10K tracked IPs. Previously, IP rotation attacks could exhaust server memory over time (V-153).
- **IPv6 bare-address host parsing misidentified host:port** — `_parse_host_port` now detects bare IPv6 addresses (2+ colons) instead of splitting on the last colon. `_add_host_variants` now generates bracketed `[::1]:8000` format matching what HTTP clients send (V-154).
- **Wildcard port matching accepted invalid ports** — Port range validation (1-65535) added to wildcard matching in both `_host_matches` and `_origin_matches` (V-155).
- **org_uuid from API response cached without validation** — `resolve_org_uuid` now validates UUID format via `UUID()` when caching values from the `/orgs` API response, matching the existing explicit_uuid path. A compromised API response could inject path traversal characters (V-156).
- **`require_org_id` treats org_id=0 as missing** — Changed from truthiness check to explicit `None` check. `org_id=0` was silently discarded (V-157).
- **`GetWisItemParams.item_id` missing validation** — Added `max_length=200` and alphanumeric pattern constraint, matching the existing `extract_id` field. Unvalidated strings were interpolated into URL paths (V-158).
- **Unbounded dict payloads forwarded to API** — `CreateDataExtractParams.extract_data`, `UploadActionSetParams.action_set_data`, and `AdvancedDeviceSearchParams.query` now enforce a 50KB size limit via model validators (V-159).
- **Cursor fields missing length constraints** — Added `max_length=2000` to cursor fields in `AuditTrailEventsParams` and `AuditEventsOcsfParams` (V-160).
- **Webhook name/URL/event_types missing length constraints** — Added `max_length` to `CreateWebhookParams` and `UpdateWebhookParams` fields (V-161).
- **Blocking DNS resolution in webhook validation** — `_validate_webhook_url` now sets a 3-second socket timeout to limit event loop blockage during synchronous DNS resolution in the Pydantic validator (V-162).
- **Prompt injection via MCP prompt parameters** — All prompt templates now validate and sanitize user-supplied parameters (`policy_id`, `device_id`, `group_name`) before interpolation (V-163).
- **Destructive actions without confirmation gates** — `investigate_noncompliant_device` and `triage_failed_policy_run` prompts now instruct the LLM to present a remediation plan and wait for user confirmation before executing commands like reboot or patch_all (V-164).
- **`report_days` parameter ignored** — `summarize_policy_execution_history` now generates a `start_time` filter from `report_days`, actually filtering the API query by date range instead of only including the value in response metadata.

### Security

- **V-150**: HMAC+JWKS key confusion attack prevention in JWT auth configuration.
- **V-151**: Bare strings in list structures now pass through `sanitize_for_llm()`.
- **V-152**: User-controlled values sanitized before reflection in error messages.
- **V-153**: Auth rate limiter periodic cleanup with 10K IP hard cap prevents memory exhaustion DoS.
- **V-154**: IPv6 addresses correctly parsed and bracketed in DNS rebinding protection.
- **V-155**: Wildcard port validation enforces TCP port range (1-65535).
- **V-156**: UUID format validation on API-derived org_uuid before caching.
- **V-158**: WIS item_id constrained to alphanumeric pattern with 200-char limit.
- **V-159**: Passthrough dict fields (extract_data, action_set_data, query) capped at 50KB.
- **V-162**: DNS resolution timeout prevents event loop starvation in webhook validation.
- **V-163**: MCP prompt parameters validated/sanitized to prevent prompt injection.
- **V-164**: Destructive prompt workflows require explicit user confirmation.

## [1.0.4] - 2026-03-30

### Fixed

- **URL path injection via unvalidated string IDs** — `policy_uuid`, `exec_token`, `device_uuid` in V2 schemas now use `UUID` type validation, matching the existing V1 schemas. Previously, bare `str` fields were interpolated directly into API URL paths without format validation. `extract_id` now uses a pattern constraint.
- **Trailing-dot FQDN bypasses cloud metadata blocklist** — Webhook URL validation now strips trailing dots from hostnames before blocklist comparison. `metadata.google.internal.` (a valid FQDN) previously bypassed both exact-match and `.endswith(".internal")` checks.
- **DNS resolution failure silently allows webhook URLs** — Webhook URL validation now rejects hostnames that cannot be resolved via DNS (fail-closed) instead of allowing them through (fail-open).
- **Token budget truncation mutates idempotency cache** — `_apply_token_budget` now deep-copies the response dict before truncation, preventing in-place mutation of cached entries that would cause progressive data loss on idempotent replays.
- **Token budget truncation only targets first list in Mapping data** — Now truncates ALL oversized lists within a Mapping payload, not just the first one found.
- **`resolve_org_uuid` conflates account UUID with org UUID** — Account UUID fallback no longer caches the value as `client.org_uuid`. Previously, tools using `allow_account_uuid=True` could poison the cache, causing subsequent tools that require a real org UUID to receive an account UUID instead.
- **Async race condition on `client.org_uuid`** — `resolve_org_uuid` now uses an asyncio lock to prevent concurrent mutations when multiple tool calls are in-flight (e.g., compound workflows using `asyncio.gather`).
- **Case-sensitive Host/Origin header matching** — DNS rebinding protection now normalizes headers to lowercase before comparison per RFC 4343. Previously, `Host: LOCALHOST:8000` would be rejected.
- **WebSocket connections bypass DNS rebinding protection** — The middleware now validates `scope["type"] == "websocket"` in addition to `"http"`.
- **Host wildcard port matching accepts non-numeric ports** — `_host_matches` now validates that the port portion is numeric when matching `host:*` patterns, consistent with `_origin_matches`.
- **Log injection via tool name** — Correlation middleware now sanitizes tool names by stripping newline/carriage return/tab characters, preventing injected log lines that could forge audit trails or mislead SIEM systems.
- **`_redact_sensitive_fields` unbounded recursion** — Added depth limit of 20 to prevent stack overflow on deeply nested error payloads.
- **`normalize_status` unbounded recursion** — Added depth limit of 20 to prevent stack overflow on deeply nested status structures.
- **`_estimate_tokens` returns 0 on serialization failure** — Now falls back to `repr()` length estimation, then to the default budget value, instead of returning 0 which would bypass budget enforcement entirely.
- **`/servers` API response not handled when paginated dict** — `list_device_inventory`, `search_devices`, and `summarize_device_health` now handle both bare list and `{"data": [...]}` dict response formats from the `/servers` endpoint.
- **`clone_policy` unbounded fetch** — The fallback clone ID lookup now uses `limit=250` instead of fetching all policies without pagination.
- **Ambiguous numeric day mapping** — `_normalize_schedule_days_input` now only accepts 0-6 (Sunday=0 through Saturday=6) instead of the ambiguous 0-6 and 1-7 dual range that silently produced different results depending on caller convention.
- **`_normalize_filters` always wraps in wildcards** — Added `exact` parameter to allow callers to opt out of the automatic `*...*` wrapping for exact-match filters.
- **Unused `_has_writes` variable in tool registration** — Replaced with `_` discard variable to remove dead code.
- **Idempotency cache expired entries not proactively cleaned** — `get()` now calls `_evict_expired()` on every access, not just during `put()` operations.

### Security

- **V-132**: UUID type validation on path-interpolated parameters (policy_uuid, exec_token, device_uuid, extract_id) prevents URL path injection.
- **V-133**: HTML tag and script stripping in sanitizer — `sanitize_for_llm` now removes `<script>` blocks, event handler attributes (`onerror`, `onclick`, etc.), `javascript:`/`data:` URIs, and all HTML tags. Previously only Markdown syntax was stripped.
- **V-134**: Instruction prefix stripping default-on for unknown fields — Fields not in the explicit preserve-list (`hostname`, `name`, `tags`, etc.) now have instruction prefixes stripped by default. Expanded the strip-field list to include `comments`, `reason`, `summary`, `output`, `body`, `content`, `text`, `value`, `result`, `response`, `log`, `error`.
- **V-135**: JWT public key file world-writable rejection — `_create_jwt_auth` now raises `RuntimeError` instead of logging a warning when the JWT public key file is world-writable. An attacker with write access could replace the key to forge tokens and bypass authentication entirely.
- **V-136**: JWT audience claim now required — `AUTOMOX_MCP_OAUTH_AUDIENCE` is mandatory when JWT authentication is enabled. Without audience binding, any valid token from the configured issuer would be accepted, enabling cross-service token reuse.
- **V-137**: Non-HTTPS OAuth issuer rejected — `AUTOMOX_MCP_OAUTH_ISSUER` must use `https://`. JWKS discovery over cleartext HTTP is vulnerable to MITM key substitution.
- **V-138**: JWT algorithm validation — Rejects HMAC algorithms when a public key is configured (algorithm confusion attack), and validates the algorithm against a known allowlist.
- **V-139**: API key file `stat()` failure no longer bypasses permission check — Previously, any `OSError` from `stat()` was silently swallowed, proceeding to read the file without permission validation.
- **V-140**: Authentication rate limiting — New `AuthRateLimitMiddleware` blocks client IPs after 10 failed authentication attempts (401/403) within 60 seconds, with a 5-minute block period. Mitigates brute-force attacks on static API keys and JWT tokens.
- **V-141**: HSTS header added — All HTTP responses now include `Strict-Transport-Security: max-age=63072000; includeSubDomains`.
- **V-142**: Fenced code block regex supports 4+ backtick delimiters — Previously, code blocks using ```````` as delimiters bypassed sanitization.
- **V-143**: OIDC discovery uses standard path — Auto-derived JWKS URI now uses `/.well-known/openid-configuration` instead of the non-standard `/.well-known/jwks.json`.
- **V-144**: Minimum API key length warning — Keys shorter than 16 characters trigger a startup warning recommending `--generate-key`.
- **V-145**: `is_auth_configured()` handles permission errors — No longer crashes the server when the key file exists but has incorrect permissions; returns `True` (auth is intended, just misconfigured).
- **V-146**: API key not exposed via `repr()` — `AutomoxClient` now defines `__repr__` and `__slots__` to prevent accidental API key exposure in debug output, logging, or exception handlers.
- **V-147**: Webhook SSRF checks for multicast/unspecified IPs — `_validate_webhook_url` now rejects `is_multicast` and `is_unspecified` addresses.
- **V-148**: Input validation bounds on 20+ schema fields — Added `max_length`, `pattern`, `ge`/`le` constraints to `PolicyRunsV2Params`, `AuditEventsOcsfParams`, `DeviceSearchTypeaheadParams`, `SearchWisParams`, `RunDetailParams`, `GetEventsParams`, `CreateServerGroupParams`, `UpdateServerGroupParams`, and `PolicyDefinition` (bitmask fields, scheduled_timezone).
- **V-149**: Operations list bounded to 50 — `PolicyChangeRequestParams.operations` now has `max_length=50` to prevent resource exhaustion via unbounded batch operations.
- **S-006**: SSRF DNS fail-closed — Webhook URL validation now rejects unresolvable hostnames instead of allowing them through. Documented TOCTOU risk (S-001) remains.

## [1.0.3] - 2026-03-30

### Fixed

- **Wrong user resolved in audit actor lookup** — `_lookup_actor_from_hints` no longer assigns a minimum score of 5 to zero-match candidates. Previously, when no candidate matched any criteria (email, name token), an arbitrary API result was selected as the "best match" and used to filter audit events for the wrong user.
- **IPv6 DNS rebinding protection rejects all requests** — Allowed hosts now include bracket-formatted IPv6 variants (e.g., `[::1]:8000`) matching what HTTP clients actually send in Host headers. Previously, the bare `::1:8000` format never matched.
- **Wildcard bind (`0.0.0.0`/`::`) breaks DNS rebinding protection** — Loopback aliases (`127.0.0.1`, `localhost`, `::1`) are now auto-added when binding to wildcard addresses. Previously, only the literal `0.0.0.0:8000` was allowed, which no real client sends.
- **IPv6 wildcard-port patterns never match** — `_host_matches` now uses proper host:port parsing that handles IPv6 bracket syntax. Origin wildcard matching now validates the suffix is a numeric port to prevent prefix-confusion bypasses.
- **Tag search iterates characters on string tags** — `search_devices` now excludes `str`/`bytes` from the `Sequence` isinstance check when processing device tags. Previously, a single tag string like `"production"` was iterated character-by-character.
- **Audit response `Sequence` check matches strings** — Added `str`/`bytes` guards to two `isinstance(response, Sequence)` checks in `audit.py` (lines 216, 677). Previously, a string API response would be iterated character-by-character, silently producing empty results. Consistent with the existing guard in `audit_v2.py`.
- **Events dict response without `data` treated as event** — `list_events` no longer wraps a Mapping response without a `"data"` key as a single event entry. Returns an empty list instead of producing a garbage entry with all-None fields.
- **`total_events` reports page count instead of API total** — `list_events` now reads the `total`/`totalCount` field from the API response envelope when available, consistent with `packages.py`.
- **`maybe_format_markdown` discards non-list data** — When `output_format="markdown"` and the data isn't a dict containing a list, the function now returns the original result instead of replacing all data with `"_No data_"`.
- **Token budget truncation skips top-level list data** — `_apply_token_budget` now truncates when `data` is itself a list (common from `extract_list`), not just when lists are nested inside dicts. Also uses safe reassignment instead of in-place slice mutation.
- **Malformed latency crashes JSON log formatter** — `JSONFormatter.format()` now catches `ValueError`/`TypeError` from malformed latency strings instead of propagating the exception, which could lose log entries.
- **`summarize_device_health` only fetches first 500 devices** — Now paginates up to 20 pages instead of making a single API call. Previously, health statistics for organizations with >500 devices only reflected a partial subset.
- **`severity_breakdown` counts only status-filtered items** — `summarize_patch_approvals` now counts severity for all approval items before applying the status filter, making `severity_breakdown` and `status_breakdown` cover the same population.
- **`_decode_schedule_days_bitmask` ignores unused bit 0** — Bitmask is now masked with `& 0xFE` before processing. Previously, any odd bitmask value produced wrong day counts and missed pattern matches (e.g., 63 not recognized as weekdays).
- **`AutomoxRateLimitError` discards 429 response payload** — Now extracts the response payload (including `Retry-After` info) before raising, consistent with how other HTTP errors are handled.
- **`summarize_policies` uses output limit as API page size** — When client-side filtering is active (e.g., `include_inactive=False`), the API fetch limit is now `min(limit * 3, 500)` to avoid excessive API calls. Consistent with `search_devices` and `list_device_inventory`.
- **Policy windows date query param embedded in URL path** — `get_group_scheduled_windows` and `get_device_scheduled_windows` now pass the `date` parameter via httpx's `params` dict instead of manually appending to the URL path, ensuring proper URL encoding.
- **Audit `params` variable shadowed by `parse_qs`** — Renamed to `qs_params` to avoid overwriting the original request parameters dict with a `dict[str, list[str]]`.

### Security

- **V-129**: Zero-match actor resolution prevented — audit trail no longer resolves to an arbitrary user when no candidates match search criteria.
- **V-130**: IPv6 DNS rebinding protection now functional — bracket-formatted Host headers are correctly validated.
- **V-131**: Origin wildcard port validation — wildcard port matching now rejects non-numeric suffixes to prevent prefix-confusion bypasses.

## [1.0.2] - 2026-03-30

### Fixed

- **Report pagination silently stops after first page** — `get_prepatch_report` and `get_noncompliant_report` now correctly paginate when the API response omits the `total` field. Previously, `total or 0` evaluated to `0`, making `len(device_list) >= 0` always true and breaking the loop after one page.
- **`AUTOMOX_ORG_ID` whitespace crash** — `AutomoxClient` now strips whitespace from `AUTOMOX_ORG_ID` before parsing, matching the existing behavior for `AUTOMOX_API_KEY` and `AUTOMOX_ACCOUNT_UUID`. Previously, a whitespace-only value caused an unhandled `ValueError`.
- **Zero/negative token budget accepted** — `AUTOMOX_MCP_TOKEN_BUDGET` now falls back to the default (4000) when set to zero or a negative value, preventing every response from triggering truncation warnings.

## [1.0.1] - 2026-03-30

### Fixed

- **Events workflow paginated response handling** — `list_events` now correctly extracts the `data` list from paginated dict responses (`{"data": [...], "total": N}`) instead of wrapping the entire response dict as a single event.
- **Missing `.strip()` on `account_uuid`** — `AutomoxClient` now strips whitespace from `AUTOMOX_ACCOUNT_UUID`, matching the existing behavior for `AUTOMOX_API_KEY` and `AUTOMOX_ORG_UUID`. Prevents opaque API failures from trailing whitespace in env vars.
- **Over-broad sensitive field redaction** — Replaced `"key"` and `"auth"` in `SENSITIVE_KEYWORDS` with specific terms (`"api_key"`, `"api-key"`, `"apikey"`) to prevent legitimate fields like `registry_key`, `author`, and `primary_key_id` from being silently redacted in error payloads.
- **Webhook partial update uses PATCH** — `update_webhook` now uses `client.patch()` instead of `client.put()` for partial updates, preventing the API from resetting omitted fields when treating PUT as a full replacement.
- **`has_more` pagination flag after auto-pagination** — `summarize_policies` no longer falsely reports `has_more=True` when `page=None` auto-pagination has already fetched all pages.
- **`total_packages` reports actual total** — `list_device_packages` and `search_org_packages` now extract the true total count from paginated API responses instead of reporting only the current page length.
- **Top failures sorted by failure rate** — `summarize_policy_activity` now sorts top failing policies by `failure_rate` (then `failed_runs`) instead of raw `failed_runs` count, so a policy with 4/5 failures correctly ranks above one with 5/1000.
- **`AUTOMOX_ORG_ID` no longer required at startup** — `_validate_env` now treats `AUTOMOX_ORG_ID` as optional (validated when present). Tools that need org context still require it at call time, but the server can start without it.
- **Inconsistent `_env_flag` semantics** — `transport_security.py` now uses explicit true/false matching with default fallback, consistent with `__init__.py`. Unrecognized values like typos now return the default instead of silently evaluating to `True`.
- **JWT public key file permission check** — `auth.py` now warns when the JWT public key file is world-writable, matching the existing permission check pattern for API key files.
- **Token budget `budget=0` handling** — `_apply_token_budget` now uses `budget if budget is not None else default` instead of `budget or default`, correctly handling explicit zero values.

### Added

- **Pydantic validation for 16 tools** — Added `params_model` schemas for all tools in `policy_history_tools` (6), `audit_v2_tools` (1), `device_search_tools` (3 with params), and `compound_tools` (3). User input now passes through `ForbidExtraModel` validation with type coercion, range constraints, and extra-field rejection.
- **Pagination support for 7 workflow functions** — Added `page`/`limit` parameters to `list_data_extracts`, `list_remediation_action_sets`, `get_action_set_actions`, `get_action_set_issues`, `get_action_set_solutions`, `search_worklet_catalog`, and `list_org_api_keys`. Previously these functions only returned the API's default first page.
- **Multi-page fetch for client-side filtered queries** — `list_device_inventory` and `search_devices` now fetch additional pages when client-side filters (hostname, IP, tag, policy_status, managed) reduce results below the requested limit, up to 20 pages or 500 items per page.
- **`StubClient.patch()` method** — Test fixture `StubClient` now supports `patch_responses` for testing PATCH-based workflows.

## [1.0.0] - 2026-03-29

### Refactored

#### Code Review Cleanup

- **Consolidated `_call` helpers** — Replaced 17 duplicated `_call` / `_call_workflow` / `_call_with_org_uuid` error-handling envelopes across all tool modules with a single `call_tool_workflow()` in `utils/tooling.py`. All org-resolution strategies (mixin detection, `inject_org_id`, `org_uuid_field`) are handled via keyword arguments (~500 lines removed).
- **Deduplicated `_extract_list`** — Three identical implementations in `device_search.py`, `vuln_sync.py`, and `policy_history.py` replaced with a shared `extract_list()` in `utils/response.py`.
- **Deduplicated `_normalize_status`** — Two implementations (simple in `policy.py`, comprehensive in `devices.py`) unified into a single `normalize_status()` in `utils/response.py`. The comprehensive version (handles Mapping, Sequence, and string inputs) serves both use cases.
- **Extracted `require_org_id` helper** — Replaced 17 instances of the 3-line `resolved_org_id = org_id or client.org_id` / `if not resolved_org_id` boilerplate across 5 workflow files with a shared `require_org_id()` in `utils/response.py`.
- **Removed orphaned schemas** — Deleted ~40 unused schema classes (~305 lines) from `schemas.py` that were left over from the earlier full-API-wrapper design (e.g., `ListZonesParams`, `GetAccountParams`, `ListDevicesParams`, `AccountIdMixin`, `PaginationMixin`, `MCPError`, `ToolResult`).
- **Parallelized `describe_device`** — The three independent supplementary API calls (packages, inventory, queue) now run concurrently via `asyncio.gather` instead of sequentially. Extracted `_build_device_core()` helper for the ~60-line field-by-field core assembly, reducing `describe_device` from 264 to ~200 lines.
- **JWT audience startup warning** — `auth.py` now logs a warning when `AUTOMOX_MCP_OAUTH_AUDIENCE` is not set, alerting operators that JWT validation will accept tokens regardless of audience.
- **Smoke test docstring** — Updated `tests/smoke_production.py` module docstring to explicitly note the `execute_device_command` write operation (scan/GetOS) and its idempotent nature.

### Added

#### Phase 6: MCP Security Best Practices

- **DNS rebinding protection** (V-120) — `DNSRebindingProtectionMiddleware` validates `Host` and `Origin` headers on all HTTP/SSE connections per the MCP transport specification. Returns `421 Misdirected Request` for invalid Host headers and `403 Forbidden` for invalid Origins. Supports wildcard port patterns. Enabled by default; configurable via `AUTOMOX_MCP_ALLOWED_ORIGINS`, `AUTOMOX_MCP_ALLOWED_HOSTS`, and `AUTOMOX_MCP_DNS_REBINDING_PROTECTION`.
- **Security response headers** (V-121) — `SecurityHeadersMiddleware` injects `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'`, `Cache-Control: no-store`, `Referrer-Policy: strict-origin-when-cross-origin`, and `Permissions-Policy` on all HTTP responses. Always enabled on HTTP/SSE transports.
- **OAuth 2.1 / JWT authentication** (V-122) — Validate JWTs from external authorization servers (Keycloak, Auth0, Azure AD, Okta) with audience binding, issuer validation, and automatic JWKS key rotation via FastMCP's `JWTVerifier`. When `AUTOMOX_MCP_OAUTH_SERVER_URL` is set, wraps with `RemoteAuthProvider` to serve RFC 9728 Protected Resource Metadata at `/.well-known/oauth-protected-resource/<path>` and returns proper `WWW-Authenticate` headers with `resource_metadata` URLs on 401/403 responses. Configure via `AUTOMOX_MCP_OAUTH_ISSUER`, `AUTOMOX_MCP_OAUTH_JWKS_URI`, `AUTOMOX_MCP_OAUTH_AUDIENCE`, `AUTOMOX_MCP_OAUTH_SERVER_URL`, `AUTOMOX_MCP_OAUTH_SCOPES`, `AUTOMOX_MCP_OAUTH_ALGORITHM`.
- **New module**: `transport_security.py` — ASGI middleware for DNS rebinding protection and security response headers, with `build_transport_security_middleware()` factory that auto-configures from server bind address and environment variables.

#### Policy Windows (9 tools)

- **New module**: `policy_windows` — 9 tools (6 read, 3 write) for managing maintenance/exclusion windows via the Policy Windows API.
  - `search_policy_windows` — Search/list windows with filtering by group, status, recurrence; pagination support.
  - `get_policy_window` — Get window details by UUID.
  - `check_group_exclusion_status` — Check if groups are in an active exclusion window (per-group boolean).
  - `check_window_active` — Check if a specific window is currently active.
  - `get_group_scheduled_windows` — Upcoming maintenance periods for a server group.
  - `get_device_scheduled_windows` — Upcoming maintenance periods for a device.
  - `create_policy_window` — Create a maintenance/exclusion window with RFC 5545 RRULE scheduling.
  - `update_policy_window` — Update a window (partial update, `dtstart` required).
  - `delete_policy_window` — Delete a window permanently.

### Security

- **V-120**: DNS rebinding protection via Origin/Host header validation on all HTTP/SSE connections. Implements the MCP transport specification requirement: "Servers MUST validate the Origin header on all incoming connections to prevent DNS rebinding attacks."
- **V-121**: HTTP security response headers on all HTTP/SSE responses (defence-in-depth). Prevents clickjacking (`frame-ancestors 'none'`), MIME sniffing (`nosniff`), and caching of sensitive responses (`no-store`).
- **V-122**: OAuth 2.1 / JWT authentication with RFC 9728 Protected Resource Metadata. Prevents token passthrough via audience binding (`AUTOMOX_MCP_OAUTH_AUDIENCE`). Implements the MCP authorization specification requirements for token audience validation and protected resource metadata.
- **V-123**: Reject requests with missing `Host` header in DNS rebinding middleware (returns 400). Prevents bypass of DNS rebinding protection through misconfigured proxies or malformed requests.
- **V-124**: Sanitize `ValidationError`/`ValueError` messages before raising `ToolError` in the shared `call_tool_workflow()` helper. Prevents Pydantic validation errors from echoing attacker-controlled input values to the LLM.
- **V-125**: Warn at startup when `AUTOMOX_MCP_OAUTH_ISSUER` does not use HTTPS, as JWKS key discovery over cleartext HTTP is vulnerable to MITM attacks.
- **V-126**: Best-effort DNS resolution check in webhook URL validation. Hostnames that resolve to private, loopback, or link-local addresses are now rejected (defense-in-depth against SSRF via DNS rebinding).
- **V-127**: Refuse to load world-readable API key files (upgraded from warning to `RuntimeError`). Group-readable files still produce a warning.
- **V-128**: Added `Literal`, `UUID`, pattern, and bounds constraints to all policy windows tool parameters (pagination size capped at 500, dates validated against ISO 8601, RRULE validated for RFC 5545 prefix).

### Changed

- `auth.py` — Refactored into three provider factories (`_create_static_auth`, `_create_jwt_auth`, `create_auth_provider`) with priority chain: static keys > JWT/OIDC > none. `is_auth_configured()` now also checks for `AUTOMOX_MCP_OAUTH_ISSUER`. Renamed `_env_list` to public `env_list` for cross-module use.
- `__init__.py` — HTTP/SSE transport startup now injects transport security middleware (DNS rebinding + security headers) automatically.
- `SECURITY.md` — Added V-120 through V-128 to threat model and security features table. Added MCP specification security references.
- `docs/deployment-security.md` — New sections for OAuth/JWT auth, DNS rebinding protection, and security headers. Updated recommendations table and pre-production checklist.
- `docs/tool-reference.md` — Enterprise Features section updated with OAuth/JWT auth, DNS rebinding protection, and security headers documentation.
- `README.md` — Configuration table expanded with 8 new env vars. Endpoint Authentication section rewritten for dual static/JWT support. Security highlights updated to 41 items (V-001 through V-128).

#### Phase 5: Hardening & Quality

- **Unicode normalization in sanitizer** (V-108a) — `sanitize_for_llm()` now applies NFKC normalization and strips zero-width/invisible characters before pattern matching, defeating homoglyph bypass attacks (Cyrillic lookalikes, full-width characters, zero-width joiners).
- **Reference-style markdown stripping** (V-117) — Sanitizer now catches `![alt][ref]`, `[text][ref]`, and `[ref]: url` patterns in addition to inline markdown syntax.
- **Unlabeled code block removal** (V-119) — Fenced code blocks without a language label are now stripped, closing a gap where only labelled shell/script blocks were removed.
- **Key file permission check** (V-118) — `AUTOMOX_MCP_API_KEY_FILE` now warns at startup if the file is group- or world-readable, recommending `chmod 600`.
- **Expanded cloud metadata blocklist** (V-114) — Webhook URL validator now blocks Azure (`metadata.azure.com`, `management.azure.com`), Oracle Cloud (`metadata.oraclecloud.com`), and generic (`instance-data`, `*.internal`) metadata endpoints alongside existing Google entries.
- **Canonical sensitive keywords** — `SENSITIVE_KEYWORDS` tuple promoted to public API in `utils/tooling.py`; `audit.py` now imports it instead of maintaining a duplicate definition.

#### Phase 4: MCP Endpoint Authentication

- **Built-in Bearer-token authentication** (V-108) for HTTP/SSE transports via `AUTOMOX_MCP_API_KEYS` (comma-separated env var) or `AUTOMOX_MCP_API_KEY_FILE` (one key per line with `#` comments and `label:key` format). When configured, all HTTP/SSE requests must include `Authorization: Bearer <key>`; unauthenticated requests receive `401 Unauthorized`. No effect on stdio transport.
- **`--generate-key` CLI flag** — Prints a cryptographically secure MCP endpoint API key (`amx_mcp_{32 hex chars}`) and exits.
- **New module**: `auth.py` — Key parsing, loading from env/file sources, `StaticTokenVerifier` integration with FastMCP, and `generate_api_key()` utility.

### Fixed

- **Redundant `set_defaults`** — Removed duplicate `parser.set_defaults(show_banner=...)` in `__init__.py` where the same default was already set via the argument definition.
- **`conftest.py` StubClient default for DELETE** — `_pop()` sentinel logic fixed so DELETE stubs correctly return `None` when no canned response remains, matching the docstring contract.
- **Test prompts incorrectly async** — Six `test_prompts.py` tests were `@pytest.mark.asyncio` / `async def` but never awaited; converted to synchronous.
- **`pytest-asyncio` mode** — Added `asyncio_mode = "auto"` to `pyproject.toml` for automatic async test detection.
- **Unused import** — Removed unused `uuid.UUID` import from `device_search.py`.
- **Ruff/mypy clean** — Resolved 5 ruff errors (import sorting, line length, E402, ASYNC240, F401) and 1 mypy `arg-type` error across source and test files.
- **Missing `uuid` in group summaries** — `list_server_groups` now includes the group `uuid` field returned by the Automox API, enabling policy windows tools to reference groups by UUID.
- **Missing `uuid` in device list summaries** — `list_devices` now includes each device's `uuid`, enabling `get_device_scheduled_windows` lookups without a separate API call.
- **Policy windows date parameter encoding** — `get_group_scheduled_windows` and `get_device_scheduled_windows` now embed the `date` parameter directly in the URL path to prevent httpx from percent-encoding colons (`%3A`), which the Automox API rejects. Trailing `Z` suffix is also stripped automatically.

### Changed

- Remote-bind warnings now distinguish auth-enabled vs auth-disabled deployments; `--allow-remote-bind` help text updated to reference `AUTOMOX_MCP_API_KEYS`.
- `SECURITY.md` — "Authentication" removed from Scope and Limitations; replaced with RBAC-only note referencing V-108.
- `docs/deployment-security.md` — New "Built-in Endpoint Authentication" section; Kubernetes example includes `AUTOMOX_MCP_API_KEYS` secret; pre-production checklist updated.
- `docs/tool-reference.md` — "Endpoint Authentication" added to Enterprise Features section.
- `README.md` — `AUTOMOX_MCP_API_KEYS` and `AUTOMOX_MCP_API_KEY_FILE` added to configuration table; new "Endpoint Authentication" section; security highlights updated to 26 items (V-108).

### Security

- **V-108**: MCP endpoint Bearer-token authentication for HTTP/SSE transports. Uses FastMCP's `StaticTokenVerifier` to validate tokens from `Authorization: Bearer` headers. Keys loaded from `AUTOMOX_MCP_API_KEYS` or `AUTOMOX_MCP_API_KEY_FILE`; labelled keys (`client:token`) produce named client IDs for audit trails.
- **V-108a**: Unicode NFKC normalization and zero-width character stripping in `sanitize_for_llm()` to prevent homoglyph bypass of instruction-prefix detection.
- **V-112**: `policy.py` broad `except Exception` narrowed to `except (AutomoxAPIError, httpx.RequestError)` — raw upstream error strings no longer leak to the LLM via `ToolError`.
- **V-114**: Webhook URL validator cloud metadata blocklist expanded from 2 to 6+ hostnames (Azure, Oracle Cloud, generic `*.internal`).
- **V-117**: Reference-style markdown images/links now stripped by sanitizer.
- **V-118**: API key file permissions checked at load time; warning logged if group/world-readable.
- **V-119**: Unlabeled fenced code blocks now removed by sanitizer (previously only labelled shell/script blocks).

#### Phase 3: Advanced Workflows & Remediation (25 new tools, 6 prompts)

- **Worklet Catalog** (2 tools)
  - `search_worklet_catalog` — Search community worklets by keyword, OS, category
  - `get_worklet_detail` — Detailed worklet info including evaluation and remediation code

- **Data Extracts** (3 tools)
  - `list_data_extracts` — List available/completed data extracts
  - `get_data_extract` — Get extract details and download info
  - `create_data_extract` — Request a new data extract for bulk reporting

- **Org API Keys** (1 tool)
  - `list_org_api_keys` — List organization API keys (names and IDs only, secrets never exposed)

- **Policy History v2** (6 tools) — Richer policy execution reporting via `/policy-history` API
  - `policy_runs_v2` — List runs with time-range filtering, policy name/type/status filters
  - `policy_run_count` — Aggregate execution counts with day-range filtering
  - `policy_runs_by_policy` — Runs grouped by policy for cross-policy comparison
  - `policy_history_detail` — Policy history details by UUID
  - `policy_runs_for_policy` — Execution runs for a specific policy
  - `policy_run_detail_v2` — Per-device results with UUID-based queries and device name filtering

- **Audit Service v2 / OCSF** (1 tool)
  - `audit_events_ocsf` — OCSF-formatted audit events with category filtering (authentication, account_change, entity_management, user_access, web_resource_activity) and cursor pagination

- **Advanced Device Search** (6 tools) — Server Groups API v2
  - `list_saved_searches` — List saved device searches
  - `advanced_device_search` — Execute advanced search with structured query language
  - `device_search_typeahead` — Typeahead suggestions for search fields
  - `get_device_metadata_fields` — Available fields for device queries
  - `get_device_assignments` — Device-to-policy/group assignments
  - `get_device_by_uuid` — Device details by UUID (v2 endpoint)

- **Vulnerability Sync / Remediations** (7 tools)
  - `list_remediation_action_sets` — List vulnerability remediation action sets
  - `get_action_set_detail` — Action set details by ID
  - `get_action_set_actions` — Remediation actions for an action set
  - `get_action_set_issues` — Vulnerability issues (CVEs) for an action set
  - `get_action_set_solutions` — Solutions for an action set
  - `get_upload_formats` — Supported CSV upload formats
  - `upload_action_set` — Upload CSV-based remediation data

- **Workflow Prompts** (6 MCP prompts) — Pre-built guided templates for common admin tasks
  - `investigate_noncompliant_device` — Investigate and remediate non-compliant devices
  - `prepare_patch_tuesday` — Assess readiness and prepare for Patch Tuesday
  - `audit_policy_execution` — Audit a policy's execution history
  - `onboard_device_group` — Create and configure a new device group
  - `triage_failed_policy_run` — Triage and remediate failed policy runs
  - `review_security_posture` — Review fleet security posture

- **New modules**: `audit_v2`, `device_search`, `policy_history`, `worklets`, `data_extracts`, `vuln_sync` — all selectable via `AUTOMOX_MCP_MODULES`
- **Capability discovery** updated with 5 new domains (device_search, policy_history, worklets, data_extracts, vuln_sync); total domains: 15
- **Smoke tests** expanded from 35 to 49 covering all Phase 3 tools against live Automox org

### Fixed

- **Unreachable dead code** — Removed 13 `return result` statements that were unreachable after `return maybe_format_markdown(result, output_format)` across 8 tool files (`device_tools.py`, `policy_tools.py`, `group_tools.py`, `webhook_tools.py`, `package_tools.py`, `event_tools.py`, `report_tools.py`, `audit_tools.py`). Leftover from the `maybe_format_markdown()` refactor.
- **Incorrect bitmask values in policy resources** — Fixed 4 wrong schedule bitmask values in `policy_resources.py` that would cause policies to skip Sundays:
  - `Sunday=1` → `Sunday=128` (line 205)
  - `1-127 for all 7 days` → `254 for all 7 days` (line 219)
  - Example `"schedule_days": 127` → `254` (line 460)
  - Schedule syntax guide `1-127, where 127 = all 7 days` → `2-254, where 254 = all 7 days` (line 632)

### Security

- **V-018**: Webhook URL validation upgraded from string prefix check (`startswith("https://")`) to proper `urllib.parse.urlparse()` validation — now verifies scheme is `https`, hostname is present, and rejects URLs containing userinfo (`user:pass@host`) to prevent credential-smuggling patterns.
- **V-101**: Error messages passed through `sanitize_for_llm()` before reaching the LLM via `ToolError`, preventing prompt injection through crafted error payloads.
- **V-102**: Dependabot `pip` ecosystem added alongside `github-actions` for automated Python dependency security alerts.
- **V-103**: Webhook URL validation now blocks private/loopback/link-local IP addresses and cloud metadata endpoints (169.254.169.254, fd00::, etc.) to prevent SSRF attacks.
- **V-104**: Instruction-prefix regex expanded from 6 to 20+ patterns, covering additional injection vectors (`EXECUTE:`, `RUN:`, `OVERRIDE:`, `ADMIN:`, `TOOL_CALL:`, `<system>`, etc.).
- **V-105**: Data at sanitization depth limit is now redacted (`[redacted: max depth exceeded]`) instead of passed through unsanitized.
- **V-106**: Non-loopback HTTP/SSE binding now requires explicit opt-in via `--allow-remote-bind` flag or `AUTOMOX_MCP_ALLOW_REMOTE_BIND=true` environment variable. Server exits with an error if a non-loopback address is configured without this flag.
- **V-107**: Sensitive field redaction expanded to include `bearer`, `passwd`, `api-key`, and `apikey` patterns alongside existing `token`, `secret`, `key`, `password`, `credential`, `auth`.

### Added

#### Enterprise Features

- **Correlation IDs** — UUID4 assigned per tool call via FastMCP middleware. The ID flows to the `metadata` field of every tool response and is forwarded to the Automox API as the `X-Correlation-ID` request header. The middleware logs tool name, final status, and wall-clock latency at `INFO` level.
- **Token budget estimation** — Middleware warns when a response is estimated to exceed ~4000 tokens and auto-truncates list data to stay within budget. Threshold is configurable via `AUTOMOX_MCP_TOKEN_BUDGET` environment variable.
- **Idempotency keys** — All 21 idempotent write tools accept an optional `request_id` parameter (UUID string). A duplicate `request_id` within 300 seconds returns the cached response without re-executing the API call. In-memory TTL cache with a maximum of 1000 entries.
- **Markdown table output** — 13 list tools accept an optional `output_format` parameter (`"json"` default, `"markdown"` for compact tables suited to chat interfaces).
- **`discover_capabilities` meta-tool** — Returns all available tools organized by domain (devices, policies, patches, groups, events, reports, audit, webhooks, account, compound). Always registered regardless of `AUTOMOX_MCP_MODULES` configuration. Brings total tool count to 45.

#### Security Hardening

- **API key privacy** — API key stored as a private attribute on the HTTP client; authentication injected per-request via an httpx auth callback rather than stored in headers.
- **Client lifecycle management** — HTTP client `aclose()` called on server shutdown via FastMCP lifespan context, preventing connection leaks.
- **Non-loopback binding warning** — Server emits a warning log when `--transport http` or `--transport sse` binds to a non-loopback address (e.g., `0.0.0.0`).
- **Exception logging** — Silent exception swallowing replaced with structured `debug`-level logging throughout workflow modules.
- **Bandit pre-commit hook** — `bandit` static security analysis added to pre-commit configuration; runs on every commit.
- **Typed schema fields** — 18 previously bare `list` / `dict` fields in `schemas.py` replaced with fully parameterized types (e.g., `list[str]`, `dict[str, Any]`) for stronger Pydantic validation.
- **Module splits** — `devices.py` split into `devices.py` + `device_inventory.py` + `device_commands.py`; `policy.py` split into `policy.py` + `policy_crud.py` for clearer separation of concerns.
- **Lint cleanup** — Ruff lint errors reduced from 46 to 0 across `src/` and `tests/`.
- **CI coverage threshold** — `pytest` now runs with `--cov-fail-under=90`; CI fails if coverage drops below 90%.
- **Test suite growth** — Tests increased from 137 to 634; coverage increased from 70% to 91%.

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
- `README.md` — Updated to document all 45 tools, 9 resources, 10 modules, and new compound/inventory capabilities
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
- **Falsy-value `or` bugs** — Fixed `exit_code`, `active_flag`, `pending_patches`, and `org_id` fields that used Python `or` operator, causing `0` and `False` to be silently dropped. Replaced with `is not None` checks in `policy.py`, `devices.py`, and `client.py`.
- **`ToolResult.deprecated_endpoint`** — Default changed from `True` to `False` (copy-paste error from `PaginationMetadata`)
- **`policy_compliance_stats` crash** — Changed from `PolicySummaryParams` (which injected extra kwargs) to `GetPolicyStatsParams` with `OrgIdContextMixin`
- **Response parsing mismatch** — `list_devices_needing_attention` now handles both `{"data": [...]}` and `{"nonCompliant": {"devices": [...]}}` response shapes from `/reports/needs-attention`
- **Policy resource `or` bug** — `["policy_id" or "id within policy object"]` evaluated to `["policy_id"]`; fixed to proper list with comma
- **Webhook event type count** — Description in `webhook_resources.py` corrected to match actual list of 39 event types
- **String-as-sequence guard** — `_candidate_org_sequences()` now rejects `str`/`bytes` as sequences
- **Pagination `limit=None`** — `summarize_policies` loop broke after first page when limit was None; removed premature break
- **`total_count` key mismatch** — `compound.py` referenced non-existent `total_count` key; fixed to `total_policies_considered`/`total_policies_available`
- **`ClonePolicyParams` missing mixin** — Added `OrgIdContextMixin` for consistent `org_id` injection
- **`compound_tools.py` dict mutation** — `_call` and `_call_with_org_uuid` now copy `raw_params` before modifying
- **Noncompliant report pagination** — Added auto-pagination loop matching `get_prepatch_report` behavior
- **Markdown return type** — All 13 markdown-format tool returns now wrapped in `dict` to match `dict[str, Any]` type annotation
- **`schedule_time` regex** — Tightened from `^\d{2}:\d{2}$` (allowed "99:99") to `^([01]\d|2[0-3]):[0-5]\d$`
- **API key whitespace** — `client.py` now strips whitespace from API key values
- **`_extract_devices` list handling** — Now merges devices from all list elements instead of only inspecting the first
- **Default port logic** — Host and port defaults now applied independently instead of requiring both to be None
- **`date` parameter shadow** — Annotated with `noqa: A002` in `audit.py` to acknowledge intentional shadowing
- **`_orgs_payload()` test fixture** — Fixed `"uuid"` key to `"org_uuid"` in `test_workflows_device_inventory.py`
- **Docstring module names** — `get_enabled_modules()` docstring corrected: `patches`→`packages`, `approvals`/`inventory` removed, `compound` added
- **README/CHANGELOG counts** — Corrected tool counts (44→45), read-only counts (28→29), list tool counts (15→13), initial release date (2025-01-01→2025-11-13)
- **README ToC link** — Fixed broken `#versioning--release-notes` anchor to `#versioning`
- **README `.python-version` claim** — Removed reference to non-existent `.python-version` file

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

- **Read-Only Mode** (`AUTOMOX_MCP_READ_ONLY`) — When set to `true`, all 16 destructive tools are excluded at registration time, leaving 29 read-only tools. Useful for audit, reporting, and monitoring use cases.
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
- `README.md` — Updated to document all 45 tools, 9 MCP resources, read-only mode, modular architecture, and new configuration options

### Fixed

- `tools/__init__.py` — `groups` module `has_writes` flag corrected from `False` to `True` (group CRUD tools were not gated by read-only mode)
- `webhook_tools.py`, `policy_tools.py` — Fixed `org_id` falsy-value check: `or` operator replaced with explicit `None` comparison to prevent `org_id=0` from being silently overwritten
- `webhook_resources.py` — Corrected webhook event type count to 39
- `workflows/devices.py` — Fixed parameter shadowing: local `policy_status` variable renamed to `device_policy_status` to avoid shadowing the function parameter `policy_status_filter`
- `workflows/__init__.py` — Fixed `__all__` ordering (`audit_trail_user_activity` before `apply_policy_changes`, `summarize_patch_approvals` before `summarize_policies`)

### Security

- **V-001**: Audit workflow now redacts sensitive fields (`token`, `secret`, `key`, `password`) from API error payloads before surfacing them in tool responses
- **V-002**: Webhook schemas use `uuid.UUID` type for `org_uuid` and `webhook_id` parameters, rejecting malformed/traversal inputs at the Pydantic validation layer
- **V-003**: Webhook `create` and `update` operations enforce HTTPS-only URLs via Pydantic `model_validator`
- **V-004**: Report `limit` parameters (`GetPrepatchReportParams`, `GetNeedsAttentionReportParams`) bounded with `le=500` to prevent unbounded result sets
- **V-005**: HTTP client debug logging no longer includes request parameters, preventing accidental credential exposure in log output
- **V-006**: The shared `call_tool_workflow()` helper (formerly per-module `_call()` wrappers) logs unexpected exceptions server-side and returns a generic error message to MCP clients, preventing internal details (file paths, connection strings, module names) from leaking
- **V-007**: `AUTOMOX_ORG_ID` validated as a positive integer at server startup; non-numeric or non-positive values raise `RuntimeError` before any tools are registered
- **V-008**: Policy workflow narrowed 3 broad `except Exception` handlers to `except (AutomoxAPIError, ValueError, TypeError, KeyError)` with structured debug logging
- **V-009**: `PolicyDefinition` model changed from `extra="allow"` to `extra="ignore"` — unrecognized fields are silently dropped instead of passed to the Automox API
- **V-010**: Sensitive field redaction keywords restored to broad patterns (`token`, `secret`, `key`, `password`, `credential`, `auth`) to cover `access_token`, `signing_key`, etc.
- **V-011**: Auto-pagination loops in reports and policies capped at 50 pages to prevent runaway API calls
- **V-012**: Webhook secrets stripped from idempotency cache after `create_webhook` and `rotate_webhook_secret` — the one-time secret is returned to the caller but not persisted in memory
- **V-013**: Raw upstream error text truncated to 500 characters in `_extract_error_payload()` to prevent verbose error pages from leaking infrastructure details
- **V-014**: `AUTOMOX_MCP_TOKEN_BUDGET` parsing wrapped in try/except — invalid values fall back to 4000 instead of crashing at import
- **V-015**: `get_enabled_modules()` validates module names against the known set and logs a warning for unrecognized names
- **V-016**: Audit `_sanitize_payload()` now redacts keys matching sensitive patterns before returning raw events to MCP clients
- **V-017**: `.gitignore` updated to cover `.env.*` variants (with `!.env.example` exclusion)

### Optimized

- `webhook_resources.py` — Webhook event types JSON precomputed at module load instead of being rebuilt on every resource request
- `schemas.py`, `group_tools.py` — `policies` parameter typed as `list[int]` (was untyped `list`) for stronger input validation
- `tools/__init__.py` — Replaced `__import__` with `importlib.import_module` for clearer dynamic imports
- `workflows/devices.py` — Early `break` in `list_device_inventory` when limit is reached, avoiding unnecessary iteration
- `workflows/audit.py` — Removed unreachable dead code in `_email_looks_valid`
- `workflows/devices.py` — Simplified `_normalize_status` priority loop: replaced sorted-list iteration with set-based check
- `utils/tooling.py` — Extracted `maybe_format_markdown()` helper to replace 13 identical 6-line markdown formatting blocks across 8 tool files
- `conftest.py` — Consolidated duplicated `StubClient` implementations from 11 test files into a single shared class
- `utils/tooling.py` — `IdempotencyCache.get()`/`put()` and `check_idempotency()`/`store_idempotency()` made async with `asyncio.Lock` for concurrency safety

## [0.1.0] - 2025-11-13

### Added

- Initial release with 18 tools across 4 domains (devices, policies, account, audit)
- 4 MCP resources (policy quick-start, schema, schedule-syntax, server group list)
- FastMCP 2.0 framework with stdio, HTTP, and SSE transport support
- Rate limiting, error formatting, and org UUID resolution utilities
- Pydantic input validation for all tool parameters
- Python 3.11+ support
