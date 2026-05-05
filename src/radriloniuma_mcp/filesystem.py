\"\"\"RADRILONIUMA MCP Filesystem Server

Read/Write/Edit operations with zero-trust scope locking.
Allowed scopes: .gateway/* and data/local/*

Contract: mcp_filesystem_protocol
Version: v1
Status: ACTIVE
Mode: contracts-first, derivation-only
\"\"\"

from __future__ import annotations

import asyncio
import hashlib
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

# Writable scopes within RADRILONIUMA_ROOT
ALLOWED_WRITE_PREFIXES = (".gateway/", "data/local/")
ALLOWED_READ_PREFIXES = (".gateway/", "data/local/", "data/source/", "contract/", "protocol/")


def _sentinel_check(operation: str, path: str | None = None, write: bool = False) -> bool:
    \"\"\"Zero-trust validation for filesystem operations.\"\"\"
    sentinel = os.environ.get("MCP_SENTINEL_GUARD", "ACTIVE")
    if sentinel != "ACTIVE":
        return False
    if path is None:
        return True
    resolved = (RADRILONIUMA_ROOT / path).resolve()
    if not str(resolved).startswith(str(RADRILONIUMA_ROOT.resolve())):
        return False
    rel = str(Path(path))
    prefixes = ALLOWED_WRITE_PREFIXES if write else ALLOWED_READ_PREFIXES
    return any(rel.startswith(p) or rel == p.rstrip("/") for p in prefixes)


def _sha256(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


TOOLS: list[Tool] = [
    Tool(
        name="radr_read_file",
        description="Read a file within the allowed filesystem scope. "
                    "Supports line range selection and optional SHA-256 integrity check.",
        inputSchema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path relative to RADRILONIUMA_ROOT",
                },
                "start_line": {
                    "type": "integer",
                    "description": "1-based starting line (inclusive)",
                },
                "end_line": {
                    "type": "integer",
                    "description": "1-based ending line (inclusive)",
                },
                "expected_sha256": {
                    "type": "string",
                    "description": "Optional SHA-256 for integrity verification",
                },
            },
            "required": ["file_path"],
        },
    ),
    Tool(
        name="radr_write_file",
        description="Write content to a file within the allowed write scope. "
                    "Requires SHA-256 integrity check for the content being written.",
        inputSchema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path relative to RADRILONIUMA_ROOT",
                },
                "content": {
                    "type": "string",
                    "description": "Full file content to write",
                },
                "content_sha256": {
                    "type": "string",
                    "description": "SHA-256 of the content (required for integrity)",
                },
                "create_dirs": {
                    "type": "boolean",
                    "description": "Create parent directories if missing",
                    "default": True,
                },
            },
            "required": ["file_path", "content", "content_sha256"],
        },
    ),
    Tool(
        name="radr_edit_file",
        description="Surgically edit a file: replace, insert after anchor, or delete line range. "
                    "Scope locked to .gateway/* and data/local/*.",
        inputSchema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path relative to RADRILONIUMA_ROOT",
                },
                "mode": {
                    "type": "string",
                    "enum": ["replace", "insert", "delete"],
                    "description": "Edit mode",
                },
                "old_string": {
                    "type": "string",
                    "description": "String to replace (for mode=replace)",
                },
                "new_string": {
                    "type": "string",
                    "description": "Replacement string (for mode=replace/insert)",
                },
                "anchor": {
                    "type": "string",
                    "description": "Anchor line to insert after (for mode=insert)",
                },
                "start_line": {
                    "type": "integer",
                    "description": "1-based start line (for mode=delete)",
                },
                "end_line": {
                    "type": "integer",
                    "description": "1-based end line (for mode=delete)",
                },
            },
            "required": ["file_path", "mode"],
        },
    ),
    Tool(
        name="radr_sync_gateway",
        description="Sync .gateway/storage/local/ with data/local/ or list gateway storage contents.",
        inputSchema={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "sync_from_data", "sync_to_data"],
                    "description": "Action to perform",
                    "default": "list",
                },
                "dry_run": {
                    "type": "boolean",
                    "description": "Show planned actions without executing",
                    "default": True,
                },
            },
        },
    ),
]


async def _handle_read_file(args: dict[str, Any]) -> list[TextContent]:
    file_path = args["file_path"]
    start_line = args.get("start_line")
    end_line = args.get("end_line")
    expected_sha256 = args.get("expected_sha256")

    if not _sentinel_check("read", file_path):
        return [TextContent(type="text", text="SENTINEL_REJECT: Access denied by zero-trust guard.")]

    target = (RADRILONIUMA_ROOT / file_path).resolve()
    if not target.exists() or not target.is_file():
        return [TextContent(type="text", text=f"FILE_NOT_FOUND: {file_path}")]

    try:
        content = target.read_text(encoding="utf-8")
    except Exception as e:
        return [TextContent(type="text", text=f"READ_ERROR: {e}")]

    if expected_sha256 and _sha256(content) != expected_sha256:
        return [TextContent(type="text", text=f"INTEGRITY_MISMATCH: SHA-256 mismatch for {file_path}")]

    lines = content.splitlines(keepends=True)
    total_lines = len(lines)

    if start_line is not None or end_line is not None:
        s = (start_line or 1) - 1
        e = (end_line or total_lines)
        lines = lines[s:e]
        content = "".join(lines)

    header = f"--- FILE: {file_path} (lines {start_line or 1}-{end_line or total_lines} of {total_lines}) ---\n"
    return [TextContent(type="text", text=header + content)]


async def _handle_write_file(args: dict[str, Any]) -> list[TextContent]:
    file_path = args["file_path"]
    content = args["content"]
    content_sha256 = args["content_sha256"]
    create_dirs = args.get("create_dirs", True)

    if not _sentinel_check("write", file_path, write=True):
        return [TextContent(type="text", text="SENTINEL_REJECT: Access denied by zero-trust guard.")]

    if _sha256(content) != content_sha256:
        return [TextContent(type="text", text="INTEGRITY_MISMATCH: content_sha256 does not match content.")]

    target = (RADRILONIUMA_ROOT / file_path).resolve()
    if create_dirs:
        target.parent.mkdir(parents=True, exist_ok=True)

    try:
        target.write_text(content, encoding="utf-8")
    except Exception as e:
        return [TextContent(type="text", text=f"WRITE_ERROR: {e}")]

    return [TextContent(type="text", text=f"SUCCESS: Wrote {file_path} ({len(content)} chars)")]


async def _handle_edit_file(args: dict[str, Any]) -> list[TextContent]:
    file_path = args["file_path"]
    mode = args["mode"]

    if not _sentinel_check("edit", file_path, write=True):
        return [TextContent(type="text", text="SENTINEL_REJECT: Access denied by zero-trust guard.")]

    target = (RADRILONIUMA_ROOT / file_path).resolve()
    if not target.exists() or not target.is_file():
        return [TextContent(type="text", text=f"FILE_NOT_FOUND: {file_path}")]

    try:
        content = target.read_text(encoding="utf-8")
    except Exception as e:
        return [TextContent(type="text", text=f"READ_ERROR: {e}")]

    if mode == "replace":
        old = args.get("old_string", "")
        new = args.get("new_string", "")
        if old not in content:
            return [TextContent(type="text", text=f"REPLACE_ANCHOR_NOT_FOUND: old_string not found in {file_path}")]
        new_content = content.replace(old, new, 1)

    elif mode == "insert":
        anchor = args.get("anchor", "")
        new = args.get("new_string", "")
        if anchor not in content:
            return [TextContent(type="text", text=f"INSERT_ANCHOR_NOT_FOUND: anchor not found in {file_path}")]
        new_content = content.replace(anchor, anchor + new, 1)

    elif mode == "delete":
        lines = content.splitlines(keepends=True)
        s = (args.get("start_line") or 1) - 1
        e = args.get("end_line") or len(lines)
        if s < 0 or e > len(lines) or s >= e:
            return [TextContent(type="text", text=f"INVALID_RANGE: start={s+1}, end={e}, total={len(lines)}")]
        new_content = "".join(lines[:s] + lines[e:])

    else:
        return [TextContent(type="text", text=f"UNKNOWN_MODE: {mode}")]

    try:
        target.write_text(new_content, encoding="utf-8")
    except Exception as e:
        return [TextContent(type="text", text=f"WRITE_ERROR: {e}")]

    return [TextContent(type="text", text=f"SUCCESS: Edited {file_path} (mode={mode})")]


async def _handle_sync_gateway(args: dict[str, Any]) -> list[TextContent]:
    action = args.get("action", "list")
    dry_run = args.get("dry_run", True)

    gateway_dir = RADRILONIUMA_ROOT / ".gateway" / "storage" / "local"
    data_dir = RADRILONIUMA_ROOT / "data" / "local"

    if not _sentinel_check("sync", ".gateway/storage/local", write=True):
        return [TextContent(type="text", text="SENTINEL_REJECT: Access denied by zero-trust guard.")]

    if action == "list":
        entries: list[dict[str, Any]] = []
        if gateway_dir.exists():
            for item in gateway_dir.rglob("*"):
                rel = str(item.relative_to(gateway_dir))
                entries.append({
                    "path": rel,
                    "type": "directory" if item.is_dir() else "file",
                    "size": item.stat().st_size if item.is_file() else None,
                })
        return [TextContent(type="text", text=json.dumps(entries, indent=2, ensure_ascii=False))]

    if action == "sync_from_data":
        if not data_dir.exists():
            return [TextContent(type="text", text="SOURCE_NOT_FOUND: data/local/ does not exist")]
        actions: list[dict[str, str]] = []
        for item in data_dir.rglob("*"):
            if item.is_file():
                rel = item.relative_to(data_dir)
                dest = gateway_dir / rel
                action_entry = {"type": "copy", "from": str(rel), "to": str(dest.relative_to(RADRILONIUMA_ROOT))}
                if not dry_run:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_text(item.read_text(encoding="utf-8"), encoding="utf-8")
                actions.append(action_entry)
        status = "DRY_RUN" if dry_run else "EXECUTED"
        return [TextContent(type="text", text=f"STATUS: {status}\n" + json.dumps(actions, indent=2, ensure_ascii=False))]

    if action == "sync_to_data":
        if not gateway_dir.exists():
            return [TextContent(type="text", text="SOURCE_NOT_FOUND: .gateway/storage/local/ does not exist")]
        actions: list[dict[str, str]] = []
        for item in gateway_dir.rglob("*"):
            if item.is_file():
                rel = item.relative_to(gateway_dir)
                dest = data_dir / rel
                action_entry = {"type": "copy", "from": str(rel), "to": str(dest.relative_to(RADRILONIUMA_ROOT))}
                if not dry_run:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_text(item.read_text(encoding="utf-8"), encoding="utf-8")
                actions.append(action_entry)
        status = "DRY_RUN" if dry_run else "EXECUTED"
        return [TextContent(type="text", text=f"STATUS: {status}\n" + json.dumps(actions, indent=2, ensure_ascii=False))]

    return [TextContent(type="text", text=f"UNKNOWN_ACTION: {action}")]


HANDLERS = {
    "radr_read_file": _handle_read_file,
    "radr_write_file": _handle_write_file,
    "radr_edit_file": _handle_edit_file,
    "radr_sync_gateway": _handle_sync_gateway,
}


async def run_server() -> None:
    server = Server("radriloniuma-filesystem")

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
