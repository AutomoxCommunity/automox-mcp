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
- Sensitive field redaction covers: `token`, `secret`, `key`, `password`, `credential`, `auth`, `bearer`, `passwd`, `api-key`, `apikey` (V-010, V-107)
- HTTP client debug logging excludes request parameters (V-005)

### Prompt Injection via API Data

Tool responses pass Automox API data back to the LLM after sanitization. The `sanitize_for_llm()` module:

- **Unicode normalization** (NFKC) and zero-width character stripping to defeat homoglyph attacks (V-108a)
- Strips inline and reference-style markdown link/image syntax that could exfiltrate data (V-117)
- Removes fenced code blocks (labelled and unlabeled) containing shell/script commands (V-119)
- Removes instruction-like prefixes from free-text fields (notes, descriptions) (V-104)
- Preserves names and tags where users commonly use words like "IMPORTANT" or "SYSTEM"
- Configurable via `AUTOMOX_MCP_SANITIZE_RESPONSES` (default: enabled)

For sensitive deployments, we recommend using an MCP gateway with inline guardrails for additional defense-in-depth.

### Privilege Escalation

- `AUTOMOX_MCP_READ_ONLY` mode disables all 22 write tools
- `AUTOMOX_MCP_MODULES` limits which tool domains load (principle of least functionality)
- Pagination capped at 50 pages to prevent resource exhaustion (V-011)
- Report limits bounded to 500 results (V-004)

### Network Exposure

- Non-loopback HTTP/SSE binding requires explicit opt-in via `--allow-remote-bind` or `AUTOMOX_MCP_ALLOW_REMOTE_BIND=true` (V-106); server exits with an error otherwise
- **DNS rebinding protection**: Origin and Host header validation on all HTTP/SSE connections per the MCP transport specification (V-120); configurable via `AUTOMOX_MCP_ALLOWED_ORIGINS` and `AUTOMOX_MCP_ALLOWED_HOSTS`
- **Security response headers** on all HTTP responses: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'`, `Cache-Control: no-store`, `Referrer-Policy`, `Permissions-Policy` (V-121)
- Built-in Bearer-token endpoint authentication for HTTP/SSE transports via `AUTOMOX_MCP_API_KEYS` or `AUTOMOX_MCP_API_KEY_FILE` (V-108); for additional defense-in-depth, an authenticating reverse proxy or MCP gateway is recommended
- **OAuth 2.1 / JWT authentication** for enterprise IdP integration (V-122): validate JWTs from external authorization servers (Keycloak, Auth0, Azure AD, Okta) with audience binding, issuer validation, and automatic JWKS key rotation; serves RFC 9728 Protected Resource Metadata at `/.well-known/oauth-protected-resource`
- Tool name prefixing (`AUTOMOX_MCP_TOOL_PREFIX`) prevents cross-server collisions
- Webhook URLs validated against private/loopback/link-local IPs and cloud metadata endpoints (Google, Azure, Oracle Cloud, generic `*.internal`) to prevent SSRF (V-103, V-114). **Accepted risk (S-001):** DNS resolution is checked at validation time but the Automox backend performs its own resolution at delivery time; a DNS rebinding attack between those two points is theoretically possible. This is inherent to the split-validation architecture and mitigated by the backend's own controls

### Denial of Service

- Rate limiter: 30 calls per 60 seconds (applies to Automox API calls, not MCP endpoint authentication)
- Token budget estimation with auto-truncation (configurable via `AUTOMOX_MCP_TOKEN_BUDGET`)
- Resource quotas (CPU/RAM) are the deployer's responsibility (see [Deployment Security Guide](docs/deployment-security.md))
- **Authentication brute-force protection (S-002):** The built-in rate limiter does not cover MCP endpoint authentication attempts. Deploy a reverse proxy with request rate limiting (e.g., nginx `limit_req`, Envoy circuit breaker) to throttle failed authentication attempts. Generated keys use 128-bit entropy (`secrets.token_hex(16)`) making brute-force infeasible, but operator-chosen keys may be weaker

## Security Features Reference

