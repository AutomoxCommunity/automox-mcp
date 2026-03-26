# Deployment Security Guide

This guide covers infrastructure-level security controls for deploying the Automox MCP server in production environments. It follows a shared responsibility model: the MCP server handles application-level security (credential management, input validation, rate limiting, audit logging); the deployer handles infrastructure security (isolation, network policy, TLS, access control).

This guide is informed by the [Wiz MCP Security Best Practices](https://www.wiz.io/blog/mcp-security-best-practices) cheat sheet. Section references (e.g., "Wiz S4") map to that document.

## Container Deployment (Recommended)

Sample `Dockerfile` following security best practices:

```dockerfile
FROM python:3.12-slim AS builder
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY src/ src/
RUN pip install --no-cache-dir uv && uv sync --frozen --no-dev

FROM python:3.12-slim
RUN groupadd -r automox && useradd -r -g automox -s /sbin/nologin automox
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"
USER automox
ENTRYPOINT ["automox-mcp"]
CMD ["--transport", "sse"]
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

The server has a built-in rate limiter (30 calls/60s), but the gateway should enforce its own per-client limits to detect runaway scripts or abuse.

### Server Allowlist

The gateway should maintain a binary allowlist of approved MCP servers by package digest. Use Sigstore verification (see [Verifying Releases](#verifying-releases)) for digest verification.

## Authentication and Authorization

The `automox-mcp` server has no built-in authentication. Options by transport:

| Transport | Recommendation |
|-----------|---------------|
| `stdio` | No network exposure — suitable for local/developer use |
| `sse` / `http` | Place behind an authenticating reverse proxy that validates OAuth2/OIDC tokens |
| Multi-user | Deploy separate server instances per API key/role, or use an MCP gateway that maps user identity to server instances |

## Human-in-the-Loop Configuration

Client-side controls that complement the server's safety features:

- Enable **confirmation dialogs** in your MCP client for all write tools (the server's 16 write tools are identifiable by the `request_id` parameter)
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
- [ ] Authentication enforced at gateway or reverse proxy
- [ ] Structured JSON logs (`AUTOMOX_MCP_LOG_FORMAT=json`) forwarded to SIEM
- [ ] Release artifact verified via Sigstore before deployment
- [ ] MCP client configured with confirmation dialogs for write operations
- [ ] Resource quotas (CPU/RAM) set on container
- [ ] Tool prefix configured if running alongside other MCP servers (`AUTOMOX_MCP_TOOL_PREFIX`)

## References

- [Wiz: MCP Security Best Practices (Cheat Sheet)](https://www.wiz.io/blog/mcp-security-best-practices) — Industry guidance for securing MCP environments
- [OWASP Top 10 for LLM Applications](https://owasp.org/www-project-top-10-for-large-language-model-applications/) — LLM01 (Prompt Injection) is directly relevant
- [Sigstore Documentation](https://docs.sigstore.dev/) — For verifying signed release artifacts
- [MCP Specification](https://modelcontextprotocol.io/) — The protocol specification this server implements
