# syntax=docker/dockerfile:1.4
# Note: You can use any Debian/Ubuntu based image you want.
FROM mcr.microsoft.com/devcontainers/base:bookworm

# ============================================================================
# LAYER 1: System packages (rarely change - good for caching)
# ============================================================================
RUN apt-get update && export DEBIAN_FRONTEND=noninteractive \
    && apt-get -y install --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    curl \
    ca-certificates \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# ============================================================================
# LAYER 2: Python dependencies (change occasionally - use cache mount)
# ============================================================================
# Copy dependency files first to leverage Docker layer caching
COPY --chown=root:root pyproject.toml /tmp/
# We use a glob for the lock file so the build doesn't fail if it's missing
COPY --chown=root:root uv.lock* /tmp/

# Create a tools virtualenv and install uv into it (keeps system clean)
RUN python3 -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir --upgrade pip uv

# Add tools venv to PATH so `uv` runs from the venv
ENV PATH=/opt/venv/bin:$PATH

# Install Python packages with BuildKit cache mount for uv (no system install)
RUN --mount=type=cache,target=/root/.cache/uv \
    cd /tmp && \
    (uv sync --frozen --no-install-project 2>/dev/null || \
     uv sync --no-install-project 2>/dev/null || \
     uv pip install -r pyproject.toml) \
    && rm -f /tmp/pyproject.toml /tmp/uv.lock

# = ::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::
# LAYER 3: User configuration (The 'vscode' user already exists in base image)
# = ::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::
# We ensure the vscode user is in the docker group
RUN groupadd docker || true \
    && usermod -aG docker vscode

# ============================================================================
# LAYER 4: Environment and runtime configuration
# ============================================================================
# Set PYTHONPATH to include project root in the container
ENV PYTHONPATH=/workspaces/financial_db:${PYTHONPATH}

# Use the standard vscode user
USER vscode

# Set the working directory to the project folder
WORKDIR /workspaces/financial_db