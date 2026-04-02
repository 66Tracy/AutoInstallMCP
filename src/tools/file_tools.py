from __future__ import annotations
import os
import re
import glob as globmod


def list_directory_tree(path: str) -> str:
    """List the directory tree structure as an ASCII tree (max 4 levels deep)."""
    lines: list[str] = []
    path = os.path.abspath(path)
    base = os.path.basename(path) or path
    lines.append(base + "/")
    _walk_tree(path, "", lines, depth=0, max_depth=4)
    return "\n".join(lines)


def _walk_tree(directory: str, prefix: str, lines: list[str], depth: int = 0, max_depth: int = 4) -> None:
    try:
        entries = sorted(os.listdir(directory))
    except PermissionError:
        lines.append(prefix + "└── [permission denied]")
        return

    # Filter out common noise
    skip = {".git", "__pycache__", "node_modules", ".venv", ".tox", ".mypy_cache", ".eggs", "dist", "build", ".pytest_cache"}
    entries = [e for e in entries if e not in skip]

    if depth >= max_depth:
        if entries:
            lines.append(prefix + "└── ... (depth limit reached)")
        return

    for i, entry in enumerate(entries):
        is_last = i == len(entries) - 1
        connector = "└── " if is_last else "├── "
        full_path = os.path.join(directory, entry)

        if os.path.isdir(full_path):
            lines.append(prefix + connector + entry + "/")
            extension = "    " if is_last else "│   "
            _walk_tree(full_path, prefix + extension, lines, depth + 1, max_depth)
        else:
            lines.append(prefix + connector + entry)


def read_file(path: str, max_lines: int = 200) -> str:
    """Read file content, optionally limiting to max_lines (default 200)."""
    max_lines = int(max_lines)
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        return f"Error: File not found: {path}"
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = []
            for i, line in enumerate(f):
                if i >= max_lines:
                    lines.append(f"\n... (truncated at {max_lines} lines)")
                    break
                lines.append(line)
        return "".join(lines)
    except Exception as e:
        return f"Error reading file: {e}"


def write_file(path: str, content: str) -> str:
    """Write content to a file, creating directories if needed."""
    path = os.path.abspath(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Successfully wrote {len(content)} bytes to {path}"
    except Exception as e:
        return f"Error writing file: {e}"


def search_files(root: str, pattern: str) -> list[str]:
    """Search for files matching a glob pattern under root directory."""
    root = os.path.abspath(root)
    results = []
    full_pattern = os.path.join(root, "**", pattern)
    for match in globmod.glob(full_pattern, recursive=True):
        results.append(os.path.relpath(match, root))
    return sorted(results)


def search_in_files(root: str, regex: str, file_pattern: str = "*") -> list[dict]:
    """Search for regex pattern in file contents under root directory. Returns max 50 matches."""
    root = os.path.abspath(root)
    results = []
    compiled = re.compile(regex)
    full_pattern = os.path.join(root, "**", file_pattern)
    for filepath in globmod.glob(full_pattern, recursive=True):
        if not os.path.isfile(filepath):
            continue
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                for line_number, line in enumerate(f, 1):
                    if compiled.search(line):
                        results.append({
                            "file": os.path.relpath(filepath, root),
                            "line_number": line_number,
                            "line": line.rstrip()[:200],
                        })
                        if len(results) >= 50:
                            return results
        except (PermissionError, OSError):
            continue
    return results
