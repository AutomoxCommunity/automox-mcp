# Release notes (customer-facing source)

**Curated through: v2.2.0 (2026-06-08).**

## What this file is — and is not

This is a **curated, customer-safe source document** for generating outbound content — release emails, "what's new" summaries, sales talking points, in-app notes. Its primary consumer is **another Claude session** asked to produce one of those from a clean source instead of from the raw `CHANGELOG.md`.

It is **not** customer-published documentation and does not replace the product docs (customers are well served by those). It is **not** the engineering changelog: the `CHANGELOG.md` and the engineering tech feed remain the complete, authoritative record. This file is the *translation layer* — the subset of releases that carry customer value, written in customer language, with every disclosure hazard already resolved.

Two things are deliberately **absent** here and must stay absent: (1) any framing that admits a prior version was broken or returned wrong/incomplete data, and (2) any specific security or data-handling vulnerability disclosure. Those are real and tracked — in the `CHANGELOG.md` and the tech feed — but they are not customer-marketing material and are not this file's job.

## How to use this file (for a Claude session generating content)

- **"What's new since vX"** → include every release entry with version ≥ X, plus the standing *Reliability & security maintenance* section if any folded version falls in range. The entries are reverse-chronological and version-anchored, so slicing by version is direct.
- **Always carry any `Caveat:` or `Upgrade:` line** attached to an entry into the generated content — they are load-bearing (host requirements, support scope, breaking-change actions). Dropping them creates support tickets or overpromises.
- **Never reintroduce omitted detail.** Do not "enrich" an entry by pulling specifics back from the `CHANGELOG.md` — the omissions are intentional. If asked for security specifics, point to the tech feed; do not synthesize them here.
- **Counts are point-in-time.** Where an entry states a tool/resource count, it is the count *as of that release*. Do not present a historical count as the current capability.

## Authoring rules (for a Claude session adding a new release entry)

When a new version ships, add its entry at the top of the release log **only if it carries customer value**, following these rules. If it does not, it belongs in the maintenance section or is omitted — see the contributor protocol below.

1. **Audience is customer / sales / marketing.** Plain language, benefit-first. Say what the operator can now *do*, not what the code does.
2. **Forward-frame everything. Never describe a fix as a fix.** Write "device search returns precise, narrowed results" — never "search was broken" / "previously returned the whole fleet" / "fixed an issue where…". Banned vocabulary in entries: *fixed, bug, broken, was returning wrong/zero/empty/truncated data, silently dropped, no longer mis-reports*. A correctness improvement is stated as the correct behavior, in the present tense.
3. **No internal references.** Strip issue numbers (`#NN`), vulnerability IDs (`V-NNN`, `S-NNN`), CodeQL/CVE/GHSA IDs, file/function/variable names, and internal tooling names. (CVE/GHSA IDs belong only in a security advisory, never here.)
4. **No tenant or customer specifics.** No device counts, query results, or benchmark timings captured from a live tenant; no org names or IDs. A performance claim may cite a *ballpark* qualified as "in testing," never a tenant-specific measurement as a guarantee.
5. **Omit sensitive disclosures entirely.** Any item whose customer-facing meaning is "we had a security or data-handling flaw" — credential exposure, tenant-isolation, audit-integrity, auth bypass, injection — does **not** get an entry here, even forward-framed. It is covered in the `CHANGELOG.md` and tech feed. When in doubt, omit and move on.
6. **Collapse churn.** Routine reliability fixes, dependency bumps, CI/test/refactor work, and generic hardening do not get individual entries — fold them into the standing *Reliability & security maintenance* section.
7. **Attach load-bearing caveats inline** with a `Caveat:` line: host-capability requirements, support scope, and anything that would otherwise overpromise.
8. **Flag breaking changes** with an `Upgrade:` line stating the operator action in one sentence.
9. **Entry shape:** a bold headline + 1–3 sentences of customer value, an optional `Caveat:` line, an optional `Upgrade:` line, and a `[Feature]` / `[Improvement]` tag.

## Contributor protocol (keeping this ongoing)

On each release, after the `CHANGELOG.md` entry is written:

