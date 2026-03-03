# ────────────────────────────────────────────────────────────────────────────
# Stage 1 — builder
# Install all Python dependencies into an isolated virtual environment.
# Keeps the final image free of build-time tooling.
# ────────────────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# Create a virtual environment outside WORKDIR for a clean copy to runtime.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy the package manifest and source, then install everything.
# Doing both copies before pip install lets Docker cache the install layer
# independently of source-only changes.
COPY pyproject.toml .
COPY src/ ./src/

RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir .

# ────────────────────────────────────────────────────────────────────────────
# Stage 2 — runtime
# Lean image: venv from builder + application source only.
# ────────────────────────────────────────────────────────────────────────────
FROM python:3.12-slim

# Non-root user for security — never run containers as root.
RUN addgroup --system aipm \
 && adduser --system --ingroup aipm --no-create-home aipm

WORKDIR /app

# Bring in the pre-built virtual environment (provides `aipm` CLI + uvicorn).
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Application source — required for templates, policy YAML files, and any
# assets resolved relative to module paths at runtime.
COPY src/ ./src/

# Create runtime I/O directories with correct ownership before switching user.
RUN mkdir -p /app/output /app/input_bundles \
 && chown -R aipm:aipm /app

USER aipm

EXPOSE 8000

# Default: start the FastAPI server.
# Override CMD to use the CLI instead:
#   docker run --rm aipm-api aipm run /app/input_bundles/my_bundle/
#   docker run --rm aipm-api aipm prompt "Build a smart notification system"
CMD ["uvicorn", "aipm.api:app", "--host", "0.0.0.0", "--port", "8000"]
