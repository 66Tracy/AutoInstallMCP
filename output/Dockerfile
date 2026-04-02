# Dockerfile for MCP Python SDK
# Using python:3.12-slim for better availability
FROM python:3.12-slim

# Install system dependencies including git for dynamic versioning
RUN apt-get update && apt-get install -y \
    git \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r mcp && useradd -r -g mcp -m -d /home/mcp mcp

WORKDIR /app

# Copy dependency files first for better layer caching
COPY pyproject.toml README.md ./
COPY src/ ./src/

# Install the package using pip (simpler than uv for Docker builds)
# Install with cli extras for mcp command
RUN pip install .[cli]

# Switch to non-root user
USER mcp

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    # MCP SDK specific settings
    MCP_TRANSPORT=stdio \
    MCP_LOG_LEVEL=INFO

# Health check for stdio transport (basic check if mcp CLI works)
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import mcp; print('MCP SDK available')" || exit 1

# Entry point for MCP CLI tool via stdio transport
ENTRYPOINT ["mcp"]

# Default command: show help if no arguments provided
CMD ["--help"]