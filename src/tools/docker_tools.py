from __future__ import annotations
import json
import logging
import time
import docker
import requests

from src.schemas.models import BuildResult

logger = logging.getLogger(__name__)

_client: docker.DockerClient | None = None


def _get_client() -> docker.DockerClient:
    global _client
    if _client is None:
        _client = docker.from_env()
    return _client


def build_image(context_path: str, dockerfile_path: str, tag: str, timeout: int = 600) -> BuildResult:
    """Build a Docker image from a Dockerfile and return BuildResult."""
    client = _get_client()
    build_log_lines: list[str] = []
    try:
        _, logs = client.images.build(
            path=context_path,
            dockerfile=dockerfile_path,
            tag=tag,
            rm=True,
            timeout=timeout,
        )
        for chunk in logs:
            if "stream" in chunk:
                line = chunk["stream"].rstrip("\n")
                if line:
                    build_log_lines.append(line)
            elif "error" in chunk:
                build_log_lines.append(f"ERROR: {chunk['error']}")
                return BuildResult(
                    success=False,
                    image_tag=tag,
                    build_log="\n".join(build_log_lines),
                    error_summary=chunk["error"],
                )
        return BuildResult(
            success=True,
            image_tag=tag,
            build_log="\n".join(build_log_lines),
        )
    except docker.errors.BuildError as e:
        for chunk in e.build_log:
            if "stream" in chunk:
                build_log_lines.append(chunk["stream"].rstrip("\n"))
            elif "error" in chunk:
                build_log_lines.append(f"ERROR: {chunk['error']}")
        return BuildResult(
            success=False,
            image_tag=tag,
            build_log="\n".join(build_log_lines),
            error_summary=str(e),
        )
    except Exception as e:
        return BuildResult(
            success=False,
            image_tag=tag,
            build_log="\n".join(build_log_lines),
            error_summary=str(e),
        )


def run_container(
    image_tag: str,
    env_vars: dict[str, str] | None = None,
    ports: dict[str, int] | None = None,
    timeout: int = 30,
) -> str:
    """Start a container and return its container ID."""
    client = _get_client()
    container = client.containers.run(
        image_tag,
        detach=True,
        environment=env_vars or {},
        ports=ports or {},
    )
    # Wait briefly for container to start
    time.sleep(min(timeout, 5))
    return container.id


def get_container_logs(container_id: str, tail: int = 100) -> str:
    """Get logs from a container."""
    client = _get_client()
    container = client.containers.get(container_id)
    logs = container.logs(tail=tail).decode("utf-8", errors="replace")
    return logs


def stop_and_remove_container(container_id: str) -> bool:
    """Stop and remove a container."""
    client = _get_client()
    try:
        container = client.containers.get(container_id)
        container.stop(timeout=10)
        container.remove(force=True)
        return True
    except docker.errors.NotFound:
        return True
    except Exception as e:
        logger.error("Failed to stop/remove container %s: %s", container_id, e)
        return False


def remove_image(image_tag: str) -> bool:
    """Remove a Docker image."""
    client = _get_client()
    try:
        client.images.remove(image_tag, force=True)
        return True
    except docker.errors.ImageNotFound:
        return True
    except Exception as e:
        logger.error("Failed to remove image %s: %s", image_tag, e)
        return False


MCP_INITIALIZE_REQUEST = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "mcp-auto-installer-test", "version": "1.0.0"},
    },
}


def send_mcp_initialize(target: str, transport: str) -> str:
    """Send MCP initialize handshake. target is container_id (stdio) or URL (http/sse)."""
    if transport in ("sse", "streamable-http"):
        return _mcp_http_initialize(target)
    else:
        return _mcp_stdio_initialize(target)


def _mcp_stdio_initialize(container_id: str) -> str:
    """Send MCP initialize via docker exec to container stdin."""
    client = _get_client()
    container = client.containers.get(container_id)
    payload = json.dumps(MCP_INITIALIZE_REQUEST) + "\n"
    try:
        exit_code, output = container.exec_run(
            cmd=["sh", "-c", f"echo '{payload.strip()}' | cat"],
            stdin=True,
            demux=True,
        )
        stdout = (output[0] or b"").decode("utf-8", errors="replace") if isinstance(output, tuple) else (output or b"").decode("utf-8", errors="replace")
        return stdout
    except Exception as e:
        return json.dumps({"error": str(e)})


def _mcp_http_initialize(url: str) -> str:
    """Send MCP initialize via HTTP POST."""
    headers = {"Content-Type": "application/json"}
    try:
        resp = requests.post(url, json=MCP_INITIALIZE_REQUEST, headers=headers, timeout=10)
        return resp.text
    except Exception as e:
        return json.dumps({"error": str(e)})
