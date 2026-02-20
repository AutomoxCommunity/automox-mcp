# Automox MCP Server: From 18 to 36 Tools — Full Webhook Support, Group Management, and More

The Automox MCP Server just doubled its capabilities. What started as a focused set of device and policy workflows now covers the full breadth of day-to-day Automox operations — from package visibility and server group management to real-time webhook subscriptions and compliance reporting.

Here's what's new and why it matters.

---

## By the Numbers

| | Before | After |
|---|---|---|
| **Tools** | 18 | 36 |
| **Tool Domains** | 4 | 9 |
| **MCP Resources** | 4 | 5 |
| **Webhook Event Types** | 0 | 39 |
| **Configuration Options** | 3 | 5 |

---

## Webhook Management: Real-Time Event Subscriptions

The biggest addition is full webhook lifecycle management — 8 new tools that let AI assistants create, configure, test, and maintain webhook subscriptions directly through conversation.

- **Create webhooks** with specific event types and HTTPS endpoints
- **Test connectivity** before going live
- **Rotate signing secrets** when credentials need cycling
- **Browse all 39 event types** across device, policy, worklet, group, organization, and audit categories

Webhooks are the foundation of event-driven automation. With MCP support, setting up a webhook that fires when a device goes non-compliant or a policy evaluation fails is now a conversational task rather than a manual console operation.

> "Set up a webhook that notifies our Slack channel when any device goes non-compliant or disconnects for an extended period."

The assistant can look up the right event types, create the webhook, save the signing secret, and test the endpoint — all in one interaction.

---

## Server Group Management: Full CRUD

Server groups are the organizational backbone of Automox. The new group management tools bring full create, read, update, and delete operations:

- **List all groups** with device counts and policy assignments
- **Create groups** with parent hierarchies, refresh intervals, and policy bindings
- **Update and delete** groups as your organizational structure evolves

This means AI assistants can now help with fleet restructuring tasks like:

> "Create a new server group called 'Q2 Rollout' under the 'Production' group, set the refresh interval to 360 minutes, and assign the standard patch policy."

---

## Package & Patch Visibility

Two new tools provide direct visibility into the software landscape:

- **`list_device_packages`** — See exactly what's installed on a specific device, including versions, patch status, and severity ratings
- **`search_org_packages`** — Search packages across the entire organization, filtering by managed status or packages awaiting installation

These tools close the gap between "this device is non-compliant" and "here's specifically what needs patching."

---

## Compliance Reports

Two focused reporting tools provide pre-built views into fleet health:

- **`prepatch_report`** — Which devices have pending patches before the next window?
- **`noncompliant_report`** — Which devices need attention right now?

Combined with the existing `device_health_metrics` and `policy_health_overview` tools, AI assistants now have everything they need to generate comprehensive compliance reports on demand.

---

## Organization Events

The new `list_events` tool provides a filterable view into organization activity — searchable by policy, device, user, event name, and date range. It complements the existing audit trail tool by covering operational events like policy evaluations, patch installations, and device status changes.

---

## Read-Only Mode

A single environment variable — `AUTOMOX_MCP_READ_ONLY=true` — disables all 14 destructive tools, leaving 22 read-only tools available. This is designed for:

- **Audit and compliance reviews** where you want to query data without any risk of modification
- **Monitoring dashboards** that pull data through MCP
- **Demo environments** where you want to showcase capabilities safely
- **Onboarding** new team members who should observe before they operate

---

## Modular Architecture

Not every use case needs all 36 tools. The new `AUTOMOX_MCP_MODULES` environment variable lets you load only the domains you need:

```bash
# Just device and policy tools
AUTOMOX_MCP_MODULES=devices,policies

# Webhook management only
AUTOMOX_MCP_MODULES=webhooks

# Audit and reporting
AUTOMOX_MCP_MODULES=audit,reports,events
```

Fewer tools means less noise for the AI assistant, faster tool selection, and lower token usage. Both options compose naturally — `AUTOMOX_MCP_READ_ONLY=true` combined with `AUTOMOX_MCP_MODULES=devices,policies` gives you a focused, read-only device and policy dashboard.

---

## New MCP Resource: Webhook Event Types

A new static resource at `resource://webhooks/event-types` provides the complete catalog of all 39 webhook event types organized by category — device, policy, worklet, device group, organization, and audit. AI assistants can consult this resource when helping users configure webhook subscriptions, ensuring they select the right event types for their use case.

---


## Getting Started

If you're already running the Automox MCP Server, the new tools are available immediately after updating. If you're new:

```bash
uvx --env-file .env automox-mcp
```

See the [README](https://github.com/AutomoxCommunity/automox-mcp#readme) for full setup instructions, editor integrations, and configuration options.
