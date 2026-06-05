# Changelog

All notable changes to the Automox MCP Server will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **`device_detail` now emits a device-level `compliance` rollup.** Counts per policy state plus the named policies in `needs_remediation`, and a note encoding the rule (verified live across ~20 devices): a device is non-compliant when at least one policy needs remediation — pending policies alone do not count against compliance. Previously the model had to derive all of this from raw per-policy entries.

### Fixed

- **`audit_events_ocsf` no longer forces the model to decode raw OCSF plumbing (audit finding cluster 2).** Three changes, all live-verified 2026-06-05: (1) event `time` arrives from the upstream as **epoch seconds** (a float — despite the OCSF standard specifying milliseconds); the projection now converts it to an ISO 8601 UTC string, with a defensive milliseconds branch for values too large to be seconds. (2) `severity`/`status` string labels are filled in from the `severity_id`/`status_id` integer enums (spec `x-enumDescriptions`) when the upstream omits the strings — live events sometimes carry only the ids, and these OCSF integers mean something entirely different from the `/servers` policy-status enum (OCSF: 1=success, 2=failure). (3) The tool description documents both scales. Test fixture updated from invented ISO-string times to the captured live shape.
- **`get_device_by_uuid` no longer returns the raw `/servers/{id}` payload unexplained — it was the unfixed twin of the `device_detail` defects below.** The tool returned the same ServerWithPolicies DTO as `device_detail` but verbatim: integer policy codes with no legend, the unit-less (and spec-misdocumented) `uptime`, and no compliance projection. Found by a 12-domain projection audit; all three findings adversarially verified. The raw dict now passes through a shared enrichment (`enrich_raw_device_payload`): each integer policy code gains a `status_label` sibling (raw code kept for fidelity), `uptime` is replaced by `uptime_minutes`, and the device-level `compliance` rollup is attached. The tool description also no longer claims a "Server Groups API v2" lookup — it has used the canonical `/servers/{id}` endpoint since the #92 fix. Smoke now asserts every integer policy code carries a label and the unit-less key is absent.
- **Per-policy status codes in `device_detail` are now translated instead of passed through raw.** `GET /servers` `policy_status[].status` is an integer enum — `0 = needs_remediation`, `1 = up_to_date`, `2 = pending` (confirmed against the Console API spec and cross-checked live against the `status.policy_statuses[].compliant` booleans: code 1 is the only value paired with `compliant: true`). The summarizer previously stringified the integers verbatim (`"1"`/`"2"`), forcing the model to guess a mapping — and in observed use it guessed one that inverted compliant and non-compliant. Worse, code 0 (needs remediation — falsy) fell through a truthiness chain to absent alternate keys and surfaced as `"unknown"`, so the one state that demands action was the one reported least clearly. The mapping is applied in the policy-entry summarizer, not in the generic status normalizer, because other Automox enums reuse these integers with different meanings.
- **`uptime` renamed to `uptime_minutes` in `device_detail` — the public spec's unit is wrong.** The Console API spec describes `Server.uptime` as "measured in seconds", but live verification against known device boot times (2026-06-04) shows the value is **minutes**, sampled at the device's last full scan — so it can also lag the current boot session. The unit-less raw key invited bad inferences (an observed session read ~6.7k minutes ≈ 4.7 days as possibly "~9 months of uptime"). The projection now emits `uptime_minutes` as an integer, and the tool description carries the sampled-at-last-scan caveat.

- **`verify-publish` no longer loses the race to PyPI index propagation (CI only).** The v2.0.3 run failed despite a healthy publish, for two compounding reasons: uv caches simple-index responses, so after a too-early first attempt every retry replayed the cached "no such version" miss instead of re-checking PyPI; and the retry window (6×20s ≈ 2 min) was shorter than occasional index-propagation lag. The install check now passes `--refresh-package automox-mcp` and retries for up to ~15 minutes (30×30s; job timeout raised 10→20 min). The loop still exits on the first success, so a normal release pays nothing — the ceiling only spends free runner minutes on slow days, instead of attended minutes diagnosing and rerunning a red release.

## [2.0.3] - 2026-06-04

### Changed

