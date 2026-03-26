# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| Latest on `main` | Yes |
| Previous releases | No |

## Reporting a Vulnerability

If you discover a security vulnerability in this project, please report it responsibly:

1. **Email** security@automox.com with a description of the vulnerability, steps to reproduce, and any relevant logs or screenshots.
2. **Do not** open a public GitHub issue for security vulnerabilities.
3. **Expected response**: We target acknowledgment within 3 business days and aim to resolve critical CVEs within 7 days and high-severity issues within 30 days.

## Threat Model Summary

The following attack surfaces have been identified and mitigated:

### Supply Chain (Rug-Pull Updates)

- Dependencies pinned via `uv.lock`
- Bandit static security analysis runs in pre-commit hooks
- 90% test coverage enforced in CI
- GitHub Actions pinned to immutable SHA digests
- Dependabot configured for automated dependency updates
- Sigstore-signed releases with CycloneDX SBOM (SLSA Build Level 1)

> **Note**: SLSA Build Level 3+ provenance (hermetic builds) is planned but not yet implemented.

### Credential Exposure

- API key stored as private attribute (`_api_key`), injected per-request via httpx auth callback (V-001)
- Generic error messages prevent key leakage in stack traces (V-006)
- Webhook secrets stripped from idempotency cache after create/rotate (V-012)
- Sensitive field redaction covers: `token`, `secret`, `key`, `password`, `credential`, `auth` (V-010)
- HTTP client debug logging excludes request parameters (V-005)

### Prompt Injection via API Data

Tool responses pass Automox API data back to the LLM after sanitization. The `sanitize_for_llm()` module:

- Strips markdown link and image syntax that could exfiltrate data
- Removes fenced code blocks containing shell/script commands
- Removes instruction-like prefixes from free-text fields (notes, descriptions)
- Preserves names and tags where users commonly use words like "IMPORTANT" or "SYSTEM"
- Configurable via `AUTOMOX_MCP_SANITIZE_RESPONSES` (default: enabled)

For sensitive deployments, we recommend using an MCP gateway with inline guardrails for additional defense-in-depth.

### Privilege Escalation

- `AUTOMOX_MCP_READ_ONLY` mode disables all 16 write tools
- `AUTOMOX_MCP_MODULES` limits which tool domains load (principle of least functionality)
- Pagination capped at 50 pages to prevent resource exhaustion (V-011)
- Report limits bounded to 500 results (V-004)

### Network Exposure

- Non-loopback binding warning logged when using HTTP/SSE transport (V-003)
- No built-in authentication — an authenticating reverse proxy or MCP gateway is required for non-local deployments
- Tool name prefixing (`AUTOMOX_MCP_TOOL_PREFIX`) prevents cross-server collisions

### Denial of Service

- Rate limiter: 30 calls per 60 seconds
- Token budget estimation with auto-truncation (configurable via `AUTOMOX_MCP_TOKEN_BUDGET`)
- Resource quotas (CPU/RAM) are the deployer's responsibility (see [Deployment Security Guide](docs/deployment-security.md))

## Security Features Reference

| ID | Description | Key Files |
|----|-------------|-----------|
| V-001 | Sensitive field redaction in API error payloads | `workflows/audit.py`, `utils/tooling.py` |
| V-002 | UUID type validation on webhook parameters | `tools/webhook_tools.py` |
| V-003 | HTTPS-only webhook URL enforcement | `tools/webhook_tools.py` |
| V-004 | Report limit bounds (le=500) | `schemas.py` |
| V-005 | Debug logging excludes request parameters | `client.py` |
| V-006 | Generic error messages to MCP clients | All `tools/*.py` modules |
| V-007 | AUTOMOX_ORG_ID validated as positive integer | `server.py` |
| V-008 | Narrowed exception handlers in policy workflows | `workflows/policy.py` |
| V-009 | PolicyDefinition rejects unknown fields | `schemas.py` |
| V-010 | Broad sensitive field redaction patterns | `utils/tooling.py` |
| V-011 | Pagination capped at 50 pages | `workflows/policy.py`, `workflows/reports.py` |
| V-012 | Webhook secrets stripped from cache | `tools/webhook_tools.py` |
| V-013 | Error text truncated to 500 chars | `client.py` |
| V-014 | Token budget parsing with fallback | `utils/tooling.py` |
| V-015 | Module name validation | `utils/tooling.py` |
| V-016 | Audit payload redaction | `workflows/audit.py` |
| V-017 | .gitignore covers .env variants | `.gitignore` |
| V-018 | Webhook URL validation with urlparse | `tools/webhook_tools.py` |

## Scope and Limitations

This server does **not** provide:

- **Authentication** — Deploy behind an authenticating reverse proxy or MCP gateway
- **Authorization / RBAC** — The server operates with a single API key; multi-user access control is the gateway's responsibility
- **TLS termination** — Use a reverse proxy (nginx, Envoy, Caddy) or MCP gateway
- **Container isolation** — Run in a container with dropped capabilities and read-only filesystem
- **Egress filtering** — Restrict outbound traffic to `console.automox.com:443` at the network layer

See the [Deployment Security Guide](docs/deployment-security.md) for infrastructure-level controls.

## References

- [Wiz: MCP Security Best Practices (Cheat Sheet)](https://www.wiz.io/blog/mcp-security-best-practices) — Industry guidance this project's security posture is benchmarked against
- [Deployment Security Guide](docs/deployment-security.md) — Infrastructure-level hardening guidance
- [OWASP Top 10 for LLM Applications](https://owasp.org/www-project-top-10-for-large-language-model-applications/) — LLM01 (Prompt Injection) is directly relevant to MCP tool security
