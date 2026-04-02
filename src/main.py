from __future__ import annotations
import argparse
import json
import logging
import sys
import os

from src.orchestrator import Orchestrator
from src import config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mcp-auto-installer",
        description="MCP Auto-Installer: Analyze repo, generate Dockerfile, build & test",
    )
    parser.add_argument("repo_path", help="Local MCP server repository path")
    parser.add_argument("--output-dir", default="./output", help="Output directory (default: ./output)")
    parser.add_argument("--max-fix-attempts", type=int, default=3, help="Max fix loop attempts (default: 3)")
    parser.add_argument("--skip-test", action="store_true", help="Skip container test phase")
    parser.add_argument("--verbose", action="store_true", help="Enable DEBUG logging")
    parser.add_argument("--env-file", default=None, help="Path to .env file for real secrets testing")
    return parser


def main(args: list[str] | None = None) -> int:
    parser = build_parser()
    parsed = parser.parse_args(args)

    # Setup logging
    log_level = logging.DEBUG if parsed.verbose else getattr(logging, config.LOG_LEVEL, logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    # Load extra env file if provided
    if parsed.env_file:
        from dotenv import load_dotenv
        load_dotenv(parsed.env_file, override=True)

    # Validate repo path
    repo_path = os.path.abspath(parsed.repo_path)
    if not os.path.isdir(repo_path):
        print(f"Error: Repository path does not exist: {repo_path}", file=sys.stderr)
        return 1

    print(f"MCP Auto-Installer")
    print(f"  Repo: {repo_path}")
    print(f"  Output: {parsed.output_dir}")
    print(f"  Max fix attempts: {parsed.max_fix_attempts}")
    print(f"  Skip test: {parsed.skip_test}")
    print()

    orchestrator = Orchestrator(
        max_fix_attempts=parsed.max_fix_attempts,
        skip_test=parsed.skip_test,
    )
    result = orchestrator.run(repo_path, output_dir=parsed.output_dir)

    print()
    if result.success:
        print("SUCCESS!")
        print(f"  Image: {result.image_tag}")
        print(f"  Transport: {result.transport_type}")
        print(f"  Run: {result.startup_command}")
    else:
        print("FAILED")
        for note in result.notes:
            print(f"  - {note}")

    return 0 if result.success else 1


if __name__ == "__main__":
    sys.exit(main())
