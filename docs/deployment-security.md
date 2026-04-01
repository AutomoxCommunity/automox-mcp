# Deployment Security Guide

This guide covers infrastructure-level security controls for deploying the Automox MCP server in production environments. It follows a shared responsibility model: the MCP server handles application-level security (credential management, input validation, rate limiting, audit logging); the deployer handles infrastructure security (isolation, network policy, TLS, access control).

This guide is informed by the [Wiz MCP Security Best Practices](https://www.wiz.io/blog/mcp-security-best-practices) cheat sheet. Section references (e.g., "Wiz S4") map to that document.

## Container Deployment (Recommended)

Sample `Dockerfile` following security best practices:

```dockerfile
FROM python:3.13-slim AS builder
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY src/ src/
RUN pip install --no-cache-dir uv && uv sync --frozen --no-dev

FROM python:3.13-slim
RUN groupadd -r automox && useradd -r -g automox -s /sbin/nologin automox
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"
USER automox
ENTRYPOINT ["automox-mcp"]
CMD ["--transport", "sse", "--allow-remote-bind"]
```

Key points:

- **Non-root user** (`USER automox`) — Wiz S4
- **Multi-stage build** minimizes image attack surface
- **No shell in final image** — consider `distroless` as an alternative base
- **Read-only filesystem** recommended (`readOnlyRootFilesystem: true` in pod security context)

## Kubernetes Deployment

Sample pod security configuration:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: automox-mcp
spec:
  securityContext:
    runAsNonRoot: true
    seccompProfile:
      type: RuntimeDefault
  containers:
    - name: automox-mcp
      image: your-registry/automox-mcp:latest
      securityContext:
        allowPrivilegeEscalation: false
        readOnlyRootFilesystem: true
        capabilities:
          drop: ["ALL"]
      resources:
        requests:
          cpu: "100m"
          memory: "128Mi"
        limits:
          cpu: "500m"
          memory: "256Mi"
      env:
        - name: AUTOMOX_API_KEY
          valueFrom:
            secretKeyRef:
              name: automox-credentials
              key: api-key
        - name: AUTOMOX_ACCOUNT_UUID
          valueFrom:
            secretKeyRef:
              name: automox-credentials
              key: account-uuid
        - name: AUTOMOX_ORG_ID
          valueFrom:
            secretKeyRef:
              name: automox-credentials
              key: org-id
        - name: AUTOMOX_MCP_API_KEYS
          valueFrom:
            secretKeyRef:
              name: automox-credentials
              key: mcp-api-keys
        - name: AUTOMOX_MCP_LOG_FORMAT
          value: "json"
        - name: AUTOMOX_MCP_TRANSPORT
          value: "sse"
```

Seccomp profile notes: The `RuntimeDefault` profile is sufficient for most deployments. Custom profiles can further restrict syscalls like `ptrace`, `mount`, and `clone` per Wiz S4.

### Network Policy

Restrict egress to the Automox API:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: automox-mcp-egress
spec:
  podSelector:
    matchLabels:
      app: automox-mcp
  policyTypes:
    - Egress
  egress:
    - to:
        - ipBlock:
            cidr: 0.0.0.0/0
      ports:
        - protocol: TCP
          port: 443
```

For tighter control, resolve `console.automox.com` to its IP ranges and restrict the CIDR accordingly.

## MCP Gateway Configuration

For production deployments, the server should sit behind an MCP gateway (Wiz S5):

### mTLS

The gateway should enforce mutual TLS between client and server. The `automox-mcp` server does not terminate TLS itself; use the gateway or a reverse proxy (nginx, Envoy, Caddy).

### Audit Logging

The server emits correlation IDs and structured logs. Enable `AUTOMOX_MCP_LOG_FORMAT=json` and forward logs to your SIEM. Recommended log schema fields:

- `correlation_id` — unique per tool call
- `tool_name` — which tool was invoked
- `status` — success or error
- `latency_ms` — execution time
- `timestamp` — ISO 8601

### Inline Guardrails

The gateway can inspect tool calls and responses:

- DLP sensors for redacting sensitive data
- Regex filters for known prompt-injection patterns
- The server's built-in `sanitize_for_llm()` provides a baseline; the gateway adds defense-in-depth

### Rate Limiting

The server has a built-in rate limiter (30 calls/60s) for Automox API calls, but the gateway should enforce its own per-client limits to detect runaway scripts or abuse.

The server includes a built-in `AuthRateLimitMiddleware` (V-140) that blocks client IPs after 10 failed authentication attempts (401/403) within 60 seconds for a 5-minute cool-down period. For additional defense-in-depth, the reverse proxy or gateway should also rate-limit authentication failures. Example nginx configuration:

```nginx
limit_req_zone $binary_remote_addr zone=mcp_auth:10m rate=10r/s;

server {
    location / {
        limit_req zone=mcp_auth burst=20 nodelay;
        proxy_pass http://127.0.0.1:8000;
    }
}
```

Generated API keys use 128-bit entropy (`secrets.token_hex(16)`), making brute-force infeasible. Keys shorter than 16 characters trigger a startup warning (V-144). However, operator-chosen keys configured via `AUTOMOX_MCP_API_KEYS` may have lower entropy.

### Server Allowlist

The gateway should maintain a binary allowlist of approved MCP servers by package digest. Use Sigstore verification (see [Verifying Releases](#verifying-releases)) for digest verification.

## Authentication and Authorization

### Built-in Endpoint Authentication (V-108)

The server supports Bearer-token authentication for HTTP/SSE transports. Generate a key and configure it:

```bash
# Generate a secure key
automox-mcp --generate-key

# Via environment variable (comma-separated, optional label prefix)
AUTOMOX_MCP_API_KEYS="alice:amx_mcp_abc123,bob:amx_mcp_def456"

# Or via key file (one per line, supports comments)
AUTOMOX_MCP_API_KEY_FILE=/etc/automox-mcp/keys.txt
```

When configured, all HTTP/SSE requests must include `Authorization: Bearer <key>`. Unauthenticated requests receive `401 Unauthorized`. This is transport-level authentication — it controls who may connect to the MCP endpoint, independent of the Automox API key.

### OAuth 2.1 / JWT Authentication (V-122)

For enterprise environments with an existing Identity Provider (Keycloak, Auth0, Azure AD, Okta), the server supports JWT-based authentication with automatic JWKS key rotation and RFC 9728 Protected Resource Metadata:

```bash
# Required: OIDC issuer URL
AUTOMOX_MCP_OAUTH_ISSUER="https://auth.example.com/realms/main"

# JWKS endpoint for automatic key rotation (discovered via OIDC if omitted)
# When omitted, the server fetches {issuer}/.well-known/openid-configuration
# at startup and extracts the jwks_uri from the discovery document.
AUTOMOX_MCP_OAUTH_JWKS_URI="https://auth.example.com/realms/main/protocol/openid-connect/certs"

# Audience claim — REQUIRED. Tokens MUST be issued for this audience (prevents token passthrough)
# The server will refuse to start if this is not set when JWT auth is enabled.
AUTOMOX_MCP_OAUTH_AUDIENCE="https://mcp.example.com"

# Canonical server URL — enables RFC 9728 Protected Resource Metadata at
# /.well-known/oauth-protected-resource
AUTOMOX_MCP_OAUTH_SERVER_URL="https://mcp.example.com"

# Optional: required OAuth scopes (comma-separated)
AUTOMOX_MCP_OAUTH_SCOPES="mcp:tools"

# Optional: JWT signing algorithm (default: RS256)
AUTOMOX_MCP_OAUTH_ALGORITHM="RS256"
```

When configured, the server:
- Validates JWT signatures via JWKS with automatic key rotation
- Verifies `iss` (issuer) and `aud` (audience) claims
- Checks token expiration
- Enforces required scopes
- Serves RFC 9728 Protected Resource Metadata at `/.well-known/oauth-protected-resource/<path>`
- Returns proper `WWW-Authenticate` headers with `resource_metadata` URLs on 401/403

Static API keys take precedence if both are configured.

### DNS Rebinding Protection (V-120)

The server validates `Host` and `Origin` headers on all HTTP/SSE connections to prevent DNS rebinding attacks, as required by the MCP transport specification. This is enabled by default.

```bash
# Disable DNS rebinding protection (NOT recommended for production)
AUTOMOX_MCP_DNS_REBINDING_PROTECTION=false

# Allow additional Host header values (comma-separated)
AUTOMOX_MCP_ALLOWED_HOSTS="proxy.internal:443,cdn.example.com:443"

# Allow additional Origin header values (comma-separated)
AUTOMOX_MCP_ALLOWED_ORIGINS="https://app.example.com,https://dashboard.example.com"
```

The server automatically allows the bound host:port and loopback aliases. Requests with invalid Host headers receive `421 Misdirected Request`; invalid Origins receive `403 Forbidden`.

### Security Response Headers (V-121)

All HTTP responses include security headers:
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'`
- `Cache-Control: no-store`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Permissions-Policy: microphone=(), camera=(), geolocation=()`
- `Strict-Transport-Security: max-age=63072000; includeSubDomains`

These are always enabled on HTTP/SSE transports with no opt-out (defense-in-depth).

### Recommendations by Transport

| Transport | Recommendation |
|-----------|---------------|
| `stdio` | No network exposure — suitable for local/developer use |
| `sse` / `http` (simple) | Enable `AUTOMOX_MCP_API_KEYS` for built-in auth. DNS rebinding protection is on by default. Requires `--allow-remote-bind` for non-loopback addresses |
| `sse` / `http` (enterprise) | Use `AUTOMOX_MCP_OAUTH_ISSUER` for JWT/OIDC auth with audience binding. Serves RFC 9728 metadata for MCP client discovery. Place behind TLS-terminating reverse proxy |
| Multi-user | Deploy separate server instances per API key/role, or use an MCP gateway that maps user identity to server instances |

## Human-in-the-Loop Configuration

Client-side controls that complement the server's safety features:

- Enable **confirmation dialogs** in your MCP client for all write tools (the server's 22 write tools are identifiable by the `request_id` parameter)
- Use `AUTOMOX_MCP_READ_ONLY=true` for monitoring and read-only use cases
- Use `AUTOMOX_MCP_MODULES` to load only required tool domains (principle of least functionality)
- Test new or untrusted server versions in a staging environment with `AUTOMOX_MCP_READ_ONLY=true` before production use

## Verifying Releases

Release artifacts are signed with [Sigstore](https://docs.sigstore.dev/) using GitHub's OIDC identity:

```bash
pip install sigstore
python -m sigstore verify identity \
  --cert-identity "https://github.com/AutomoxCommunity/automox-mcp/.github/workflows/release.yml@refs/tags/vX.Y.Z" \
  --cert-oidc-issuer "https://token.actions.githubusercontent.com" \
  automox_mcp-X.Y.Z.tar.gz
```

Each release also includes a CycloneDX SBOM (`sbom.cdx.json`) attached to the GitHub Release.

## Compliance Mapping

| Control | ISO 42001 | SOC 2 | GDPR Art. 32 |
|---------|-----------|-------|--------------|
| Correlation IDs / audit trail | A.6.2.3 | CC7.2 | Art. 32(1)(d) |
| Read-only mode | A.6.2.1 | CC6.1 | Art. 32(1)(b) |
| Rate limiting | A.6.2.4 | CC6.6 | Art. 32(1)(b) |
| Error sanitization | A.6.2.2 | CC6.1 | Art. 32(1)(a) |
| Structured JSON logging | A.6.2.3 | CC7.1 | Art. 32(1)(d) |

*This is guidance, not a compliance certification. Consult your compliance team for authoritative mapping.*

## Pre-Production Checklist

- [ ] API key scoped to minimum required permissions
- [ ] `AUTOMOX_MCP_READ_ONLY=true` if write operations not needed
- [ ] `AUTOMOX_MCP_MODULES` set to only required domains
- [ ] Server running as non-root in a container with dropped capabilities
- [ ] Egress restricted to `console.automox.com:443`
- [ ] TLS terminated at gateway or reverse proxy
- [ ] MCP endpoint authentication enabled — static keys (`AUTOMOX_MCP_API_KEYS`) or JWT/OIDC (`AUTOMOX_MCP_OAUTH_ISSUER`) — and/or enforced at gateway/reverse proxy
- [ ] For JWT auth: `AUTOMOX_MCP_OAUTH_AUDIENCE` set (mandatory — server refuses to start without it); issuer uses HTTPS; `AUTOMOX_MCP_OAUTH_SERVER_URL` set for RFC 9728 metadata
- [ ] API key file permissions restricted to owner only (`chmod 600`) — the server refuses world-readable files, world-writable JWT pubkey files, and raises on stat failures (V-118, V-127, V-135, V-139)
- [ ] DNS rebinding protection enabled (default) — custom origins added via `AUTOMOX_MCP_ALLOWED_ORIGINS` if needed
- [ ] Structured JSON logs (`AUTOMOX_MCP_LOG_FORMAT=json`) forwarded to SIEM
- [ ] Release artifact verified via Sigstore before deployment
- [ ] MCP client configured with confirmation dialogs for write operations
- [ ] Resource quotas (CPU/RAM) set on container
- [ ] Tool prefix configured if running alongside other MCP servers (`AUTOMOX_MCP_TOOL_PREFIX`)
- [ ] Built-in auth rate limiting active (V-140); reverse proxy adds additional rate limiting for defense-in-depth
- [ ] `AUTOMOX_MCP_ALLOW_REMOTE_BIND` set only when non-loopback binding is intentional

## References

- [Wiz: MCP Security Best Practices (Cheat Sheet)](https://www.wiz.io/blog/mcp-security-best-practices) — Industry guidance for securing MCP environments
- [OWASP Top 10 for LLM Applications](https://owasp.org/www-project-top-10-for-large-language-model-applications/) — LLM01 (Prompt Injection) is directly relevant
- [Sigstore Documentation](https://docs.sigstore.dev/) — For verifying signed release artifacts
- [MCP Specification](https://modelcontextprotocol.io/) — The protocol specification this server implements
- [MCP Security Best Practices](https://modelcontextprotocol.io/specification/2025-11-25/basic/security_best_practices) — Official MCP security guidance (session hijacking, SSRF, confused deputy, scope minimization)
- [MCP Authorization Specification](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization) — OAuth 2.1 authorization framework for MCP