| ID | Description | Key Files |
|----|-------------|-----------|
| V-001 | Sensitive field redaction in API error payloads | `workflows/audit.py`, `utils/tooling.py` |
| V-002 | UUID type validation on webhook parameters | `tools/webhook_tools.py` |
| V-003 | HTTPS-only webhook URL enforcement | `tools/webhook_tools.py` |
| V-004 | Report limit bounds (le=500) | `schemas.py` |
| V-005 | Debug logging excludes request parameters | `client.py` |
| V-006 | Generic error messages to MCP clients | `utils/tooling.py` (`call_tool_workflow`) |
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
| V-101 | Error messages sanitized before ToolError | `utils/tooling.py` |
| V-102 | Dependabot pip ecosystem for Python deps | `.github/dependabot.yml` |
| V-103 | SSRF prevention in webhook URLs (private IP/metadata blocking) | `tools/webhook_tools.py` |
| V-104 | Expanded instruction-prefix regex (20+ patterns) | `utils/sanitize.py` |
| V-105 | Redact data at sanitization depth limit | `utils/sanitize.py` |
| V-106 | Require `--allow-remote-bind` for non-loopback binding | `__init__.py` |
| V-107 | Expanded sensitive field redaction patterns | `utils/tooling.py` |
| V-108 | MCP endpoint Bearer-token authentication for HTTP/SSE | `auth.py`, `server.py`, `__init__.py` |
| V-108a | Unicode NFKC normalization + zero-width char stripping in sanitizer | `utils/sanitize.py` |
| V-112 | Narrowed policy.py exception handler; no raw error leakage to LLM | `workflows/policy.py` |
| V-114 | Expanded cloud metadata blocklist (Azure, Oracle, *.internal) | `tools/webhook_tools.py` |
| V-117 | Reference-style markdown image/link stripping | `utils/sanitize.py` |
| V-118 | API key file permission check (block world-readable, warn group-readable) | `auth.py` |
| V-119 | Unlabeled fenced code block removal | `utils/sanitize.py` |
| V-120 | DNS rebinding protection (Origin/Host header validation) | `transport_security.py`, `__init__.py` |
| V-121 | HTTP security response headers (X-Frame-Options, CSP, etc.) | `transport_security.py` |
| V-122 | OAuth 2.1 / JWT authentication with RFC 9728 metadata | `auth.py` |
| V-123 | Reject missing Host header in DNS rebinding middleware | `transport_security.py` |
| V-124 | Sanitize ValidationError/ValueError messages before ToolError | `utils/tooling.py` (`call_tool_workflow`) |
| V-125 | Warn on non-HTTPS OAuth issuer URL (MITM risk for JWKS) | `auth.py` |
| V-126 | Best-effort DNS resolution check for webhook SSRF | `tools/webhook_tools.py` |
| V-127 | Refuse world-readable API key files | `auth.py` |
| V-128 | Literal/UUID type constraints on policy windows parameters | `tools/policy_windows_tools.py` |
| S-001 | Documented DNS TOCTOU accepted risk in webhook SSRF validation | `tools/webhook_tools.py` |
| S-002 | Documented auth brute-force rate limiting as deployer responsibility | `SECURITY.md`, `docs/deployment-security.md` |
| S-003 | Documented SENSITIVE_KEYWORDS narrowing rationale | `utils/tooling.py` |
| S-004 | UUID format validation before caching on client | `utils/organization.py` |
| S-005 | Patch names format/length validation via Pydantic | `schemas.py` |

## Scope and Limitations

This server does **not** provide:

- **Authorization / RBAC** — The server operates with a single Automox API key; multi-user access control is the gateway's responsibility. MCP endpoint authentication (V-108, V-122) controls *who may connect*, not *what they may do*. OAuth scopes can be enforced via `AUTOMOX_MCP_OAUTH_SCOPES`.
- **Authentication brute-force protection** — The server does not rate-limit authentication attempts; deploy a reverse proxy with rate limiting (S-002)
- **TLS termination** — Use a reverse proxy (nginx, Envoy, Caddy) or MCP gateway
- **Container isolation** — Run in a container with dropped capabilities and read-only filesystem
- **Egress filtering** — Restrict outbound traffic to `console.automox.com:443` at the network layer

See the [Deployment Security Guide](docs/deployment-security.md) for infrastructure-level controls.

## References

- [MCP Security Best Practices](https://modelcontextprotocol.io/specification/2025-11-25/basic/security_best_practices) — Official MCP protocol security guidance (session hijacking, SSRF, confused deputy, token passthrough, scope minimization)
- [MCP Authorization Specification](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization) — OAuth 2.1 authorization framework for MCP, RFC 9728 Protected Resource Metadata
- [Wiz: MCP Security Best Practices (Cheat Sheet)](https://www.wiz.io/blog/mcp-security-best-practices) — Industry guidance this project's security posture is benchmarked against
- [Deployment Security Guide](docs/deployment-security.md) — Infrastructure-level hardening guidance
- [OWASP Top 10 for LLM Applications](https://owasp.org/www-project-top-10-for-large-language-model-applications/) — LLM01 (Prompt Injection) is directly relevant to MCP tool security
