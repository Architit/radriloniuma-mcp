"""RADRILONIUMA MCP Gateway Server

Implements the MCP Gateway Protocol V1 for the RADRILONIUMA ecosystem.
Provides secure, zero-trust access to:
  - LRPT/TSPT transit layers
  - .gateway/* local storage
  - Canon contracts and protocols
  - AELARIA chronicles and memory

Contract: mcp_gateway_protocol
Version: v1
Status: ACTIVE
Mode: contracts-first, derivation-only
"""

from __future__ import annotations

import asyncio
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

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
RADRILONIUMA_ROOT = Path(os.environ.get("RADRILONIUMA_ROOT", "/root/Architit_Nodes/RADRILONIUMA"))
TRUST_CLASS = os.environ.get("MCP_TRUST_CLASS", "TRUSTED_INTERNAL")
SENTINEL_GUARD = os.environ.get("MCP_SENTINEL_GUARD", "ACTIVE")

# ---------------------------------------------------------------------------
# Validation Gate
# ---------------------------------------------------------------------------

def _sentinel_check(endpoint_id: str, operation: str, path: str | None = None) -> bool:
    """Zero-trust validation before any TSPT ingress.

    Reads env vars on every call to support testing and dynamic policy updates.
    """
    sentinel = os.environ.get("MCP_SENTINEL_GUARD", "ACTIVE")
    trust = os.environ.get("MCP_TRUST_CLASS", "TRUSTED_INTERNAL")
    if sentinel != "ACTIVE":
        return False
    if trust not in ("TRUSTED_INTERNAL", "TRUSTED_EXTERNAL"):
        return False
    # Block any path outside RADRILONIUMA_ROOT
    if path is not None:
        resolved = (RADRILONIUMA_ROOT / path).resolve()
        if not str(resolved).startswith(str(RADRILONIUMA_ROOT.resolve())):
            return False
    return True

# ---------------------------------------------------------------------------
# Tool Registry
# ---------------------------------------------------------------------------

TOOLS: list[Tool] = [
    Tool(
        name="radr_list_directory",
        description="List contents of a directory within the RADRILONIUMA repository. "
                    "Requires Sentinel approval. Returns file tree with metadata.",
        inputSchema={
            "type": "object",
            "properties": {
                "relative_path": {
                    "type": "string",
                    "description": "Path relative to RADRILONIUMA_ROOT",
                },
                "max_depth": {
                    "type": "integer",
                    "description": "Maximum recursion depth",
                    "default": 2,
                },
            },
            "required": ["relative_path"],
        },
    ),
    Tool(
        name="radr_read_contract",
        description="Read a contract or protocol file from RADRILONIUMA. "
                    "Zero-trust: only .md and .yaml files in data/source/ or contract/.",
        inputSchema={
            "type": "object",
            "properties": {
                "contract_path": {
                    "type": "string",
                    "description": "Relative path to contract file",
                },
            },
            "required": ["contract_path"],
        },
    ),
    Tool(
        name="radr_search_canon",
        description="Search for keywords across canon, protocols, and contracts.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search term or regex pattern",
                },
                "scope": {
                    "type": "string",
                    "enum": ["protocols", "contracts", "canon", "all"],
                    "default": "all",
                },
                "max_results": {
                    "type": "integer",
                    "default": 10,
                },
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="radr_get_endpoint_status",
        description="Return the MCP Endpoint Matrix status for RADRILONIUMA.",
        inputSchema={
            "type": "object",
            "properties": {},
        },
    ),
]

# ---------------------------------------------------------------------------
# Tool Handlers
# ---------------------------------------------------------------------------

async def _handle_list_directory(args: dict[str, Any]) -> list[TextContent]:
    rel_path = args["relative_path"]
    max_depth = args.get("max_depth", 2)

    if not _sentinel_check("mcp_local_gateway", "read", rel_path):
        return [TextContent(type="text", text="SENTINEL_REJECT: Access denied by zero-trust guard.")]

    target = (RADRILONIUMA_ROOT / rel_path).resolve()
    if not target.exists():
        return [TextContent(type="text", text=f"PATH_NOT_FOUND: {rel_path}")]

    entries: list[dict[str, Any]] = []
    for item in target.rglob("*"):
        depth = len(item.relative_to(target).parts)
        if depth > max_depth:
            continue
        entries.append({
            "path": str(item.relative_to(RADRILONIUMA_ROOT)),
            "type": "directory" if item.is_dir() else "file",
            "size": item.stat().st_size if item.is_file() else None,
        })

    entries.sort(key=lambda x: (x["type"] != "directory", x["path"]))
    return [TextContent(type="text", text=json.dumps(entries, indent=2, ensure_ascii=False))]