1. Decide the release's bucket: **Feature/Improvement** (gets an entry), **Maintenance** (fold into the standing section), or **Omit** (purely internal/CI, or a sensitive security/compliance fix).
2. If Feature/Improvement, add an entry at the top of the release log per the authoring rules. Use the template below.
3. If Maintenance or a partial release, add the version to the *Reliability & security maintenance* coverage list so every shipped version stays accounted for.
4. Update **Curated through:** at the top to the new version.

Every shipped version should be traceable here: either it has an entry, or it is listed under maintenance, or it is a sensitive-only release intentionally omitted (those live in the `CHANGELOG.md`). This file is referenced from the release section of `CLAUDE.md` so the step is part of the release flow.

**Template:**

```
### vX.Y.Z — <customer-facing title> (YYYY-MM-DD) [Feature|Improvement]

**<Bold headline of the customer benefit.>** <1–3 sentences: what the operator can now do and why it matters.>
Caveat: <only if a host requirement / support-scope / expectation qualifier applies.>
Upgrade: <only if a breaking change needs an operator action.>
```

---

# Release log

### v2.2.0 — Interactive in-host review surfaces (2026-06-08) [Feature]

**Review and act on fleet posture visually, right inside your AI assistant.** This release adds five interactive surfaces that render directly in supported hosts: a compliance-triage dashboard, a patch-approval queue, a policy-change blast-radius preview, a remediation-apply review, and an RBAC access-certification review. Instead of reading a wall of text, operators see compliance state, affected devices, and pending decisions laid out visually — and for action-oriented flows they can act in-session, with every change still routed through the assistant's standard confirmation before anything is written.
Caveat: The interactive surfaces require an MCP Apps–capable host; on any other assistant the same information is returned as clean structured data, so nothing is lost.

### v2.1.0 — Clearer, self-describing tool output (2026-06-06) [Improvement]

**Your AI assistant interprets device, policy, and compliance data more accurately.** Tool outputs now carry plain-language explanations of their own status codes, units, and severity values, so the assistant reads your fleet data correctly instead of inferring meaning. The result is more reliable answers about compliance state, patch readiness, and device health — with no change to how you use the tools.

### v2.0.1–v2.0.3 — Sharper device search and precise policy targeting (2026-06-02 → 2026-06-04) [Improvement]

**Advanced Device Search returns exactly the devices that match.** Filter by OS family, group, tag, or any supported attribute and get back a precise, narrowed result set; saved searches create and update dependably, including name- or description-only edits, and type-ahead responds as you build a query. Policy device-filters apply across every policy type, the policy-impact preview reports the affected-device count, and large package inventories return in full.
Caveat: Advanced Device Search is most reliable with an org-scoped API key; the credentials section of the README explains the key types.

### v2.0.0 — Capability and safety model; full published-API coverage (2026-06-01) [Feature]

**Complete, principled coverage of the Automox platform — with safety built in.** This release establishes a clear capability model: the server wraps 100% of the published Console and Webhooks APIs, with the single deliberate exception of secret-exposing endpoints, which it never calls. It adds single-device update, action-set management, installer upload to Required Software policies, and webhook-delivery troubleshooting. High-blast-radius destructive actions (fleet-scale operations, device deletion) follow a consistent, opt-in model: they are off by default and require explicit enablement, so an assistant can never trigger them by accident.
Upgrade: Operators who enabled remediation execution via the older `AUTOMOX_MCP_ALLOW_REMEDIATION` flag must switch to `AUTOMOX_MCP_ALLOW_APPLY_REMEDIATION_ACTIONS`; fleet-wide Splashtop install/uninstall now requires its own opt-in flag. If a flag is unset the capability stays safely withheld.

### v1.2.0 — Major capability expansion (2026-05-30) [Feature]

**Manage identity, access, remediation, and multi-zone policy from your assistant.** This release broadens the surface substantially: account-wide and per-user API key management; visibility into users, zones, and RBAC roles; remediation execution; bulk device tagging; cloning patch policies across zones; richer device search; organization and tier visibility; and policy-run reporting. API-key tools never return secret material.
Caveat: Remediation execution changes endpoint state and is opt-in, disabled by default.

### v1.0.36 — Splashtop Remote Control (2026-05-28) [Feature]

