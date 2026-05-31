# API Coverage & Intentional Omissions

This document records what the Automox MCP server deliberately does **not** expose, and the policy that governs destructive operations. It exists so that a coverage gap is never ambiguous: every documented Automox Console API operation is either wrapped, tracked for build, or intentionally omitted here with a rationale.

Audited against the Automox Console API OpenAPI bundle (`ax-console-bundle.yaml`, version `2026-05-28`): **115 documented operations**. Coverage verified by registering the server and reading the live tool set, not by reading prose. Undocumented-but-wrapped paths (endpoints the live tenant serves that the spec omits) are tracked separately in [#95](https://github.com/AutomoxCommunity/automox-mcp/issues/95) and are **not** coverage gaps.

The server exposes 130 tools (84 read / 46 write). Effectively every documented **read** operation is covered; the omissions below are all writes, deletes, or secret-exposing endpoints.

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
| `apply_remediation_actions` | `AUTOMOX_MCP_ALLOW_REMEDIATION` | **(C)** `patch-with-worklet` runs a model-selected worklet (arbitrary script) on endpoints; a confirmation dialog can't convey the payload. (Triggering a *human-built* worklet policy via `execute_policy_now` stays Tier 1 — a human vetted that payload.) |
| `splashtop_bulk_install_uninstall` | `AUTOMOX_MCP_ALLOW_REMOTE_CONTROL` | **(A)** one call installs/uninstalls the Splashtop client across an entire server group. |

### Omitted on destructive grounds

| Omitted | Operation | Rationale |
|---|---|---|
| `deleteDevice` | `DELETE /servers/{id}` | **(B)** destroys the device record and its history — not reconstructable through the MCP — and there is no create-device counterpart (agents self-register), so it fails the value test. Documented rather than gated. If a concrete need arises, it would ship gated, not ask-first. |

---

## 3. Build backlog

The documented-surface build items from [#111](https://github.com/AutomoxCommunity/automox-mcp/issues/111) are now **covered**:

| Operation | Tool | Tier |
|---|---|---|
| `PUT /servers/{id}` (`updateDevice`: `custom_name`, `server_group_id`, `exception`, `tags`, `ip_addrs`) | `update_device` | **Not destructive** — plain write, no gate. Fills the single-device-update hole `batch_update_devices` (tags only) doesn't cover. |
| `DELETE /orgs/{org}/remediations/action-sets/{id}` (`deleteActionSet`) | `delete_action_set` | Tier 1 ask-first (reconstructable via re-upload) |
| `DELETE /orgs/{org}/remediations/action-sets` (`deleteActionSetsBulk`) | `delete_action_sets_bulk` | Tier 1 ask-first (console metadata, not endpoint state) |

**Implementation note — `delete_action_sets_bulk`:** implemented by iterating the single-delete endpoint (`DELETE /…/action-sets/{id}`) rather than the native bulk endpoint (`DELETE /…/action-sets`), whose request-body shape is undocumented in the OpenAPI bundle and was unverifiable at build time. Deletion is non-atomic (per-ID results; a mid-list failure leaves earlier deletes applied — safe, since action sets are re-uploadable). **Actionable follow-on:** confirm the native bulk-delete contract (rendered docs or a console cURL capture) and swap to a single round-trip — tracked as a perf optimization, not a coverage gap.

Remaining uncovered documented surface (binary/multipart uploads) is tracked in [#106](https://github.com/AutomoxCommunity/automox-mcp/issues/106).

---

## Not a gap — redundant

| Operation | Why |
|---|---|
| `GET /policy-history/policies/{policy_uuid}/runs` (`policyExecutionHistory`) | Returns `{policy_id, policy_uuid, run_time, execution_token}` — the exact data already surfaced by `policy_runs_for_policy` with `summary_only=true` (DTO-verified). |