- **ADS-family 403s are now self-diagnosing.** The upstream Server Groups v2 search endpoints return a bare `403` that is indistinguishable from an RBAC denial, so callers (and models) chase permissions instead of the usual fix. The search/saved-search/assignments workflows now append a hint to any 403 — global/account keys behave inconsistently on these endpoints while org-scoped keys work reliably; try an org-scoped key for the target org (zone Settings > Secrets & Keys) — at the exact failure point, with no configuration to declare or drift. The metadata endpoints (`get_searchable_fields`, `get_search_scopes`, `get_device_metadata_fields`) are deliberately excluded: they accepted either key type throughout, so a 403 there means something else. (A declared `KEY_SCOPE` env var was considered and rejected — users who don't know their key type would set it wrong, and it drifts on key rotation.)
- **README now explains the two API key types, not just which to pick.** Added an org-scoped vs global/account key comparison (scope, where each is created, tool coverage) to the credentials section, a symptom line (403 on the search family while reads work elsewhere usually means the key, not permissions), and a key-type hint in `.env.example` — so a holder of a global key can recognize it and mint the right one instead of just being told "use org-scoped."
- **Documented Advanced Device Search key behavior and the `TAGS` search scope.** Observed live (2026-06-03/04): global/account-scoped API keys behave **inconsistently** on the Server Groups API v2 search endpoints (`advanced_device_search`, `device_search_typeahead`, saved-search CRUD, `list_searches_for_device`, `get_device_assignments`) — a full-admin account key 403'd uniformly across all orgs on day one, then (untouched) worked in exactly one org a day later while still 403ing elsewhere — whereas a freshly-issued org-scoped key worked immediately and reliably. Mechanism unconfirmed upstream (an interim revision claimed the endpoints flatly "only accept org-scoped keys"; the observation matrix in `docs/api-coverage.md` replaces that overclaim). The README previously claimed "both global and org-scoped API keys work"; it now recommends an org-scoped key and lists the affected tools. The `advanced_device_search` description also now shows that tag search uses scope `TAGS` (not `DEVICE`): `{"scope": "TAGS", "field": "tag", "operator": "IN", "values": [...]}` — confirmed live against a known tag census.

## [2.0.2] - 2026-06-03

### Security

- **HTML sanitizer now suppresses the text content of elements carrying a dangerous attribute.** `_HTMLTextExtractor` detected `on*` event handlers and `javascript:`/`data:` URLs in `href`/`src`/`action` but took no action — it dropped the tag (as it does for any tag) while still emitting the element's inner text. The dangerous *value* never reached output (attributes are never emitted), so impact was limited to defence-in-depth, but the detection was effectively dead. The extractor now tracks suppression with a `(tag, skipping)` stack that correctly releases on the matching end tag, skips void elements (`<img>`, `<br>`, …) that have no end tag, tolerates unclosed inner tags, and relies on `HTMLParser` CDATA mode for `<script>`/`<style>`. (The obvious one-line `_skip_depth += 1` fix was rejected — it leaks skip state on non-`script`/`style` tags and self-closing tags, silently swallowing all trailing text.)

### Fixed

- **`preview_policy_device_filters` mis-reported every result and 500'd on filter-only targets — both fixed.** Verified live (2026-06-03): (1) The endpoint returns a `{"results": [...], "size": N}` envelope, which `extract_list` didn't recognize — it wrapped the whole envelope as a single device and reported `total_devices: 1` for *any* result set (a 14-device group and its 6-device filtered subset both came back as "1"). The wrapper now parses `results`/`size` directly, falling back to the bare-list / `data` shapes. (2) A filter-only request (`device_filters` with no `server_groups`) and an empty request both return an opaque upstream HTTP 500; the wrapper now pre-empts them with actionable guidance ("pass the `server_groups` this policy targets…"). Confirmed live that `device_filters` **are** applied within a `server_groups` scope — a `tag` clause narrows a group's set to exactly the tagged devices — so previewing a tag-targeted policy works when the target groups are supplied. (This corrects an earlier note that the endpoint was simply broken: it works when `server_groups` is present.)
- **Policy `device_filters` no longer silently dropped — wrong-shape clauses are rejected, and structured filters are auto-enabled on all policy types.** Three issues, all verified against the live tenant (2026-06-03): (1) The model-facing guidance resources (`resource://filters/syntax` and the policy how-to) documented filters as `{"type": "tag", "tag_name": "..."}`, but the API uses `{"field", "op", "value"}` (fields `tag`/`ip_addr`/`hostname`/`os_family`/`os_version_id`/`serial_number`/`organizational_unit`, singular; ops `in`/`not_in`/`like_any`) and **rejects the legacy shape with HTTP 400** — every real stored policy uses the `{field, op, value}` form. Both resources now document the correct shape. (2) `_normalize_device_filters` forwarded any mapping clause verbatim without validation, so a wrong-shape filter reached the API as an opaque 400; it now validates clause shape locally and rejects the legacy `{type, tag_name}` form with an actionable message. (3) `device_filters_enabled` (which the API requires for filters to take effect — all live policies carry it `True`) was only auto-set for `patch` policies; structured filters on `custom`/worklet and `required_software` policies shipped with the flag unset, so a tag filter could be present-but-disabled and the policy would target every assigned group. The flag is now auto-set for all policy types when filters are present. (Previewing the resulting targeting: see the `preview_policy_device_filters` entry above.)
- **`docs/tool-reference.md` Table of Contents counts and anchors corrected.** The TOC listed Device Management as 9 tools (header says 11) and Vulnerability Sync as 7 (header says 9); the stale counts also broke the in-page anchor links. The section headers — validated against the registered tool set by `test_doc_tool_counts.py` — were already correct.
- **`create_policy`/`update_policy` schedule-days error message no longer advertises an unsupported range.** The "Unrecognized day name" message offered numeric indexes "0-6 or 1-7", but `_normalize_schedule_days_input` accepts 0–6 only (1–7 was intentionally removed for its ambiguous Monday/Sunday mapping). Dropped the "or 1-7" clause.

### Changed

- **`preview_policy_device_filters` description and smoke coverage now reflect the verified contract.** The tool description and `docs/tool-reference.md` state that `server_groups` is required when `device_filters` is provided (pass the groups the policy targets; clauses apply within that scope). The smoke suite's preview check now asserts correctness instead of "got a response": the reported `total_devices` must match the returned device list (catches the envelope-wrapped-as-one-device regression), and a filter for a nonexistent tag must narrow the group scope to exactly 0 devices (catches a silently-ignored filter).
- **Code-quality cleanup (CodeQL + AI code-scanning findings), no behavior change.** Removed unused module-level `logger` bindings across 18 tool modules and a dead instruction-strip allowlist superseded by the preserve-list denylist; consolidated redundant/duplicate imports (`json` hoisted in `schemas.py`, `asynccontextmanager` in `server.py`, dead local re-imports in `utils/tooling.py` and `workflows/devices.py`); parenthesized two implicitly-concatenated multi-line strings inside reference list literals to make intent explicit. Added a regression test for the `list_device_packages` auto-pagination safety cap (`_MAX_PACKAGE_PAGES`) — the `metadata.complete = False` truncation signal was previously unverified.

## [2.0.1] - 2026-06-02

### Fixed

- **`advanced_device_search` was broken three ways — now filters correctly.** (1) The Server Groups v2 search endpoint requires `organizationUuids` in the request *body* (the org UUID in the path is not enough); without it every call returned `400 "organizationUuids required"`. (2) Filter criteria must sit at the body top level under `filters` — the wrapper nested them under a `query` key, which the endpoint *silently ignores*, returning the entire fleet instead of the filtered set. (3) The page-size parameter is `size`, not `limit`. The response is also a Spring `Page` envelope (`content`/`total_elements`), so `extract_list` was wrapping the whole envelope as one bogus device. All verified live (e.g. an `osFamilyName EQ Linux` filter now returns 1 device, not the unfiltered 227). The model-facing `query` dict now carries a `filters` list — see the updated tool description.
- **`create_saved_search` / `update_saved_search` returned HTTP 500 on every structured query.** Upstream expects the search spec wrapped in a `search` envelope carrying `organizationUuids`, not a top-level `query` key. `create_saved_search` now builds that envelope (caller-supplied `organizationUuids` preserved). **`update_saved_search` is now read-modify-write:** the upstream `PUT` is a *full replace* and 500s on a partial body, so a name-only or description-only update would have failed even with the envelope fix — the wrapper now fetches the existing record, overlays the provided fields, and re-`PUT`s the complete object. Verified live: create → name-only update → delete all succeed.
- **`device_search_typeahead` returned `400` on every call.** Same `organizationUuids`-in-body requirement as `advanced_device_search`, plus the field selector is `fields` (an array), not `field` (singular) — the wrapper sent neither correctly. The model-facing `field` stays singular and is wrapped into the one-element array the endpoint expects, with `organizationUuids` injected; the `content` page envelope is now parsed. Verified live (returns suggestions). Found by the hardened smoke suite below.
- **Smoke suite now asserts correctness, not just "got a response" (test hardening).** A read-only smoke pass marked a tool PASS on any non-error reply, so the contract bugs above were invisible to it. `advanced_device_search` now asserts a filter *narrows* the result vs. unfiltered (catches the silent whole-fleet return); `list_device_packages` asserts `metadata.complete` (catches truncation); a self-cleaning `create → update → delete` saved-search round-trip catches the write-path 500s — **this round-trip caught the `update_saved_search` partial-body 500, and exercising the suite caught the `device_search_typeahead` `400`.** `preview_policy_device_filters` now passes a valid `server_groups` target (an empty body 500s upstream). Account-admin tools (`list_users`, `get_account`, `list_account_rbac_roles`, `list_global_api_keys`, `list_zones`) record **skip-OK** when the key lacks scope (403/404) instead of failing, so a limited key doesn't make the pre-tag gate noisy. `CLAUDE.md` documents the convention: wrapper unit-test fixtures must be captured real payloads, not invented shapes. (Putting smoke in CI is tracked separately.)
- **`list_device_packages` silently truncated.** `/servers/{id}/packages` returns a bare list with no `total` and pages 0-indexed by `limit`, so a single call capped at the page size while reporting `total_packages = len(page)` — the caller could not tell more existed (the reported "~125–250 of ~500"). It now auto-paginates the full set by default (verified: 1045 packages from a host that previously truncated) and reports `metadata.complete`; an explicit `page` still returns one page and flags `metadata.pagination.has_more`.

## [2.0.0] - 2026-06-01

Establishes and documents the server's capability model: a categorical policy for what the MCP server exposes, omits, and gates. **This is a major release because it carries deliberate, non-defect breaking changes to the destructive-operation gating contract** (see Breaking Changes). Read-only and additive consumers are unaffected; the blast radius is limited to two opt-in flags.

### Breaking Changes

- **Destructive-gate env flags now follow a uniform `AUTOMOX_MCP_ALLOW_<TOOL_NAME>` rule — one rename.** Each gate flag's suffix is the uppercased name of the single tool it unlocks, so the flag↔tool mapping is 1:1 and greppable. The flag shipped in 1.2.0 as `AUTOMOX_MCP_ALLOW_REMEDIATION` is renamed to **`AUTOMOX_MCP_ALLOW_APPLY_REMEDIATION_ACTIONS`** (matching tool `apply_remediation_actions`). Anyone who set the old name must update it, or `apply_remediation_actions` will not register — fail-safe (the capability is withheld, never silently enabled). The `delete_device` gate (`AUTOMOX_MCP_ALLOW_DELETE_DEVICE`) and the new Splashtop gate already follow the rule, so no other flags change.
- **`splashtop_bulk_install_uninstall` is now gated.** It installs/uninstalls the Splashtop client across an entire server group in one call — a fleet-scale blast radius per-call confirmation cannot meaningfully vet — so it now requires `AUTOMOX_MCP_ALLOW_SPLASHTOP_BULK_INSTALL_UNINSTALL=true` in addition to write mode. Previously it registered on write mode alone. **No grandfathering:** the destructive-gating standard is applied uniformly. Single-device Splashtop actions (`install`/`uninstall`/`force_disconnect`) are unaffected — they remain confirmation-gated (`destructiveHint`) only, since they are single-target and recoverable. The flag name mirrors the tool so it reads as "gate deploying/removing the client software fleet-wide," not "gate starting remote-control sessions" (that is `splashtop_initiate_connection`, which is not env-gated).

### Added

- **`docs/api-coverage.md` — coverage map and capability policy.** Documents, against the `2026-05-28` Console API bundle (115 documented operations), every intentional omission and the destructive-operation gating principle. README gains a **Capability model** section summarizing it.
- **`delete_device` tool (#123), gated.** Permanently deletes a device record and its history via `DELETE /servers/{id}`. Irreversible and not reconstructable through the MCP — there is no create-device counterpart (agents self-register) — so it is gated behind a new default-off `AUTOMOX_MCP_ALLOW_DELETE_DEVICE` flag (category B), not ask-first. Off by default even in write mode.
- **`update_device` tool (#111).** Updates a single device's `custom_name`, `server_group_id`, `exception`, `tags`, or `ip_addrs` via `PUT /servers/{id}`. Fills the single-device-update gap that `batch_update_devices` (tags-only) leaves; not destructive, plain write (off under `read_only`).
- **`delete_action_set` / `delete_action_sets_bulk` tools (#111).** Delete Vuln Sync action sets — Tier-1 ask-first (`destructiveHint`, reconstructable via re-upload). The bulk tool issues one atomic `DELETE /…/action-sets` with a `{"ids": [...]}` body; `AutomoxClient.delete` gained JSON-body support to enable it.
- **`upload_policy_file` tool (#106), gated + local-only.** Uploads a local installer file (up to 10 GB) to a Required Software policy via `POST /policies/{id}/files`. Mechanism: `file_path` (server reads a local file) — `base64` is impractical at GB scale and `file_url` was rejected to avoid building SSRF defense from scratch. Confined by a new default-off gate `AUTOMOX_MCP_ALLOW_UPLOAD_POLICY_FILE`, a **required** directory allowlist `AUTOMOX_MCP_UPLOAD_ALLOWED_DIRS` (paths canonicalized; `..`/symlink escape rejected), a size cap `AUTOMOX_MCP_UPLOAD_MAX_BYTES` (default 10 GB), and **stdio-only** registration — `main()` refuses to start a remote transport while the flag is on, so it can never be served over a network. The installer streams to Automox and never passes through the model. Contract verified end-to-end against the live tenant (2026-06-01): create Required Software policy → upload → `201` (returns a file object `{uuid, filename, size}`) → delete.
- **`list_webhook_deliveries` tool (#128).** Lists recent delivery attempts (status, latency, error) for a webhook via `GET /organizations/{org_uuid}/webhooks/{id}/deliveries` — delivery troubleshooting. Read-only, no gate; newest-first and cursor-paginated, with optional `start_date`/`end_date` filters. This was the 9th of 9 Webhooks API paths and the only one not yet wrapped; the server now covers **100%** of the published Console **and** Webhooks APIs (the Webhooks API is a separate OpenAPI doc, `Automox Webhooks API` v1.0.0). The `DeliveryLog` projection carries no secret material (the signing secret is write/rotate-only).
- Tool count is now **133** (85 read / 48 write); read-only mode exposes 85.

### Changed

- **`upload_action_set` tool signature (#106).** Replaces the freeform `action_set_data` dict with `csv_content` (raw CSV text), `source` (format enum), and `filename` (becomes the action set's display name). CSV arrives inline as text — no URL fetch or local-file read, so no SSRF/file-read surface.
- **README capability claim + `docs/api-coverage.md` webhooks coverage (#128).** The README now asserts the server wraps 100% of the published Console and Webhooks APIs with the single deliberate exception of secret-exposing endpoints, and the stale line claiming device deletion is *omitted* is corrected — `delete_device` ships **gated** (#123), not omitted. `api-coverage.md` gains a Webhooks API coverage section (all 9 paths mapped; notes the spec's `PUT`-vs-our-`PATCH` drift on update, cross-ref #95).

### Fixed

- **`upload_action_set` now works — sends real `multipart/form-data` (#106).** The previous implementation POSTed JSON and was non-functional; the live endpoint requires a multipart file. Added `AutomoxClient.post_multipart`, which overrides the client's default `application/json` content-type with the boundary httpx encodes. Contract confirmed against the live tenant (2026-05-31): `source` is a **query parameter** (enum `generic|qualys|tenable|crowd-strike|rapid7`) and the multipart body carries `file` + `format` (same enum) — the earlier opaque `500` was `source` sent as a form field with an empty query string.

### Policy (documented, no code change)

- **Secrets are never handled** — no decrypt tools, no password-setting, secret fields redacted. `PUT /users/{id}` (full-replace, accepts `password`) stays omitted; the `PATCH` variant (`update_user`) is the wrapped one.
- **Destructive operations are two-tier** — *ask-first* (`destructiveHint`, host confirmation) for single-target/recoverable actions; *gated* (default-off env flag) only when confirmation can't protect the operator: fleet-scale **(A)**, self-lockout **(B)**, or arbitrary model-authored code execution **(C)**.
- **`DELETE /servers/{id}` (device deletion) now wrapped, gated** — after verified demand (#123) it ships behind `AUTOMOX_MCP_ALLOW_DELETE_DEVICE` (category B: no create-counterpart, no MCP-side undo), per the standing policy that it would ship gated rather than ask-first. The documented-surface build backlog (`PUT /servers/{id}`, action-set deletes) is also covered (#111); binary/multipart uploads (action-set CSV + Required Software installer) are now covered too (#106 closed).

## [1.2.1] - 2026-05-30

Directory-submission preparation for the Anthropic Connectors Directory. No new tools, endpoints, or behavioral changes — additive metadata, documentation accuracy, and tool-description clarifications.

### Added

- **Privacy policy declaration for directory submission.** Added the `privacy_policies` array to `mcpb/manifest.json` (pointing at the public `PRIVACY.md` on `main`), satisfying the directory's requirement for an HTTPS-hosted policy declared in both README and manifest. Added a scope/deference clause to `PRIVACY.md` clarifying that it covers only the local MCP proxy and that data within the Automox platform is governed by the [Automox Privacy Policy](https://www.automox.com/legal/privacy-policy).
- **Human-readable `title` on every tool annotation.** All 127 tools now expose an MCP `ToolAnnotations.title` (e.g. `list_devices` → "List Devices"), derived from the tool name by a post-registration pass so titles cannot drift from a separate source. Improves host-client UI display and satisfies the directory's tool-annotation guidance.

### Fixed

- **Tool-count consistency across docs.** Reconciled stale read/write counts to the true split — **127 tools = 84 read / 43 write** — in `mcpb/manifest.json` (read-only config description), `README.md`, and `docs/deployment-security.md`. The latter also previously characterized all write tools as `destructiveHint: true`; corrected to `readOnlyHint: false` (the actual invariant — 42 of the 43 are destructive; `refresh_saved_search_cache` is an idempotent non-destructive write).
- **API references on freeform-query tools.** `advanced_device_search`, `create_saved_search`, and `update_saved_search` now name the Automox Advanced Device Search API in their descriptions, per the directory's requirement that caller-constructed-query tools reference the target API.

## [1.2.0] - 2026-05-30

### Fixed

- **Test-suite order-dependence (latent, pre-existing).** A test reimported the package (`sys.modules` pop + re-`import`), leaving duplicate class objects behind; later `issubclass(..., OrgIdRequiredMixin)` checks then compared classes across module copies and silently stopped injecting `org_id` — invisible in the fixed CI order, but failing up to ~100 tests under randomized order. Added a `conftest` autouse fixture that snapshots/restores `sys.modules` (and `os.environ`) per test, and added `pytest-randomly` (dev) so the suite now runs in randomized order and regressions surface immediately. Suite is green across 26 seeds.

### Added

- **Global (account-scoped) API keys — 4 tools (#91, category B).** `list_global_api_keys` (metadata only), `create_global_api_key`, `update_global_api_key` (enable/disable), `delete_global_api_key`. Same secret-handling as the per-user keys: list/create return metadata only (verified against the DTOs — no secret), and the `decrypt` endpoint is deliberately not wrapped. Writes are `read_only`-gated and idempotency-keyed. Tool count 123 → 127 (read-only 83 → 84).
- **Identity / zone / API-key writes — 7 tools (#91, category A, write slice).** Reads: `list_user_api_keys`, `get_user_api_key` (key metadata only). Writes: `create_zone`, `update_user`, `create_user_api_key`, `update_user_api_key`, `delete_user_api_key`. Security guards baked in: `create_zone` redacts the zone `access_key`; the per-user key endpoints never return the key secret (verified against the DTOs — create/get/update are metadata-only, and the secret is not retrievable via MCP); and `update_user` **deliberately cannot set passwords** (the spec's PATCH/PUT accept password fields, an account-takeover vector excluded here). The `decrypt` endpoints remain skipped. Tool count 116 → 123 (read-only 81 → 83).
- **Remediation execution — `apply_remediation_actions` (#91, category C, part 2).** Wraps `POST /orgs/{id}/remediations/action-sets/{id}/actions` to run `patch-now` / `patch-with-worklet` on explicit devices, immediately changing endpoint state (async, `202 Accepted`). **Double-gated:** requires write mode *and* the new `AUTOMOX_MCP_ALLOW_REMEDIATION=true` env flag (default off); `destructiveHint:true`, idempotency-keyed, no "all devices" shortcut. Snake_case inputs (`solution_id`/`worklet_id`) are mapped to the API's camelCase body. Tool count 115 → 116 (the 116th registers only with the env flag).
- **Policy device-targeting assessment + bulk device tagging (#91, category C, part 1).** Three tools: `preview_policy_device_filters` (`POST /policies/device-filters-preview`) — dry-run of which devices a policy's filters/server-groups would target, changes nothing; `list_devices_for_policies` (`POST /server-groups-api/policies/servers`) — devices currently targeted by given policy UUIDs, i.e. blast-radius assessment; both read-only. Plus `batch_update_devices` (`POST /servers/batch`) — bulk attribute actions on ≤500 devices (the upstream `actions` contract supports `tags` apply/remove today; passed through for forward-compatibility), a `read_only`-gated write. The remaining category-C endpoint — `runActions` (remediation execution) — ships separately behind an explicit env gate. Tool count 112 → 115 (read-only 79 → 81).
- **Identity inspection — 9 read-only tools (#91, category A, read slice).** `list_users`, `get_user`, `get_account`, `list_account_rbac_roles`, `get_account_user`, `list_zones_for_user`, `list_zones`, `get_zone`, `list_zone_users`. The server could previously invite/remove users but not list or read them, accounts, zones, or RBAC roles — an asymmetric surface this closes. **Secrets are redacted in every projection**: the User DTO's `intercom_hmac` and the zone DTO's `access_key` are never surfaced. The per-user API-key endpoints (list/get/create/update/delete and especially `decrypt`) are intentionally **out of scope** pending an explicit key-exposure sensitivity decision. Tool count 103 → 112 (read-only 70 → 79).
- **Multi-zone patch-policy clone on `clone_policy` (#91, category E).** New optional `target_zone_ids` argument routes to the server-side `POST /policies/{id}/clone` endpoint, cloning a patch policy into one or more zones/orgs (1–500 zone UUIDs) in a single atomic call and returning the per-zone `{policy_id, zone_id, org_id}` results. Upstream supports patch policies only; `target_zone_ids` is mutually exclusive with `name`/`server_groups`. Without it, `clone_policy` keeps its existing client-side GET-then-POST behavior, which works for all policy types but stays within the source org. No new tool, so the tool count is unchanged.
- **Search & metadata enrichment — 4 device-search tools (#91, category D).**
  - `get_searchable_fields` — `GET /server-groups-api/device/metadata/fields`: searchable fields grouped by scope with per-field type metadata, richer than the existing flat `get_device_metadata_fields` (`device-fields`). Read-only.
  - `list_searches_for_device` — `GET …/device/saved-search/server/{deviceUUID}`: which saved searches currently contain a given device, with optional `type` filter. Read-only.
  - `run_saved_search` — `GET …/device/search/{searchUUID}`: execute a saved search by UUID with `page`/`size` paging and an optional `fields` projection (Spring `PageObject` envelope re-emitted under `metadata.pagination`). Lighter-weight than `get_saved_search_results`. Read-only.
  - `refresh_saved_search_cache` — `POST …/device/search/{searchUUID}/refresh`: force a re-cache of stale results. Write (gated by `read_only=False`, idempotency-keyed); `destructiveHint=false` (recompute, not delete).
- **`list_organizations` tool (account domain).** Surfaces the `GET /orgs` Organization DTO — `tier`, `device_count`, `device_limit`, `soft_device_limit`, `parent_id`, `trial_end_time`, `uuid`, `create_time` — which the server previously fetched only internally inside `resolve_org_uuid` and never exposed to the model. Unlocks MSP/multi-org navigation, feature-tier checks, capacity posture, and trial-expiry warnings. Read-only. (#91, category H)
- **`policy_execution_counts` tool (policy_history domain).** Wraps `GET /policy-history/policies` (the policy index) for fleet-wide per-policy run counts over a `start_time`/`end_time` window in one round-trip — the "which policies ran most last quarter?" view. Distinct from `policy_run_count` (single aggregate) and `policy_runs_for_policy` (per-run records for one policy). Read-only. (#91, category I)
- **`summary_only` argument on `policy_runs_for_policy`.** When `true`, each run is projected to `{policy_uuid, run_time, execution_token, run_count}` and `banner_stats` is dropped — a token-efficient way to enumerate execution tokens for a policy with many runs. Defaults to `false`, so existing callers and stats-driven workflows are unaffected. (#91, category J)
- **Do Not Disturb honoring surfaced in policy summaries.** `summarize_policies` now projects `installation_do_not_disturb_honored` and `reboot_do_not_disturb_honored`, and `describe_policy` promotes them into a top-level `dnd_honored` block when present, so an LLM can answer "did the policy patch/reboot, or did macOS Do Not Disturb / Windows Focus block it?" without raw-dumping the policy. (The flag is `installation_do_not_disturb_honored` per the `CustomPolicy` DTO — not `install_…` as the tracking issue stated — and these flags live on the policy config, not on run-result records, so `describe_policy_run_result` is intentionally unchanged.) (#91, category F)
- **Anthropic Software Directory submission collateral.** Standalone `PRIVACY.md`, `CONTRIBUTING.md`, and `CODE_OF_CONDUCT.md` at the repo root, promoted from inline README content / Contributor Covenant by reference, ahead of the MCPB Desktop Extension listing.
- **CI manifest-consistency gate.** New `manifests` job in `.github/workflows/ci.yml` asserts that `pyproject.toml`, `server.json` (both `.version` and `.packages[].version`), `mcpb/manifest.json`, and `mcpb/pyproject.toml` (including the `automox-mcp>=` dependency floor) all carry the same version on `main`. The release workflow already rewrites these at publish time; this gate prevents drift from reaching `main` between releases.
- **MCPB schema validation in CI.** The new `manifests` job also runs `mcpb validate mcpb/manifest.json` and a smoke `mcpb pack mcpb /tmp/automox-mcp-ci.mcpb` so manifest-schema or pack-time regressions fail PR review instead of release.

### Fixed

- **`docs/tool-reference.md` table-of-contents drift.** TOC link claimed "Vulnerability Sync (7 tools)" while the section header and actual `@server.tool` count are 6. Realigned to 6.

## [1.1.0] - 2026-05-28

### Fixed

- **`get_device_by_uuid` was calling a non-existent path and silently returning empty results (#92).** The tool previously hit `GET /server-groups-api/v1/organizations/{org_uuid}/server/{device_uuid}`, which is not documented in any upstream OpenAPI spec revision (verified against `ax-console-bundle.yaml` and the 2026-05-08 `console-api.yaml`). The live tenant returned `200` from a Spring catch-all route with an empty Page wrapper (`{"content": [], "pageable": {…}, "total_elements": 0}`) regardless of the device UUID, so the tool appeared to succeed while never returning a real device. Existing unit tests passed only because the stubbed fixture was a hand-authored device dict that bypassed the wire response shape. Switched to the canonical `GET /servers/{device_uuid}?o={org_id}` endpoint — the upstream spec types `id` as `integer/int64` but the live tenant accepts UUIDs and returns the real device detail (`agent_version`, `compliant`, `last_refresh_time`, etc.). The unit-test fixture has been replaced with the real `/servers/{uuid}` response shape so future drift will fail loudly.

### Changed

- **Version-strategy realignment to strict SemVer.** Going forward, releases that add new tools, workflows, modules, or endpoint wrappers bump the MINOR version; bug fixes, performance work, internal refactors, and documentation updates bump PATCH. Several recent releases that added new capability surface (notably #80/#84 saved-search CRUD + bulk policy assignment, and #81 Splashtop Remote Control module) shipped as PATCH bumps under the previous cadence; this `1.1.0` realigns the version with the actual capability footprint ahead of broader directory distribution. The `get_device_by_uuid` bug fix above ships alongside the realignment.
- **In-tree version alignment.** `server.json`, `mcpb/manifest.json`, and `mcpb/pyproject.toml` (including the `automox-mcp>=` dependency floor) had drifted to `1.0.19` while `pyproject.toml` was at `1.0.36`. The release workflow overrides these at build time, so the drift never reached published artifacts — but reading the repo was misleading. All in-tree versions are now `1.1.0`.
- **MCPB manifest copy refreshed.** `mcpb/manifest.json` `long_description` was stale (claimed 80 tools across 18 domains; actual is 97 tools across 18 domains, with the Splashtop Remote Control module now included). The `read_only` user-config description has been corrected from "Disable all 22 write operations. 58 read tools remain available." to "Disable all 32 write operations. 65 read tools remain available." Pre-directory-submission copy hygiene.

## [1.0.36] - 2026-05-28

### Added

- **Splashtop Remote Control module (#81)** — Wraps all ten `/remotecontrol-st/...` endpoints Automox shipped on 2026-01-14 (Splashtop partnership GA). Endpoint paths, request/response shapes, and parameter enums are sourced verbatim from the [`AutomoxCommunity/openapi-defs`](https://github.com/AutomoxCommunity/openapi-defs/blob/main/openapi/bundles/ax-console-bundle.yaml) authoritative spec — no guessing.
  - **Module name:** `splashtop` (load via `AUTOMOX_MCP_MODULES=splashtop,...`).
  - **Read-only tools (always registered):** `splashtop_device_status`, `splashtop_session_status`, `splashtop_get_attended_access`.
  - **Write tools (gated by `read_only=False`, `destructiveHint: true`):** `splashtop_install`, `splashtop_bulk_install_uninstall`, `splashtop_initiate_connection`, `splashtop_force_disconnect`, `splashtop_set_attended_access`, `splashtop_set_bulk_attended_access`, `splashtop_uninstall`.
  - **Important semantics:** `splashtop_initiate_connection` returns a `splashtop-sos://...` deeplink — the API does NOT start the session. The operator's local Splashtop RMM App handles the URL, and end-user consent still applies when attended access is enabled on the device. The tool description and response both surface this.
  - **Entitlement model:** Remote Control Core is bundled with Automate Enterprise; Resolve is a paid add-on. Tenants without either return upstream 4XX, which the shared client surfaces as `AutomoxApiError`.
  - **Permission:** No separate API scope; standard Automox API key with the operator's RBAC `Devices: Control` (or `Remote Control Deployment: Manage` for bulk) permissions per the [Splashtop QSG](https://docs.automox.com/product/Product_Documentation/Remote_Control_Module/Splashtop_QSG.htm). No operator MFA per the API contract.
  - Pydantic schemas validate the `os_family`, `connection_type`, `request_permission`, `accountType`, and `action` enums verbatim from the OpenAPI spec.
  - Total tool count: 87 → 97 (65 read-only + 32 write). README, SECURITY.md, deployment-security.md, tool-reference.md, `discover_capabilities`, and `_VALID_MODULES` all updated.

## [1.0.35] - 2026-05-28

### Added

- **Saved-search CRUD + bulk policy assignment for the Advanced Device Search API (#80)** — Automox shipped 23 new Device Explorer endpoints on 2025-12-11; this release exposes the saved-search composition surface most useful for agentic workflows. Eight new tools register under the `device_search` module:
  - Read-only (always registered): `get_saved_search`, `get_saved_search_results`, `get_cached_search_results`, `get_search_scopes`.
  - Write (gated by `read_only=False`): `create_saved_search`, `update_saved_search`, `delete_saved_search`, `assign_policies_to_saved_search`.
  - Pydantic schemas validate query payload size (50 KB cap, matching `advanced_device_search`), enforce at-least-one-field on partial update, and reject empty `policy_ids` arrays. Write tools carry MCP Tool Annotations with `destructiveHint: true` and use the standard idempotency-key envelope.
  - Total tool count: 79 → 87 (62 read-only + 25 write). `discover_capabilities` and `docs/tool-reference.md` reflect the new surface.

## [1.0.34] - 2026-05-28

### Performance

- **Parallel pagination for device-list workflows (#69)** — `summarize_device_health`, `list_device_inventory`, and `search_devices` previously paginated `/servers` serially, costing one upstream RTT per page; on multi-page tenants the loop dominated wall time. New shared helper `automox_mcp.utils.pagination.parallel_paginate` fetches page 0 serially (fast path for single-page tenants), then fans out subsequent pages via `asyncio.gather` in batches of `concurrency` (default 4 for exhaustive aggregation, 2 for filter-and-limit workflows). Results are walked in strict page order; short pages and `on_page` early-stop signals discard any prefetched pages after the terminator (offset pagination makes them empty or racily inconsistent).
  - **Empirical speedup on a 5-page query against the live tenant: 4 parallel pages = 1.21s vs 4.49s serial (3.7×).** The full `summarize_device_health` workflow at `limit=50` (5 pages) ran in ~2.0s vs ~5s serial-projected.
  - 12 new helper tests cover single-page, exact-multiple-of-page-size, off-by-one termination, short-page-discards-batch-tail, on_page early stop, strict page-order invariant under out-of-order completion, concurrency bound, gather-with-failure, and boundary conditions (`max_pages=0`, `max_pages=1`, empty page 0).
  - No behavior change for callers: response shape and the canonical pagination metadata block are unchanged.

## [1.0.33] - 2026-05-28

### Changed

- **Scheduled-windows `date` schema accepts the standard ISO 8601 surface (#78)** — `GetGroupScheduledWindowsParams.date` and `GetDeviceScheduledWindowsParams.date` previously rejected any ISO 8601 string with milliseconds or a timezone offset (e.g., `2026-05-28T00:00:00.000Z`, `2026-05-28T00:00:00+00:00`), which are the default outputs of `datetime.isoformat()` in Python and `Date.toISOString()` in JavaScript. Loosened the regex to `^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2}(\.\d{1,9})?)?(Z|[+-]\d{2}:\d{2})?)?$` so the schema matches what callers actually emit. Added a `description` to both fields documenting a known upstream Automox API bug (issue #78): the `/policy-windows/.../scheduled-windows` endpoints currently reject every `date` format including the one documented in their own error message — omit the parameter unless tenant-specific scoping is required. New parametrized schema tests cover the accepted formats and reject obvious garbage.
- **`audit_events_ocsf` tool description documents the dual-permission requirement** — per the Automox API change log entry of 2025-10-27, the upstream OCSF audit endpoint now requires the calling API key to have BOTH `organization:manage` and `users:read` scopes; keys missing either scope return 403. The tool description now surfaces that requirement so callers can provision the right key without hitting a runtime 403.

## [1.0.32] - 2026-05-27

### Changed

- **`policy_runs_v2` now provides `next_page` + `suggested_next_call` (#76)** — Previously the filtered-pagination branch emitted `metadata.pagination.has_more=true` without telling the caller how to fetch the rest, forcing an LLM to infer "call with `page=current_page+1`" from raw counters. That diverged from `policy_catalog`'s richer contract. Now matches `policy_catalog`: when `has_more=True`, the response includes `pagination.next_page` and a top-level `metadata.suggested_next_call` with the exact tool name and args (carrying through the original filter parameters). On the last page neither hint is emitted, so the LLM knows there's nothing more to fetch. Surfaced by `tests/exploratory_sweep.py`.

### Fixed

- **Documentation corrections — tool names + counts** —
  - `docs/tool-reference.md` documented the wrong follow-up tool names in the compound-tool contract (`get_prepatch_report`, `get_noncompliant_report`), the same bug that landed in production code with v1.0.27 / v1.0.26 and was fixed in v1.0.30 but never propagated to the doc. Updated to the registered names (`prepatch_report`, `noncompliant_report`).
  - Tool-count drift across `README.md`, `SECURITY.md`, and `docs/deployment-security.md`: "22 write tools" → 21; "all 80 tools" → 79; "57 of 79 tools remain" → 58; "58 of 80" → 58 of 79. Reflects the actual surface: 79 total, 58 read-only, 21 write.

## [1.0.31] - 2026-05-27

### Changed

- **Prompts teach the compound-tool contract (#67)** — `prepare_patch_tuesday` and `review_security_posture` now document the `detail_limit` parameter, the `metadata.section_summaries.<key>` shape, and the follow-up-tool dispatch pattern (which detail tool to call for each truncated section, and to use the `follow_up_args_hint` rather than guessing args). The compound-tool contract shipped across v1.0.26 / v1.0.27 / v1.0.30, but the prompts that drive these tools didn't teach how to use it — LLMs were learning the contract by reading the response only after potentially losing fidelity. Now the contract is taught up-front so the LLM can ask for `detail_limit=0` when it only wants the headline counts, or call the follow-up tool proactively when the user wants full detail. Two new regression tests assert each prompt mentions `detail_limit`, `section_summaries`, and `follow_up_tool`.

## [1.0.30] - 2026-05-27

### Fixed

- **Compound tools' `follow_up_tool` dispatch pointed at non-existent tool names** — Both `get_patch_tuesday_readiness` and `get_compliance_snapshot` emitted `metadata.section_summaries.<key>.follow_up_tool = "get_prepatch_report"` / `"get_noncompliant_report"` when their inner lists were truncated. The actual registered tool names are `prepatch_report` and `noncompliant_report` (no `get_` prefix). Every LLM that followed the contract's own dispatch hint received `Unknown tool` errors at exactly the moment it tried to recover from a truncated section. The compound-tool contract shipped in v1.0.26 / v1.0.27 (#53) was broken at its most important UX point. Surfaced by the new exploratory sweep harness (`tests/exploratory_sweep.py`). Added a regression test that registers the entire tool surface and asserts every `follow_up_tool` emitted by a compound response resolves to a known tool name.

### Added

- **`tests/exploratory_sweep.py`** — Persona-driven exploratory probe harness that exercises ~50 tool calls across 8 operator personas (patch admin, security analyst, fleet manager, policy operator, vuln manager, webhook admin, device drill-down, maintenance windows) plus safe-write probes with auto-cleanup. Reports PASS / ANOMALY / FAIL per probe. Manual debugging harness (not CI). Ships alongside `tests/verify_reported_bugs.py` and `tests/smoke_production.py`.

## [1.0.29] - 2026-05-27

### Fixed

- **`get_noncompliant_report` dropped devices past the first page (#68)** — The pagination loop terminated when `len(device_list) >= summary["total"]`. A live-tenant probe (138 devices, page size 10) confirmed that `summary["total"]` on `/reports/needs-attention` is the **per-page device count**, not a total-fleet count — every page reported `total: 10`. With the workflow's hardcoded page size of 500, any tenant with more than 500 non-compliant devices would receive only the first 500 silently. Removed the early-break and rely on empty-page termination (the same pattern `get_prepatch_report` already documents). Also fixed `data.total_devices` to use the accumulated device count instead of `summary["total"]`. A regression test exercises the auto-pagination path with two full-sized pages.

## [1.0.28] - 2026-05-27

### Fixed

- **Write tools no longer lock out retries on transient failure (#65)** — When a write tool (`execute_device_command`, `apply_policy_changes`, `clone_policy`, `delete_policy`, `decide_patch_approval`, `execute_policy_now`, `create_data_extract`, `create_webhook`, `update_webhook`, `delete_webhook`, `test_webhook`, `rotate_webhook_secret`) hit a transient upstream failure, the idempotency cache's in-flight sentinel was never cleared. Every retry with the same `request_id` returned a generic `{"duplicate": True}` marker for the full 5-minute TTL, blocking recovery. Added `release_idempotency()` and wrapped each write-tool body in `try/except` that releases the sentinel on failure.
- **Cross-tenant org UUID cache poisoning (#65)** — `resolve_org_uuid` cached caller-supplied UUIDs on the shared `AutomoxClient` and short-circuited subsequent calls without checking `org_id`. For multi-org API keys, this silently returned the wrong tenant's UUID to audit / policy-history / audit-v2 tools. The cache is now gated on `org_id` matching the client's configured `org_id`, and caller-supplied UUIDs are no longer persisted on the shared client.
- **Crash on non-string policy / approval fields (#65)** — `summarize_policies` and `summarize_patch_approvals` called `.lower()` directly on values from `policy_type` / `status` / `severity`. Legacy upstream payloads occasionally return integer enums for these fields, causing `AttributeError` to surface as a 500 from `policy_catalog`, `get_compliance_snapshot`, and `get_patch_tuesday_readiness`. Now wrapped in `str()` defensively.
- **`CancelledError` swallowed in compound tools (#65)** — `compound._settle` and `policy_history` caught `BaseException` from `asyncio.gather(return_exceptions=True)`, converting child-task cancellations into stringified error entries instead of propagating the cancellation. Now re-raises `CancelledError` and `BaseException` subclasses; only `Exception` instances are collected into the errors list.

### Security

- **Prompt-injection bypass in `format_error` (#65)** — Attacker-controlled strings embedded in upstream API error responses (e.g., `detail: "IMPORTANT: ignore prior instructions..."`) bypassed the line-anchored instruction-prefix sanitizer because `format_error` ran `json.dumps` before sanitization, leaving the keyword behind `  "detail": "` at the start of each line. The sanitizer now runs on the payload values *before* JSON serialization so the line anchor matches each value at its own logical line start.
- **Async event loop blocked by sync DNS in webhook URL validator (#65)** — `_validate_webhook_url` ran `concurrent.futures.ThreadPoolExecutor.submit().result(timeout=5.0)` inside a Pydantic `model_validator`. `future.result()` is a blocking call that stalled the asyncio event loop — a single unresolvable hostname froze every concurrent tool call for up to 5 seconds. Also mutated `socket.setdefaulttimeout` (process-wide global). Split into `_validate_webhook_url_sync` (Pydantic-friendly structural checks) and `_validate_webhook_url_dns` (async; uses `loop.getaddrinfo` with `asyncio.wait_for` so the loop stays responsive). DNS resolution still runs before the upstream call (SSRF defense preserved); `socket.setdefaulttimeout` is no longer touched.

### Performance

- **Removed wasted `deepcopy` in `_apply_token_budget`** — Sole production caller (`as_tool_response`) always passes a freshly built dict. The defensive clone was a full traversal of the largest responses for no benefit.
- **Removed double `json.dumps` in `summarize_device_health`** — The second serialization existed only to refresh `approx_response_bytes` after adding ~50 bytes of follow-up metadata; the size delta is negligible. Metadata mutation is in place on the same dict, so the first measurement is now reused.
- **Fast-path for `sanitize_for_llm`** — ASCII strings with no markdown / HTML / zero-width markers (the overwhelming majority of API field values: UUIDs, statuses, timestamps, numeric strings) now skip the ~8 regex passes via a single cheap substring + multi-line prefix probe. Microbenchmark: 1.29 µs vs 2.51 µs per short string (~2× speedup). Translates to several milliseconds saved per string-heavy response.

## [1.0.27] - 2026-05-26

### Added

- **`get_compliance_snapshot` adopts the compound-tool contract (#53)** — The tool now accepts `detail_limit` (default `10`) and caps `data.noncompliant_report.devices` and `data.device_health.stale_devices` per the contract from v1.0.26. Truncated sections surface `metadata.section_summaries.<key>` with `follow_up_tool` (`get_noncompliant_report`, `device_health_metrics`) and `follow_up_args_hint` (including `group_id` when set). The `stale_devices` summary reads `metadata.stale_device_count` from `summarize_device_health` so the reported total reflects the true fleet count, not just what fit in the per-section cap.
- **`get_device_full_profile` adopts the compound-tool contract (#53)** — The tool now accepts `detail_limit`. When omitted it falls back to the legacy `max_packages` parameter (default `25`), preserving existing callers. The `packages.packages` list is capped at the effective limit; `metadata.section_summaries.packages.packages` surfaces `total`, `returned`, `has_more`, and `follow_up_tool="list_device_packages"` with `follow_up_args_hint={"device_id": ...}`. The legacy `data.packages.truncated` / `data.packages.note` fields are retained for backwards-compat. Inventory remains server-side summarized (counts + key-values per category) because its upstream payload is dict-structured, not a flat list.
- **`build_section_summary` / `build_section_summary_notes` helpers in `automox_mcp.utils.response`** — The per-section truncation block (`total` / `returned` / `has_more` / `follow_up_tool` / `follow_up_args_hint`) is now built by a shared helper instead of duplicated across the three compound workflows. `build_section_summary_notes` builds the LLM-facing `metadata.notes` strings.

## [1.0.26] - 2026-05-26

### Added

- **`get_patch_tuesday_readiness` — proof-of-shape for the compound-tool contract (#53)** — The compound tool used to embed full inner lists (`prepatch_report.devices`, `patch_approvals.approvals`, `patch_policy_schedules`) verbatim, which routinely exceeded the 4000-token response budget on tenants of any meaningful size and triggered arbitrary truncation. The tool now accepts a `detail_limit` parameter (default `10`) that caps every inner list. Counts and aggregates (`total_devices_needing_patches`, `pending_count`, `readiness_summary`) are always returned in full; truncated sections surface a per-section entry under `metadata.section_summaries.<key>` with `total`, `returned`, `has_more`, and a `follow_up_tool` / `follow_up_args_hint` pointing at the underlying detail tool (`get_prepatch_report`, `patch_approvals_summary`, `policy_catalog`). `metadata.notes` carries an LLM-friendly hint per truncated section. `detail_limit=0` returns a pure summary with empty previews. This establishes the contract; `get_compliance_snapshot` and `get_device_full_profile` will follow in subsequent releases.
- **Compound tools section in `docs/tool-reference.md`** — Documents the `detail_limit` parameter, the `metadata.section_summaries` shape, and the follow-up-tool dispatch pattern.

## [1.0.25] - 2026-05-26

### Added

- **Canonical `metadata.pagination` block across all paginated tools (#52)** — Every tool that returns multiple records now exposes pagination state under one canonical key with a stable field vocabulary: `page`, `page_size`, `total_elements`, `total_pages`, `has_more`, and `next_cursor` (the latter when cursor-based). Offset-paginated tools (`policy_catalog`, `policy_runs_v2` filtered path, `search_policy_windows`, `get_device_assignments`, `policy_run_results`) emit the page-style core; cursor-paginated tools (`audit_trail_user_activity`, `audit_events_ocsf`, `list_webhooks`) emit the cursor-style core. A generic pagination loop can now read `metadata.pagination.has_more` and either increment `page` or pass `metadata.pagination.next_cursor` to the next call without per-tool special-cases. Pre-#52 locations (e.g. `metadata.current_page`, `metadata.total_count`, `metadata.limit`, `data.total_elements`, `data.total_pages`, `data.next_cursor`, `metadata.next_cursor`, `metadata.last_event_cursor`) are retained as legacy aliases for backwards-compat — prefer the canonical block in new code.
- **`build_pagination_metadata` helper in `automox_mcp.utils.response`** — Central helper used by every paginated workflow to construct the canonical block. Derives `total_pages` from `total_elements` and `page_size` when both are known, and derives `has_more` from page/page_size/total_elements when not passed explicitly. Tool-specific extras (Spring `first`/`last`/`offset`/`sort`, legacy `current_page`/`limit`/`total_count`/`returned_count` aliases) can be merged in via the `extra` keyword.
- **Cross-tool contract test (`tests/test_pagination_contract.py`)** — Every migrated workflow is now exercised against the canonical-fields contract so future tools cannot regress to per-tool shapes without breaking CI.

## [1.0.24] - 2026-05-26

### Fixed

- **`policy_catalog` pagination stalled past page 2 at `limit=10` (#57.1)** — The wrapper over-fetched `min(limit*3, 500)` from `/policies` while passing the user's `page` directly, so the upstream offset was `page * (limit*3)` instead of `page * limit`. With `limit=10, page=3` against a 79-policy tenant the wrapper asked upstream for offset 90, got zero results, and still reported `has_more=true` (computed from the stats-derived total). The over-fetch and multi-page walk are gone: user `page` and `limit` now map 1:1 to upstream `/policies` params. A page may return fewer than `limit` active policies when some entries on that page are inactive and `include_inactive=False`, but the cursor remains correct and `has_more` reflects the actual upstream state.

- **`policy_runs_v2` silently ignored `policy_name` and `policy_type` filters (#57.2)** — Verified directly against the upstream `/policy-history/policy-runs` endpoint: the policy-report-api list endpoint silently ignores **every** filter query parameter (`policy_name`, `policy_uuid`, `policy_type`, `start_time`, `end_time`, `result_status`) regardless of param casing (`snake_case`, `camelCase`, or short forms). The wrapper now applies filters client-side after fetching a large pool (up to 5000 runs, matching the schema cap). `policy_name` matches as a case-insensitive substring; `policy_type` and `policy_uuid` match exactly; `start_time`/`end_time` filter on `run_time`; `result_status` is reinterpreted against the aggregated counter model (include runs where the named counter — `success`/`failed`/`pending`/`not_included`/`remediation_not_applicable`/`blocked`, plus `failure`/`successful` aliases — is non-zero). When any filter is active, `metadata.filter_strategy="client_side"`, `metadata.filters_applied`, `metadata.upstream_pool_size`, `metadata.filtered_count`, and a `metadata.pagination` block (`page`, `limit`, `total_count`, `has_more`) describe the local pagination. Pagination is pass-through when no filter is set.

- **`policy_catalog` truncated the `policies` array because `policy_stats` filled the budget (#57.3)** — Every response auto-fetched `/policystats` and embedded the full per-policy stats array under `data.policy_stats`. On the verified tenant, this 79-entry array consumed ~80% of the 4000-token response budget, leaving the `policies` array truncated to whatever fit. One real policy was invisible across ~20 catalog queries because the truncation always cut the alphabetical slot before reaching it. `policy_stats` is now opt-in via `include_stats=true` (default `false`); callers needing the per-policy compliance breakdown can use the dedicated `policy_compliance_stats` tool. `metadata.notes` includes a hint when stats are omitted. `total_policies_available` (derived from the stats payload) is now only present when `include_stats=true`.

### Added

- **Upstream HTTP observability** — The `AutomoxClient._request` path now emits one structured log line per upstream call with `method`, `path`, `status`, `latency_ms`, `correlation_id`, and (on 429/5xx) `retry_after`. Network failures (`httpx.RequestError`) log the exception type and elapsed time. The previous DEBUG line is retained. No retry policy is introduced; this is groundwork for diagnosing the intermittent multi-minute hangs reported in #57 issue 4.

### Security

- **Bump `idna` floor to 3.15 (CVE-2026-45409)** — `idna.encode()` could consume disproportionate CPU on arbitrarily long inputs (`"٠" * N`, `"・" * N + "漢"`), enabling a DoS. The original 2024 fix (CVE-2024-3651) was incomplete; the 3.15 fix extends the early length-rejection to lesser-used per-label conversions and codec helpers. Constrained via `tool.uv.constraint-dependencies`. (Closes the same CVE that dependabot PR #58 addressed; that PR can be closed once this lands.)
- **Bump `starlette` floor to 1.0.1 (PYSEC-2026-161)** — Starlette reconstructed the requested URL from the HTTP `Host` header without validating its value, allowing path injection into the host portion. Routing still uses the actual request path, so the inconsistency can lead to authentication bypass when auth depends on the reconstructed URL. Constrained via `tool.uv.constraint-dependencies` (alongside the existing `urllib3` floor). Affects the HTTP/SSE transport path; stdio transport is unaffected.

## [1.0.23] - 2026-05-07

### Fixed

- **`get_device_assignments` leaked Spring `Page<T>` envelope (#43)** — The `/server-groups-api/v1/organizations/{uuid}/assignments` endpoint returns a Spring page wrapper with `content`, `pageable`, `total_elements`, `number_of_elements`, `sort`, `first`, `last`, etc. The wrapper passed the response through `_extract_list`, which has no special-case for Spring pages and fell through to wrapping the *entire* envelope as a single record — leaking `pageable`/`total_elements`/`number_of_elements` into `data.assignments[0]`. The wrapper now extracts `content` explicitly and re-emits Spring pagination data under `metadata.pagination` in the project's canonical shape (`page`, `page_size`, `total_elements`, `total_pages`, `page_number`, `offset`, `sort`, `first`, `last`).

- **`get_patch_tuesday_readiness` truncation flag was ambiguous (#43)** — When the token-budget enforcer truncated multiple lists inside a dict-shaped `data` payload, `metadata.total_available` was the *sum* across all truncated lists, hiding which array had which count. The verified tenant case showed `metadata.total_available=8`, `metadata.truncated=true`, but `data.patch_policy_schedules` had only 4 entries — the `8` was actually the sum of two separate truncations. The token-budget code now emits a per-key `metadata.truncations` map (`{"patch_policy_schedules": {"total": 8, "returned": 4}, ...}`) so callers see exactly what was shrunk and to what. `total_available` is retained as the cross-array sum for backwards-compat.

- **`get_action_set_detail` returned no enrichment beyond the list summary (#43)** — Both the list and detail endpoints used the same summarizer, which looked for top-level `name`, `issue_count`, `action_count`, `solution_count` fields that the Automox API does not emit at the top level. The user-visible name lives under `source.name`, and per-bucket counts live under `statistics.issues.{type}.count` / `statistics.solutions.{type}.count`. The summarizer now flattens these: it pulls `name` out of `source`, sums per-bucket `issue_count` / `solution_count` from `statistics`, surfaces `matched_device_count` from `statistics.devices.matched_count`, and exposes the raw `statistics` block for callers that need per-bucket detail. Tool output expanded from 5 keys to ~13.

- **`policy_history_detail` had no run history despite the description (#43)** — The tool description promised "run history and status" but the implementation only fetched `/policy-history/policies/{uuid}` (top-level policy metadata). It now also fetches `/policy-history/policy-runs/{uuid}` concurrently via `asyncio.gather` and merges a summarized `recent_runs` list (capped via the new `recent_runs_limit` parameter, default 25), `total_runs_returned`, and `banner_stats` into the response. The runs sub-call is best-effort: if it fails, the detail still returns and `metadata.runs_fetch_error` carries the error message.

## [1.0.22] - 2026-05-07

### Fixed

- **`devices_needing_attention` returned all-null diagnostic fields (#43)** — The wrapper looked for snake_case fields (`device_id`, `server_group_id`, `last_check_in`, `policy_status`, `pending_updates`) that the `/reports/needs-attention` endpoint does not return. The endpoint emits camelCase Automox console fields (`id`, `groupId`, `lastRefreshTime`, `compliant`, `policies`), so every device came back with `policy_status=null`, `pending_patches=null`, `last_check_in=null`, `server_group_id=null`. Field mapping corrected. The bogus `pending_patches` field (no per-device patch count exists in this endpoint) was replaced with `failing_policies_count` and a compact `failing_policies` summary derived from the `policies` list. Added `needs_reboot`, `os_family`, `connected` for context. The legacy snake_case fallback path is retained for backwards-compatibility with hypothetical future API shapes.

- **`policy_run_results` ignored `result_status` filter (#43)** — The Automox `/policy-history/policies/{policy_uuid}/{exec_token}` endpoint silently ignores the `result_status` query parameter (verified live: `result_status`, `resultStatus`, and `status` all return the unfiltered set). The wrapper was forwarding it and trusting the upstream filter. Now the filter is applied **client-side** after the page is fetched, and the metadata block surfaces this with `result_status_filter.applied = "client_side"`, pre/post counts, and a note explaining that `pagination` counts reflect the unfiltered upstream response. Pagination across pages still works; the caller just sees fewer results per page when the filter excludes most of them.

- **`audit_trail_user_activity` cursor advance was ambiguous when filter excluded the page (#43)** — When an actor filter was applied and the page returned 0 matches but `next_cursor` was set, callers had no way to distinguish "actor was inactive" from "actor's events live on later pages of the org-wide stream." The org-wide audit endpoint does not filter by actor — the wrapper does it client-side after fetching — so a cursor with 0 returned events meant "keep paginating," not "stop." Callers stopped, silently missing later events. The metadata now surfaces `filter_pagination_state` with `no_matches_in_page`, `more_pages_available`, `events_in_unfiltered_page`, and an explicit `advice` string when this state arises. The data shape is unchanged; the new key is additive.

- **`policy_health_overview` sample size mismatch was not surfaced (#43)** — `total_policy_runs` (from `/policy-history/policy-run-count?days=N`) honors the requested window, but `/policy-history/policy-runs` is server-capped at the most recent ~100 events (≈last 24h) regardless of `limit`, `days`, or `start_time`/`end_time` parameters. So `total_runs_considered < total_policy_runs` is the *normal* state for active orgs, not a math error. The wrapper now sets `data.sample_is_truncated`, mirrors it in `metadata.sample_is_truncated`, and includes a `metadata.sample_note` explaining the cap when truncation is detected. The numerical fields are unchanged.

## [1.0.21] - 2026-05-06

### Fixed

- **`policy_run_detail_v2` failed with `org=null` (#43)** — The wrapper around `/policy-history/policies/{policy_uuid}/{exec_token}` did not forward the org UUID as a query parameter, despite a stale comment claiming the endpoint extracted org context from the JWT. The Automox policy-report API rejected every call with `400 Invalid or missing org from query parameters org=null`. The org UUID is now resolved and threaded through alongside the existing filter params (`sort`, `result_status`, `device_name`, `page`, `limit`).
- **Scheduled-windows date param rejected as malformed (#43)** — `get_group_scheduled_windows` and `get_device_scheduled_windows` passed the `date` value through `httpx`'s default params encoder, which percent-encoded the literal colons in `YYYY-MM-DDTHH:mm:ss` to `%3A`. The Automox `/policy-windows/.../scheduled-windows` endpoint validates the raw string and rejected the encoded form with `400 Invalid date-time format`. The query is now appended to the URL with `urllib.parse.quote(..., safe=":")` so colons survive transport intact.

### Removed

- **`get_action_set_actions` tool removed (#43)** — The wrapper hit `GET /orgs/{org_id}/remediations/action-sets/{action_set_id}/actions`, but that endpoint is `POST`-only (it creates actions; `OPTIONS` confirms `Allow: POST`). There is no read endpoint for actions in the Automox public API. Every call returned `405 Method Not Allowed`. Use `get_action_set_issues` and `get_action_set_solutions` for the related read data. Tool count drops from 80 to 79 (read-only tool count drops from 58 to 57).

## [1.0.20] - 2026-04-29

### Added

- **MCPB Desktop Extension** — `automox-mcp` is now installable as a one-click [MCPB (MCP Bundle)](https://github.com/modelcontextprotocol/mcpb) Desktop Extension. Claude Desktop users can drag the `automox-mcp-1.0.20.mcpb` archive (attached to this GitHub Release) into Settings → Extensions instead of editing JSON config files. The bundle is a uvx shim — `manifest.json` + a one-line Python entry point + a `pyproject.toml` that pins `automox-mcp>=1.0.20` — so source code is not bundled and `uv` pulls the matching PyPI release on first run. The install form prompts for API key (sensitive), Account UUID, Org ID (optional), and a read-only mode toggle.

### Changed

- **Release workflow now publishes to three channels.** Every `v*` tag now publishes to PyPI (Sigstore-signed, with SBOM), to the MCP Registry under the DNS-verified `com.automox/automox-mcp` namespace, and as a `.mcpb` archive attached to the GitHub Release. v1.0.20 is the first release exercising the latter two paths in CI.

## [1.0.19] - 2026-04-28

### Changed

- **Official designation** — `automox-mcp` is now the official Automox MCP server. Support remains community-driven via [GitHub Issues](https://github.com/AutomoxCommunity/automox-mcp/issues) and the Automox Community; the project is not covered by Automox commercial support contracts. README, package description, and Support section updated to reflect the new status.
- **MCP Registry preparation** — Added `mcp-name: com.automox/automox-mcp` ownership marker to README in advance of publishing to the official [MCP Registry](https://registry.modelcontextprotocol.io/) under the `com.automox/` namespace.

## [1.0.18] - 2026-04-25

### Fixed

- **`get_prepatch_report` field mislabel (#28)** — The `total_org_devices` field in the response was sourced from the `/reports/prepatch` API's `total` key, which actually counts **pending patches**, not devices. Renamed to `total_pending_patches` (both in the top-level `data` and inside `summary`) to match what the value represents. This corrects the prior interpretation noted in v1.0.13 ("`total` field from API means org device count"). Callers needing a true org device count should use `device_health_metrics.total_devices` or `list_devices`.
- **`get_prepatch_report` pagination heuristic** — Removed an early-exit condition that compared `len(device_list) >= summary["total"]` to terminate pagination. Because `total` is a patch count rather than a device count, the comparison was meaningless. Pagination now relies solely on the empty-page sentinel, which already worked in practice.

## [1.0.17] - 2026-04-25

### Security

- **GHSA-jj8c-mmj3-mmgv (authlib)** — Bumped `authlib` constraint from >=1.6.6 to >=1.6.11 to fix a CSRF vulnerability in OAuth integrations using the cache parameter for state storage. Without `SessionMiddleware` tying the client to auth state, attackers could initiate an OAuth flow and trick a victim into completing it, binding the attacker's account to the victim's session

## [1.0.16] - 2026-04-16

### Security

- **Nested-bracket sanitization bypass fixed** — Updated markdown link/image regexes in `sanitize.py` to handle one level of nested brackets, preventing URL exfiltration via patterns like `[click [here]](https://evil.com)` that previously bypassed the sanitizer entirely
- **CVE-2025-71176 (pytest)** — Bumped `pytest` from >=8.2 to >=9.0.3 to fix a local privilege escalation via predictable `/tmp/pytest-of-{user}` directory names on UNIX
- **CVE-2026-40347 (python-multipart)** — Bumped `python-multipart` from >=0.0.22 to >=0.0.26 to fix a denial-of-service vulnerability when parsing crafted multipart/form-data requests with large preamble or epilogue sections

### Added

- **JWT `verify_token()` integration tests** — 9 new tests exercising the actual token verification path (valid tokens, expired tokens, wrong audience/issuer, invalid signatures, missing scopes, garbage input). Previously only JWTVerifier construction was tested
- **Schema validation tests** (`test_schemas.py`) — 34 new tests covering Pydantic model validators, field constraints, discriminated unions, payload size limits, and command injection prevention via `patch_names` regex
- **Workflow error-path tests** — 6 new tests across events, groups, reports, and packages workflows verifying `AutomoxAPIError` propagates correctly and is not silently swallowed

### Changed

- **Consolidated duplicate test infrastructure** — Moved `StubServer` and `FakeClient` into `conftest.py`, removing ~170 lines of duplicated code from 4 test files
- **Removed unnecessary `sys.path` manipulation** — Cleaned up legacy `sys.path.insert()` from `conftest.py`, `test_workflows_policy.py`, and `test_workflows_policy_crud_extended.py`

## [1.0.15] - 2026-04-11

### Added

- **Privacy Policy** — Added a Privacy Policy section to README.md covering data collection, usage, third-party sharing, and data retention, as required for the Anthropic MCP Directory submission
- **MCP Tool Annotations on all 80 tools** — Every tool now declares `readOnlyHint`, `destructiveHint`, `idempotentHint`, and `openWorldHint` per the MCP Protocol Tool Annotations schema. Read-only tools (58) are marked as safe and idempotent; write tools (22) are marked as destructive with per-tool idempotency classification. MCP clients can use these hints for confirmation dialogs and safety guardrails

### Changed

- **Tool reference documentation** — Added "Tool Safety Annotations" section to `docs/tool-reference.md` documenting the annotation schema and per-tool classification
- **Deployment security guide** — Updated Human-in-the-Loop section to reference MCP Tool Annotations for identifying write tools

## [1.0.14] - 2026-04-11

### Security

- **HTML sanitization hardened** — Replaced regex-based HTML tag filtering in `sanitize.py` with stdlib `html.parser` to properly handle malformed tags, nested content, and edge cases (resolved CodeQL `py/bad-tag-filter`)
- **5 CodeQL code-scanning alerts resolved** — Fixed weak-hashing false positive in `auth.py` (`usedforsecurity=False`), clear-text-logging false positive in `__init__.py`, and URL substring-matching false positives in tests

### Fixed

- **Release workflow idempotency** — `gh release create` now checks for an existing release first and uploads assets with `--clobber` if one exists, preventing failures on workflow re-runs
- **Release workflow PyPI check** — Skip PyPI publish step if the version already exists on PyPI, preventing `400 File already exists` errors on re-runs

## [1.0.13] - 2026-04-11

### Security

- **CVE-2026-39892 (cryptography)** — Bumped `cryptography` from 46.0.6 to 46.0.7 to fix a buffer overflow when non-contiguous buffers are passed to APIs like `Hash.update()` on Python >3.11. Added `cryptography>=46.0.7` as a direct dependency constraint.

### Fixed

- **Release workflow excessive permissions** — Moved `contents: write` and `id-token: write` from workflow-level to job-level permissions in `release.yml`, following the principle of least privilege (flagged by zizmor)

## [1.0.12] - 2026-04-03

### Fixed

- **Policy report API query params** — Changed camelCase query parameters (`startTime`, `policyName`, etc.) to snake_case (`start_time`, `policy_name`) to match the policy-report-api's expected format
- **Policy runs URL path** — Corrected the URL path for fetching policy runs by policy
- **Device details org param** — Removed erroneous `org` query parameter from the device details endpoint (uses JWT for org context)
- **Response field extraction** — Fixed response field names to match actual API DTOs

## [1.0.11] - 2026-04-01

### Changed

- Applied `ruff format` to fix formatting in `src/automox_mcp/tools/__init__.py` and `tests/test_prompts.py`

### Fixed

- **MCP Scanner CI failure** — `mcp-scanner` v4.x requires the `stdio` subcommand and `--stdio-arg` (singular, repeatable) instead of `--stdio-args` (which consumed only one token, causing `automox-mcp` to be misinterpreted as a subcommand)
- **MCP Scanner arg ordering** — Moved `--analyzers` and `--format` global options before the `stdio` subcommand where the CLI parser expects them, and changed dummy `AUTOMOX_ORG_ID` from `0` to `1` to pass server validation (positive integer required)
- **MCP Scanner output parsing** — Updated the CI check script regex to match `Unsafe items:` (mcp-scanner v4.4.0 output) in addition to `Unsafe tools:`
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