**Drive remote-control sessions through the integration.** Check device and session status and initiate, install, or disconnect Splashtop remote sessions from your assistant.
Caveat: Initiating a session returns a launch link rather than starting control directly, and attended access requires end-user consent — so this is not one-click remote takeover. Remote Control availability depends on your Automox entitlements; confirm current packaging before quoting specifics.

### v1.0.35 — Saved searches and bulk policy assignment (2026-05-28) [Feature]

**Reuse device searches and attach policies in bulk.** Create, update, delete, and reuse saved Advanced Device Searches, and assign policies to the devices a search returns — turning a one-off query into a repeatable targeting workflow.

### v1.0.34 — Faster fleet queries (2026-05-28) [Improvement]

**Device-health and inventory lookups return substantially faster on larger fleets** — roughly a 3–4× speedup on multi-page queries in testing, with no change to results.

### v1.0.20 — One-click install in Claude Desktop (2026-04-29) [Feature]

**Install the Automox MCP server with a drag-and-drop Desktop Extension** — no manual JSON configuration. The server is also published to PyPI and the MCP Registry.

### v1.0.19 — Official Automox MCP server (2026-04-28) [Improvement]

**Now published under Automox's verified namespace in the MCP Registry** as the official Automox MCP server.
Caveat: "Official" designates the publisher; support is community-driven and is not covered by Automox commercial support contracts. This qualifier must travel with any "official" claim.

### v1.0.15 — Per-tool safety hints (2026-04-11) [Improvement]

**Every tool declares machine-readable safety hints** — read-only vs. destructive, idempotent or not — so MCP clients can show the right confirmation prompts and guardrails before a write action runs.

### v1.0.4–v1.0.5 — Safer AI workflows (2026-03-30) [Improvement]

**Destructive AI workflows ask for confirmation before they run.** Guided workflows that could reboot or patch devices now require an explicit confirmation step, and the server enforces strong authentication and input validation throughout.

### v1.0.0 — General availability (2026-03-29) [Feature]

**Manage your fleet end to end through an AI assistant.** The GA release ships a broad tool surface — device inventory, patch readiness, policy management and cross-zone cloning, server groups, webhooks, worklet search, policy-execution and audit reporting, and maintenance-window scheduling — plus guided workflows for common tasks like Patch Tuesday prep, non-compliant-device investigation, policy-history audits, and security-posture review. It is enterprise-ready out of the box: OAuth 2.1 / JWT and bearer-token authentication, a read-only mode for audit and reporting use cases, and security hardening throughout. API key and webhook secrets are never exposed to the assistant.
Caveat: Connecting requires an MCP-capable host (such as Claude Desktop or another MCP client).

### v0.1.0 — First release (2025-11-13) [Feature]

**The first Automox MCP server.** Initial release letting you query and manage devices, policies, account information, and audit data through an AI assistant — the foundation the GA release built on.

---

# Reliability & security maintenance (standing)

Between the milestones above, Automox MCP receives continuous reliability and security maintenance: broader and more accurate pagination so large fleets return complete results, faster fleet queries, clearer report and data formatting, machine-readable safety hints on every tool, host-confirmation prompts before destructive workflows, and regular dependency updates to stay current with upstream security patches. Specifics — individual fixes, security details, and any operator-relevant change — are tracked in the `CHANGELOG.md` and the engineering tech feed.

**Coverage note (for traceability — not customer-facing copy):** the following shipped versions are folded into this maintenance section or intentionally omitted as internal-only / sensitive-security releases, and have no standalone entry above: v2.0.0's plumbing sub-items, v1.2.1, v1.1.0, v1.0.33, v1.0.32, v1.0.31, v1.0.30, v1.0.29, v1.0.28, v1.0.27, v1.0.26, v1.0.25, v1.0.24, v1.0.23, v1.0.22, v1.0.21, v1.0.18, v1.0.17, v1.0.16, v1.0.14, v1.0.13, v1.0.12, v1.0.11, v1.0.10, v1.0.9, v1.0.8, v1.0.7, v1.0.6, v1.0.3, v1.0.2, v1.0.1. (v1.0.21 removed a non-functional tool — an operator-facing detail tracked in the `CHANGELOG.md`.) Sensitive security/compliance fixes across the 1.0.x and 2.0.x series are deliberately excluded here and documented in the `CHANGELOG.md` and tech feed.
