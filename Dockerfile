ARG BASE_IMAGE=ghcr.io/meta-pytorch/openenv-base:latest
FROM ${BASE_IMAGE} AS builder

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends git && \
    rm -rf /var/lib/apt/lists/*

# 1. Copy only dependency files first (CRITICAL for caching)
COPY pyproject.toml uv.lock* /app/env/
WORKDIR /app/env

# Ensure uv is available
RUN if ! command -v uv >/dev/null 2>&1; then \
        curl -LsSf https://astral.sh/uv/install.sh | sh && \
        mv /root/.local/bin/uv /usr/local/bin/uv; \
    fi

# 2. Install dependencies (Cached unless pyproject/uv.lock changes)
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-install-project --no-editable

# 3. Now copy the rest of the code
COPY . /app/env

# Final Sync to include the project itself
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-editable

# --- Final runtime stage ---
FROM ${BASE_IMAGE}
WORKDIR /app

# 4. FIX: Copy the WHOLE directory in one go to preserve symlinks and speed
COPY --from=builder /app/env /app/env

# 5. Update PATH and PYTHONPATH to point to the nested .venv
ENV PATH="/app/env/.venv/bin:$PATH"
ENV PYTHONPATH="/app/env:/app/env/server:$PYTHONPATH"


# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/ || exit 1

# Run the server (Updated path based on your previous logs)
CMD ["sh", "-c", "cd /app/env && uvicorn app:app --host 0.0.0.0 --port 8000"]