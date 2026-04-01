#!/usr/bin/env bash
set -euo pipefail

echo "========================================="
echo " MCP Auto-Installer — Project Setup"
echo "========================================="
echo ""

# ── 1. Check prerequisites ──────────────────────────────────────────────────

errors=0

# Python 3.11+
if command -v python &>/dev/null; then
    PY=python
elif command -v python3 &>/dev/null; then
    PY=python3
else
    echo "[ERROR] Python not found. Install Python 3.11+ first."
    errors=1
    PY=""
fi

if [ -n "$PY" ]; then
    PY_VERSION="$($PY -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "unknown")"
    PY_MAJOR="$($PY -c "import sys; print(sys.version_info.major)" 2>/dev/null || echo "0")"
    PY_MINOR="$($PY -c "import sys; print(sys.version_info.minor)" 2>/dev/null || echo "0")"
    if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 11 ]; }; then
        echo "[ERROR] Python $PY_VERSION found, but 3.11+ is required."
        errors=1
    else
        echo "[OK] Python $PY_VERSION"
    fi
fi

# uv
if command -v uv &>/dev/null; then
    echo "[OK] uv $(uv --version 2>/dev/null | head -1)"
else
    echo "[ERROR] uv not found. Install it: https://docs.astral.sh/uv/getting-started/installation/"
    errors=1
fi

# Docker
if command -v docker &>/dev/null; then
    if docker info > /dev/null 2>&1; then
        echo "[OK] Docker Engine is running"
    else
        echo "[ERROR] Docker is installed but the daemon is not running. Start Docker Desktop or the Docker service."
        errors=1
    fi
else
    echo "[ERROR] Docker not found. Install Docker: https://docs.docker.com/get-docker/"
    errors=1
fi

if [ "$errors" -ne 0 ]; then
    echo ""
    echo "[FATAL] Prerequisites check failed. Fix the errors above and re-run this script."
    exit 1
fi

echo ""

# ── 2. Initialize project with uv ───────────────────────────────────────────

if [ ! -f "pyproject.toml" ]; then
    echo "Initializing project with uv..."
    uv init
else
    echo "[OK] pyproject.toml already exists, skipping uv init"
fi

echo "Adding dependencies..."
uv add openai pydantic python-dotenv docker

echo "[OK] Dependencies installed"
echo ""

# ── 3. Create .env.example ───────────────────────────────────────────────────

cat > .env.example << 'ENVEOF'
# MCP Auto-Installer Configuration
# Copy this file to .env and fill in your values.

# LLM Configuration (required)
LLM_API_KEY=your-api-key-here

# LLM Model name (default: gpt-4o)
LLM_MODEL=gpt-4o

# LLM Base URL — set this for OpenAI-compatible endpoints (optional)
# LLM_BASE_URL=http://127.0.0.1:18080
ENVEOF

echo "[OK] Created .env.example"

# ── 4. Copy .env.example to .env if needed ───────────────────────────────────

if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "[OK] Created .env from .env.example — please edit it with your real values"
else
    echo "[OK] .env already exists, skipping copy"
fi

echo ""

# ── 5. Create src/ directory structure ───────────────────────────────────────

echo "Creating src/ directory structure..."

dirs=(
    "src"
    "src/agents"
    "src/agents/repo_analysis_agent"
    "src/agents/dockerfile_agent"
    "src/agents/build_test_agent"
    "src/tools"
    "src/schemas"
    "src/model"
)

for dir in "${dirs[@]}"; do
    mkdir -p "$dir"
done

# Create __init__.py files
init_files=(
    "src/__init__.py"
    "src/agents/__init__.py"
    "src/agents/repo_analysis_agent/__init__.py"
    "src/agents/dockerfile_agent/__init__.py"
    "src/agents/build_test_agent/__init__.py"
    "src/tools/__init__.py"
    "src/schemas/__init__.py"
    "src/model/__init__.py"
)

for init in "${init_files[@]}"; do
    if [ ! -f "$init" ]; then
        touch "$init"
    fi
done

echo "[OK] src/ directory structure created"

# ── 6. Create output/ directory ──────────────────────────────────────────────

mkdir -p output
echo "[OK] output/ directory created"

echo ""

# ── 7. Verify Docker connectivity ───────────────────────────────────────────

if docker info > /dev/null 2>&1; then
    echo "[OK] Docker connectivity verified"
else
    echo "[WARN] Docker connectivity check failed"
fi

echo ""

# ── 8. Summary ───────────────────────────────────────────────────────────────

echo "========================================="
echo " Setup Complete!"
echo "========================================="
echo ""
echo " Project structure:"
echo "   src/agents/         — Agent implementations"
echo "   src/tools/          — File and Docker tool functions"
echo "   src/schemas/        — Pydantic data models"
echo "   src/model/          — LLM client wrapper"
echo "   output/             — Pipeline output directory"
echo ""
echo " Next steps:"
echo "   1. Edit .env with your real LLM API key and settings"
echo "   2. Run: python -m src.main /path/to/mcp-repo"
echo ""
