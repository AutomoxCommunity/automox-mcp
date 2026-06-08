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

### MCP App write-flows

Interactive MCP App UIs (the `io.modelcontextprotocol/ui` extension; see `docs/tool-reference.md`) that drive a write are **review surfaces over an existing write tool — not a new tool and not a new gate.** The UI calls the underlying tool by name through the host's `CallTool` bridge, so the write inherits that tool's tier verbatim: the host confirmation dialog (Tier 1) or env flag (Tier 2) fires exactly as it does for a direct call. The patch-approval review App (`ui://automox/patch-approval.html`) drives the Tier-1 `decide_patch_approval`, and the policy blast-radius review App (`ui://automox/policy-blast-radius.html`) re-invokes the Tier-1 `apply_policy_changes` with `preview=false`; in read-only mode those write tools are not registered, so the Apps degrade to view-only. The remediation-apply review App (`ui://automox/remediation-apply.html`) drives the **Tier-2** `apply_remediation_actions` (patch-now) — and because that tool is registered only when `AUTOMOX_MCP_ALLOW_APPLY_REMEDIATION_ACTIONS` is set, the App's apply is inert until the env gate is on (the review remains usable). The App deliberately does **not** offer `patch-with-worklet` — that arbitrary-code path (trigger C) stays a direct, explicitly-constructed tool call. When adding a write-flow App, pick the entry/write tool by its existing tier here — do **not** add a parallel gate for the App.

**Bridge-reuse security invariants.** Reusing the existing gated write tool via the host `CallTool` bridge is the *safer* architecture — it inherits read-only-mode de-registration, idempotency (`request_id`), and `destructiveHint` annotations, all of which a new `@app.tool()` backend would bypass. But the destructive gate is **host-consent-driven** (there is no in-tool confirm token), so every write-flow App must hold:

1. **Host mediation.** An App→host `CallTool` on a `destructiveHint: true` tool must trigger the *same* host consent as a model-issued call; it must **not** auto-execute. Otherwise the sole human checkpoint for a patch/remediation write is lost.
2. **Review-↔-execute fidelity.** The bridge call must be built from the *same vetted data shown in the App review*, and the consent prompt should display the real params. App HTML renders tenant-controlled strings, so a "reviewed ≠ executed" decoupling is the worst-case bug. Concretely: keep the write-App client JS **minimal and `eval`-free**, and derive the `CallTool` params **only from vetted/escaped data** (the structured payload the App reviewed), never by re-parsing rendered HTML or interpolating raw tenant strings into the call. This — not a CSP knob — is the real defense against a tampered-payload write.
3. **CSP — deny-all, with a higher bar to loosen.** Write-App `ui://` resources stay **deny-all**: an empty `ResourceCSP`, no added allowed domains — the same floor as the read-only triage pilot, and the strictest setting the mechanism can express. (Verified against FastMCP 3.2.0: `ResourceCSP` is **domain-only** — `connect_domains`/`resource_domains`/`frame_domains`/`base_uri_domains` are origin source-lists that *add* origins to the host's directives; it exposes no `'unsafe-inline'`/`'unsafe-eval'`/nonce control, so the host owns the inline-script policy and there is nothing stricter to set.) The bar to **loosen** is higher for a write-App than for a read-only one: any domain addition needs explicit security justification, because a write-App's UI both *displays the data under review* and *triggers a privileged write* — a relaxed `connect-src` is an exfiltration/tamper channel. Never add a domain the review doesn't strictly need.

The shipped Apps (#179–#181) satisfy these: the apply payload is built from the reviewed structured data (the rendered approval id / the captured `operations` / the rendered solution + its devices) — never re-parsed from HTML — the client JS is `eval`-free and escapes every value before `innerHTML`, the bridge issues a host-mediated `tools/call` with no auto-execute, and each App ships an empty (deny-all) `ResourceCSP`.

**Access certification (#182) — write-side reality.** Review is fully supported: `list_users` surfaces `account_rbac_roles` / `rbac_roles`. Acting on findings is **partial**, and for three distinct reasons (do not conflate them):

- **Role change** — *no tool.* `update_user` is profile-only (firstname/lastname/email/tfa_type; password is deliberately excluded); a user's RBAC role is settable only at invite time via `invite_user_to_account(account_rbac_role=...)`. This is a true API gap.
- **Membership revoke** — *exists, gated, but unreachable.* `remove_user_from_account` is Tier-1 but **UUID-keyed**, and no sanctioned listing surfaces the account-user UUID (`list_users` / `get_user` project numeric `id`). Blocked on the UUID-listing gap ([#193](https://github.com/AutomoxCommunity/automox-mcp/issues/193)).
- **API-key revocation** — *fully wireable today, numeric-keyed:* `list_users` → `list_user_api_keys(user_id)` → `update_user_api_key(is_enabled=False)` / `delete_user_api_key`.

So #182 ships read-only by **deliberate scope choice** — **not** because "the API has no write." API-key revocation is deferred to a fast-follow ([#192](https://github.com/AutomoxCommunity/automox-mcp/issues/192)); role change is an API gap; membership revoke is blocked on the UUID gap ([#193](https://github.com/AutomoxCommunity/automox-mcp/issues/193)).

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

## API key behavior — Advanced Device Search family (mechanism unconfirmed)

Account/global API keys behave **inconsistently** on the Server Groups API v2 search endpoints; org-scoped keys work reliably. Observed live (an earlier revision of this section claimed the endpoints flatly "only accept org-scoped keys" — that was an overclaim, falsified a day later by the same key working in one org):

| Key | When | Org(s) | Result |
|---|---|---|---|
| Account key (full admin, freshly issued) | day 1 | every org it could see | `403`, uniform |
| Org-scoped key (freshly issued) | day 2 | its org | `200` immediately, correct results |
| Same account key, untouched | day 2 | the org where the org key had been used | `200` |
| Same account key, untouched | day 2 | three other orgs | `403` |

Not explained by: key type alone, key age/propagation alone, the owner's org membership (member of all orgs), or any visible per-org role difference. One candidate is lazy per-org provisioning in the search service triggered by a successful org-key access — unconfirmed; raised with the platform team. Affected tools:

`advanced_device_search`, `device_search_typeahead`, `create_saved_search`, `update_saved_search`, `delete_saved_search`, `list_saved_searches`, `list_searches_for_device`, `get_device_assignments`

Other `/server-groups-api/` endpoints (`get_searchable_fields` / metadata, `list_devices_for_policies`) accepted the account key throughout — the inconsistency is endpoint-level, not family-wide. Classic v1 endpoints (`/servers`, `/policies`, …) accept either key type.

**Operational guidance (stands regardless of mechanism):** use an org-scoped key — the README setup instructions say so. A `403` on these tools while reads work elsewhere usually means the key, not the user's permissions.

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
