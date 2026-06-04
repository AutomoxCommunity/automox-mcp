# API Coverage & Intentional Omissions

This document records what the Automox MCP server deliberately does **not** expose, and the policy that governs destructive operations. It exists so that a coverage gap is never ambiguous: every documented Automox Console API operation is either wrapped, tracked for build, or intentionally omitted here with a rationale.

Audited against the Automox Console API OpenAPI bundle (`ax-console-bundle.yaml`, version `2026-05-28`): **115 documented operations**. Coverage verified by registering the server and reading the live tool set, not by reading prose. Undocumented-but-wrapped paths (endpoints the live tenant serves that the spec omits) are tracked separately in [#95](https://github.com/AutomoxCommunity/automox-mcp/issues/95) and are **not** coverage gaps.

The server exposes 133 tools (85 read / 48 write). Effectively every documented **read** operation is covered; the omissions below are all secret-exposing endpoints (every documented write/delete/upload is now either wrapped or gated).

The **Webhooks API** is a *separate* published OpenAPI document (`Automox Webhooks API` v1.0.0), not part of the Console API bundle above. The server now wraps **all 9** of its paths — see [Webhooks API coverage](#webhooks-api-coverage) below. Taken together, the server can assert it wraps **100% of the published Automox Console API and Webhooks API**, with the single deliberate exception of secret-exposing endpoints (Section 1).

## Three categories

Everything the server chooses not to do falls into one of three buckets:

1. **Secrets** — never handled, in or out. Permanent.
2. **Destructive** — exposed under a two-tier safety policy (ask-first vs. gated), or omitted when neither tier is appropriate.
3. **Everything else** — a build backlog, tracked as issues.

---

## 1. Secrets — never handled

**Principle: the server never returns secret material and never lets the model set it.** Credentials enter only via environment/config (`AUTOMOX_API_KEY`, etc.) and are never logged, persisted, or echoed back through a tool. The model can neither read a secret nor write one.

This is permanent policy, not a backlog item. It unifies several decisions:

| Omitted / guarded | Operation | Rationale |
|---|---|---|
| `decryptOrganizationApiKey` | `POST /users/{userId}/api_keys/{id}/decrypt` | Returns a live plaintext API key. Never wrapped. |
| `decryptGlobalApiKey` | `POST /global/api_keys/{keyId}/decrypt` | Returns a live plaintext account-scoped key. Never wrapped. |
| `FullUpdateUserById` | `PUT /users/{userId}` | Full-replace body accepts `password`/`password1`/`password2`/`tfa_type` — an account-takeover write. We wrap the `PATCH` variant (`update_user`) instead, with password fields stripped. |
| (field redaction) | User DTO `intercom_hmac`, Zone DTO `access_key` | Secret fields are redacted from every projection that would otherwise surface them. |

API-key **metadata** (list/create/get/update) is wrapped — only the secret material is off-limits.

---

## 2. Destructive operations — a two-tier policy

Most destructive operations **are** exposed; the server already ships create/update/delete tools across policies, webhooks, groups, saved searches, API keys, windows, users, and remote-control actions. The question for each is *how* it is exposed.

**Meta-principle: gate (require an explicit, default-off env flag) only when per-call human confirmation cannot meaningfully protect the operator.** Otherwise, rely on the host client's confirmation dialog.

### Tier 1 — Ask-first (default on, subject to `AUTOMOX_MCP_READ_ONLY`)

Single-target, human-vettable, recoverable destructive or real-world actions. Each carries `readOnlyHint: false` and `destructiveHint: true`, so a compliant host surfaces a confirmation dialog. The human in the loop is genuinely sufficient.

Examples: `delete_policy`, `delete_webhook`, `delete_server_group`, `delete_saved_search`, `delete_*_api_key`, `delete_policy_window`, `delete_action_set`/`delete_action_sets_bulk` (reconstructable via re-upload), `remove_user_from_account`, `execute_policy_now` (triggers a human-curated policy), `execute_device_command` (one device), `splashtop_install`/`uninstall`/`force_disconnect` (one device; `force_disconnect` is fully reversible — reconnect).

**Reversibility and disruption are handled here, not by gating.** A reboot is disruptive but recoverable and single-target → confirm, don't gate.

### Tier 2 — Gated (default-off env flag)

An operation is gated when confirmation is insufficient because it is:

- **(A) Uncontainable by scale** — acts across many endpoints in one call by design; the operator can't meaningfully reason about the blast radius from a confirmation prompt.
- **(B) Unrecoverable / self-lockout** — removes your own ability to manage or recover the endpoint afterward; there is no undo and no remote path back in.
- **(C) Opaque / arbitrary** — model-authored code execution on endpoints, where confirming the call doesn't reveal what will actually run.

Note: *bulk alone is not a gate.* `batch_update_devices` is bulk but only applies tags (reversible metadata) → Tier 1. The gate is bulk **and** destructive/real-world.

| Tool | Flag | Trigger |
|---|---|---|
| `apply_remediation_actions` | `AUTOMOX_MCP_ALLOW_APPLY_REMEDIATION_ACTIONS` | **(C)** `patch-with-worklet` runs a model-selected worklet (arbitrary script) on endpoints; a confirmation dialog can't convey the payload. (Triggering a *human-built* worklet policy via `execute_policy_now` stays Tier 1 — a human vetted that payload.) |
| `splashtop_bulk_install_uninstall` | `AUTOMOX_MCP_ALLOW_SPLASHTOP_BULK_INSTALL_UNINSTALL` | **(A)** one call installs/uninstalls the Splashtop client across an entire server group. The flag name mirrors the tool: it gates *deploying/removing the client software* fleet-wide, not starting remote-control sessions (`splashtop_initiate_connection`, which is not env-gated). |
| `delete_device` | `AUTOMOX_MCP_ALLOW_DELETE_DEVICE` | **(B)** `DELETE /servers/{id}` destroys the device record and its history — not reconstructable through the MCP, and there is no create-device counterpart (agents self-register), so a wrongly deleted record has no MCP-side undo. Per-call confirmation cannot restore it. |

### Omitted on destructive grounds

None currently. `deleteDevice` (`DELETE /servers/{id}`) was the sole candidate and, after verified demand ([#123](https://github.com/AutomoxCommunity/automox-mcp/issues/123)), now ships **gated** behind `AUTOMOX_MCP_ALLOW_DELETE_DEVICE` (category B above) — not ask-first, consistent with the earlier statement that if a concrete need arose it would ship gated.

---

## 3. Build backlog

The documented-surface build items from [#111](https://github.com/AutomoxCommunity/automox-mcp/issues/111) are now **covered**:

| Operation | Tool | Tier |
|---|---|---|
| `PUT /servers/{id}` (`updateDevice`: `custom_name`, `server_group_id`, `exception`, `tags`, `ip_addrs`) | `update_device` | **Not destructive** — plain write, no gate. Fills the single-device-update hole `batch_update_devices` (tags only) doesn't cover. |
| `DELETE /orgs/{org}/remediations/action-sets/{id}` (`deleteActionSet`) | `delete_action_set` | Tier 1 ask-first (reconstructable via re-upload) |
| `DELETE /orgs/{org}/remediations/action-sets` (`deleteActionSetsBulk`) | `delete_action_sets_bulk` | Tier 1 ask-first (console metadata, not endpoint state) |

**Implementation note — `delete_action_sets_bulk`:** wraps the native bulk endpoint `DELETE /…/action-sets` with a JSON body `{"ids": [...]}` (schema `delete-action-set`, `console-api.yaml` `2026-05-08`; responds `204`) — a single atomic call.

**Multipart uploads ([#106](https://github.com/AutomoxCommunity/automox-mcp/issues/106)) — both covered:**

| Operation | Tool | Status |
|---|---|---|
| `POST /orgs/{org}/remediations/action-sets/upload` (`uploadRemediationCSV`) | `upload_action_set` | **Covered.** `AutomoxClient.post_multipart` now sends real `multipart/form-data`. Contract confirmed live 2026-05-31: `source` is a **query param** (enum); the body carries `file` + `format` (same enum). The earlier 500 was `source` sent as a form field with an empty query string. CSV arrives as inline `csv_content` text — no SSRF/file-read surface. |
| `POST /policies/{policyID}/files` (`uploadPolicyFile`) | `upload_policy_file` | **Covered, gated, local-only.** Required-Software installer upload (up to 10 GB). Mechanism decision: **`file_path`** (server reads a local file) — `base64` is impractical at GB scale and `file_url` was rejected (would require building SSRF defense from scratch for marginal value). Confined by: env-gate `AUTOMOX_MCP_ALLOW_UPLOAD_POLICY_FILE` (default off) + a required directory allowlist `AUTOMOX_MCP_UPLOAD_ALLOWED_DIRS` (paths canonicalized; `..`/symlink escape rejected) + **stdio-only** (the tool isn't registered under a remote transport, and `main()` refuses to start a remote transport while the flag is on). The installer streams to Automox and never passes through the model. |

---

## API key scope requirement — Advanced Device Search family

The Server Groups API v2 search endpoints **only accept org-scoped API keys**; a global/account-scoped key gets a uniform `403` regardless of the caller's role (verified live 2026-06-04: global-admin account key → 403 on every org; org-scoped key → 200 with correct results on the same org). Affected tools:

`advanced_device_search`, `device_search_typeahead`, `create_saved_search`, `update_saved_search`, `delete_saved_search`, `list_saved_searches`, `list_searches_for_device`, `get_device_assignments`

Other `/server-groups-api/` endpoints (`get_searchable_fields` / metadata, `list_devices_for_policies`) **do** accept either key type — the restriction is endpoint-level, not family-wide. Classic v1 endpoints (`/servers`, `/policies`, …) accept either. The README setup instructions recommend an org-scoped key for this reason. A `403` on these tools is a key-scope symptom, not a permissions/role problem — re-issue the key at the org level.

(Automox's public docs don't state this restriction as of 2026-06-04 — the global-keys doc's permission-inheritance language suggests the opposite.)

---

## Webhooks API coverage

The Webhooks API (`Automox Webhooks API` v1.0.0) is published as a **separate** OpenAPI document from the Console API bundle. It defines 9 paths; the server now wraps **all of them**:

| Path | Tool |
|---|---|
| `GET /webhooks/event-types` | `list_webhook_event_types` |
| `GET /organizations/{org_uuid}/webhooks` | `list_webhooks` |
| `POST /organizations/{org_uuid}/webhooks` | `create_webhook` |
| `GET /organizations/{org_uuid}/webhooks/{id}` | `get_webhook` |
| `PUT /organizations/{org_uuid}/webhooks/{id}` | `update_webhook` (uses `PATCH` — see below) |
| `DELETE /organizations/{org_uuid}/webhooks/{id}` | `delete_webhook` |
| `POST /organizations/{org_uuid}/webhooks/{id}/test` | `test_webhook` |
| `POST /organizations/{org_uuid}/webhooks/{id}/secret/rotate` | `rotate_webhook_secret` |
| `GET /organizations/{org_uuid}/webhooks/{id}/deliveries` | `list_webhook_deliveries` |

**No webhook DTO returns secret material.** The signing secret is write/rotate-only — surfaced once on `create_webhook`/`rotate_webhook_secret` and never returned by any read. The `DeliveryLog` projection (`id, eventType, success, statusCode, error, durationMs, timestamp`) carries no credentials.

**Spec drift (cross-ref [#95](https://github.com/AutomoxCommunity/automox-mcp/issues/95)):** the doc documents the update operation as `PUT`, but `update_webhook` issues a `PATCH` (partial update) — which the live API accepts. Tracked with the other API-team spec gaps.

---

## Not a gap — redundant

| Operation | Why |
|---|---|
| `GET /policy-history/policies/{policy_uuid}/runs` (`policyExecutionHistory`) | Returns `{policy_id, policy_uuid, run_time, execution_token}` — the exact data already surfaced by `policy_runs_for_policy` with `summary_only=true` (DTO-verified). |
