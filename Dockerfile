FROM python:3.13-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /build

RUN pip install --no-cache-dir build

COPY pyproject.toml uv.lock ./
COPY src ./src

RUN python -m build --wheel --outdir dist

FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AUTOMOX_MCP_TRANSPORT=http \
    AUTOMOX_MCP_HOST=0.0.0.0 \
    AUTOMOX_MCP_PORT=8000

RUN useradd --create-home --shell /usr/sbin/nologin automox && mkdir -p /app && chown automox:automox /app

WORKDIR /app

COPY --from=builder /build/dist/automox_mcp-*.whl /tmp/
RUN pip install --no-cache-dir /tmp/automox_mcp-*.whl \
    && rm /tmp/automox_mcp-*.whl

USER automox

# Use the project CLI entry point; override args at runtime if needed.
CMD ["automox-mcp", "--transport", "http", "--host", "0.0.0.0", "--port", "8000", "--allow-remote-bind"]