async def _handle_read_contract(args: dict[str, Any]) -> list[TextContent]:
    contract_path = args["contract_path"]

    if not _sentinel_check("mcp_local_gateway", "read", contract_path):
        return [TextContent(type="text", text="SENTINEL_REJECT: Access denied by zero-trust guard.")]

    # Only allow .md and .yaml in specific directories
    allowed_prefixes = ("data/source/", "contract/", "protocol/")
    if not any(contract_path.startswith(p) for p in allowed_prefixes):
        return [TextContent(type="text", text="POLICY_REJECT: Path outside allowed contract scopes.")]

    if not (contract_path.endswith(".md") or contract_path.endswith(".yaml") or contract_path.endswith(".yml")):
        return [TextContent(type="text", text="POLICY_REJECT: Only markdown and YAML contracts are readable.")]

    target = (RADRILONIUMA_ROOT / contract_path).resolve()
    if not target.exists():
        return [TextContent(type="text", text=f"CONTRACT_NOT_FOUND: {contract_path}")]

    content = target.read_text(encoding="utf-8")
    return [TextContent(type="text", text=f"--- CONTRACT: {contract_path} ---\n\n{content}")]


async def _handle_search_canon(args: dict[str, Any]) -> list[TextContent]:
    import re

    query = args["query"]
    scope = args.get("scope", "all")
    max_results = args.get("max_results", 10)

    if not _sentinel_check("mcp_local_gateway", "read"):
        return [TextContent(type="text", text="SENTINEL_REJECT: Access denied by zero-trust guard.")]

    scope_dirs: list[Path] = []
    if scope in ("protocols", "all"):
        scope_dirs.append(RADRILONIUMA_ROOT / "data" / "source" / "protocols")
    if scope in ("contracts", "all"):
        scope_dirs.append(RADRILONIUMA_ROOT / "contract")
    if scope in ("canon", "all"):
        scope_dirs.append(RADRILONIUMA_ROOT / "data" / "source" / "canon")

    results: list[dict[str, Any]] = []
    pattern = re.compile(query, re.IGNORECASE)

    for directory in scope_dirs:
        if not directory.exists():
            continue
        for file_path in directory.rglob("*"):
            if not file_path.is_file():
                continue
            try:
                text = file_path.read_text(encoding="utf-8")
                matches = list(pattern.finditer(text))
                if matches:
                    results.append({
                        "file": str(file_path.relative_to(RADRILONIUMA_ROOT)),
                        "matches": len(matches),
                        "preview": text[max(0, matches[0].start() - 80):matches[0].end() + 80],
                    })
                    if len(results) >= max_results:
                        break
            except Exception:
                continue
        if len(results) >= max_results:
            break

    return [TextContent(type="text", text=json.dumps(results, indent=2, ensure_ascii=False))]


async def _handle_get_endpoint_status(_args: dict[str, Any]) -> list[TextContent]:
    matrix = {
        "effective_utc": "2026-05-05T00:00:00Z",
        "endpoints": [
            {
                "endpoint_id": "mcp_local_gateway",
                "backend": "local_fs",
                "trust_class": TRUST_CLASS,
                "scope": "LRPT/TSPT + .gateway/*",
                "direction": "read_write",
                "status": "ACTIVE" if SENTINEL_GUARD == "ACTIVE" else "DEGRADED",
            },
            {
                "endpoint_id": "mcp_onedrive_bridge",
                "backend": "onedrive",
                "trust_class": "TRUSTED_EXTERNAL",
                "scope": "contracts/taskspec/patch artifacts",
                "direction": "read_write",
                "status": "CONDITIONAL",
            },
            {
                "endpoint_id": "mcp_gdrive_lake",
                "backend": "gdrive",
                "trust_class": "TRUSTED_EXTERNAL",
                "scope": "journals/log snapshots/research context",
                "direction": "read_only",
                "status": "CONDITIONAL",
            },
        ],
        "sentinel_guard": SENTINEL_GUARD,
    }
    return [TextContent(type="text", text=json.dumps(matrix, indent=2, ensure_ascii=False))]


HANDLERS = {
    "radr_list_directory": _handle_list_directory,
    "radr_read_contract": _handle_read_contract,
    "radr_search_canon": _handle_search_canon,
    "radr_get_endpoint_status": _handle_get_endpoint_status,
}

# ---------------------------------------------------------------------------
# Server Lifecycle
# ---------------------------------------------------------------------------

async def run_server() -> None:
    server = Server("radriloniuma-gateway")

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
