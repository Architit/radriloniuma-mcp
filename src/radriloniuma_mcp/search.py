"""RADRILONIUMA MCP Search Server

Advanced ecosystem search with filters:
  - glob_pattern: file name pattern
  - file_type: extension filter
  - scope_dir: restrict search to directory
  - modified_after: timestamp filter
  - max_results: limit output

Contract: mcp_search_protocol
Version: v1
Status: ACTIVE
Mode: contracts-first, derivation-only
"""

from __future__ import annotations

import asyncio
import fnmatch
import json
import os
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    TextContent,
    Tool,
)

RADRILONIUMA_ROOT = Path(os.environ.get("RADRILONIUMA_ROOT", "/root/Architit_Nodes/RADRILONIUMA"))


def _sentinel_check(path: str | None = None) -> bool:
    """Zero-trust validation before any TSPT ingress."""
    sentinel = os.environ.get("MCP_SENTINEL_GUARD", "ACTIVE")
    if sentinel != "ACTIVE":
        return False
    if path is not None:
        resolved = (RADRILONIUMA_ROOT / path).resolve()
        if not str(resolved).startswith(str(RADRILONIUMA_ROOT.resolve())):
            return False
    return True


TOOLS: list[Tool] = [
    Tool(
        name="radr_search_ecosystem",
        description="Advanced search across RADRILONIUMA ecosystem with filters. "
                    "Supports glob patterns, file types, directory scoping, and date filters.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Filename pattern or glob (e.g. '*.md', 'MCP_*')",
                },
                "file_type": {
                    "type": "string",
                    "description": "File extension filter (e.g. 'md', 'yaml', 'py')",
                },
                "scope_dir": {
                    "type": "string",
                    "description": "Restrict search to this directory (relative to RADRILONIUMA_ROOT)",
                    "default": "",
                },
                "modified_after": {
                    "type": "string",
                    "description": "ISO-8601 timestamp — only files modified after this",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results",
                    "default": 50,
                },
                "include_dirs": {
                    "type": "boolean",
                    "description": "Include directories in results",
                    "default": False,
                },
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="radr_search_content",
        description="Search for content inside files across the ecosystem.",
        inputSchema={
            "type": "object",
            "properties": {
                "text_query": {
                    "type": "string",
                    "description": "Text to search for inside files",
                },
                "glob_pattern": {
                    "type": "string",
                    "description": "Limit search to files matching this glob",
                    "default": "*",
                },
                "scope_dir": {
                    "type": "string",
                    "description": "Restrict search to this directory",
                    "default": "",
                },
                "max_results": {
                    "type": "integer",
                    "default": 20,
                },
                "preview_chars": {
                    "type": "integer",
                    "description": "Characters around match to include in preview",
                    "default": 60,
                },
            },
            "required": ["text_query"],
        },
    ),
]


async def _handle_search_ecosystem(args: dict[str, Any]) -> list[TextContent]:
    query = args["query"]
    file_type = args.get("file_type", "")
    scope_dir = args.get("scope_dir", "")
    modified_after = args.get("modified_after", "")
    max_results = args.get("max_results", 50)
    include_dirs = args.get("include_dirs", False)

    if not _sentinel_check(scope_dir or None):
        return [TextContent(type="text", text="SENTINEL_REJECT: Access denied by zero-trust guard.")]

    search_root = RADRILONIUMA_ROOT / scope_dir if scope_dir else RADRILONIUMA_ROOT
    if not search_root.exists():
        return [TextContent(type="text", text=f"SCOPE_NOT_FOUND: {scope_dir}")]

    results: list[dict[str, Any]] = []
    cutoff_ts = 0.0
    if modified_after:
        from datetime import datetime
        try:
            cutoff_ts = datetime.fromisoformat(modified_after.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return [TextContent(type="text", text=f"INVALID_TIMESTAMP: {modified_after}")]

    for item in search_root.rglob("*"):
        if len(results) >= max_results:
            break

        rel = str(item.relative_to(RADRILONIUMA_ROOT))

        # Skip .git and hidden dirs
        if "/.git/" in rel or "/.git" == rel:
            continue

        # Glob pattern match
        if not fnmatch.fnmatch(item.name, query):
            continue

        # File type filter
        if file_type and item.is_file() and not item.name.endswith(f".{file_type}"):
            continue

        # Modified after filter
        if cutoff_ts > 0 and item.stat().st_mtime < cutoff_ts:
            continue

        if item.is_dir() and not include_dirs:
            continue

        results.append({
            "path": rel,
            "type": "directory" if item.is_dir() else "file",
            "size": item.stat().st_size if item.is_file() else None,
            "modified": item.stat().st_mtime,
        })

    return [TextContent(type="text", text=json.dumps(results, indent=2, ensure_ascii=False))]


async def _handle_search_content(args: dict[str, Any]) -> list[TextContent]:
    text_query = args["text_query"]
    glob_pattern = args.get("glob_pattern", "*")
    scope_dir = args.get("scope_dir", "")
    max_results = args.get("max_results", 20)
    preview_chars = args.get("preview_chars", 60)

    if not _sentinel_check(scope_dir or None):
        return [TextContent(type="text", text="SENTINEL_REJECT: Access denied by zero-trust guard.")]

    search_root = RADRILONIUMA_ROOT / scope_dir if scope_dir else RADRILONIUMA_ROOT
    if not search_root.exists():
        return [TextContent(type="text", text=f"SCOPE_NOT_FOUND: {scope_dir}")]

    results: list[dict[str, Any]] = []

    for item in search_root.rglob(glob_pattern):
        if len(results) >= max_results:
            break
        if not item.is_file():
            continue

        # Skip binary files
        if item.stat().st_size > 1024 * 1024:  # 1MB limit
            continue

        try:
            text = item.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        if text_query in text:
            idx = text.find(text_query)
            start = max(0, idx - preview_chars)
            end = min(len(text), idx + len(text_query) + preview_chars)
            preview = text[start:end].replace("\n", " ")

            results.append({
                "file": str(item.relative_to(RADRILONIUMA_ROOT)),
                "matches": text.count(text_query),
                "preview": preview,
            })

    return [TextContent(type="text", text=json.dumps(results, indent=2, ensure_ascii=False))]


HANDLERS = {
    "radr_search_ecosystem": _handle_search_ecosystem,
    "radr_search_content": _handle_search_content,
}


async def run_server() -> None:
    server = Server("radriloniuma-search")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return TOOLS

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any] | None) -> list[TextContent]:
        if name not in HANDLERS:
            return [TextContent(type="text", text=f"UNKNOWN_TOOL: {name}")]
        args = arguments or {}
        return await HANDLERS[name](args)

    async with stdio_server(server) as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main() -> None:
    asyncio.run(run_server())


if __name__ == "__main__":
    main()
