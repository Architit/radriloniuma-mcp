"""RADRILONIUMA MCP Protocols Server

Read-only protocol and contract validation.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    TextContent,
    Tool,
)

RADRILONIUMA_ROOT = Path(os.environ.get("RADRILONIUMA_ROOT", "/root/Architit_Nodes/RADRILONIUMA"))

ALLOWED_PREFIXES = ("data/source/", "contract/", "protocol/", "gov/")


def _sentinel_check(operation: str, path: str | None = None) -> bool:
    sentinel = os.environ.get("MCP_SENTINEL_GUARD", "ACTIVE")
    if sentinel != "ACTIVE":
        return False
    if path is None:
        return True
    resolved = (RADRILONIUMA_ROOT / path).resolve()
    if not str(resolved).startswith(str(RADRILONIUMA_ROOT.resolve())):
        return False
    rel = str(Path(path))
    return any(rel.startswith(p) or rel == p.rstrip("/") for p in ALLOWED_PREFIXES)


def _extract_frontmatter(content: str) -> dict[str, Any]:
    if not content.startswith("---"):
        return {}
    try:
        end = content.find("\n---", 3)
        if end == -1:
            return {}
        fm_text = content[3:end].strip()
        result: dict[str, Any] = {}
        for line in fm_text.splitlines():
            if ":" in line and not line.strip().startswith("-"):
                key, val = line.split(":", 1)
                result[key.strip()] = val.strip()
        return result
    except Exception:
        return {}


def _find_protocols(scope: str = "all", status_filter: str = "") -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    dirs: list[Path] = []
    if scope in ("protocols", "all"):
        dirs.append(RADRILONIUMA_ROOT / "data" / "source" / "protocols")
    if scope in ("contracts", "all"):
        dirs.append(RADRILONIUMA_ROOT / "contract")
    if scope in ("canon", "all"):
        dirs.append(RADRILONIUMA_ROOT / "data" / "source" / "canon")

    for directory in dirs:
        if not directory.exists():
            continue
        for file_path in directory.rglob("*.md"):
            try:
                text = file_path.read_text(encoding="utf-8")
                fm = _extract_frontmatter(text)
                rel = str(file_path.relative_to(RADRILONIUMA_ROOT))
                status = fm.get("status", "UNKNOWN")
                if status_filter and status.upper() != status_filter.upper():
                    continue
                results.append({
                    "file": rel,
                    "name": file_path.stem,
                    "status": status,
                    "version": fm.get("version", "unknown"),
                    "last_updated": fm.get("last_updated_utc", "unknown"),
                })
            except Exception:
                continue
    return results


TOOLS: list[Tool] = [
    Tool(
        name="radr_validate_contract",
        description="Validate contract file for schema compliance.",
        inputSchema={
            "type": "object",
            "properties": {
                "contract_path": {"type": "string"},
                "required_fields": {
                    "type": "array",
                    "items": {"type": "string"},
                    "default": ["version", "status"],
                },
            },
            "required": ["contract_path"],
        },
    ),
    Tool(
        name="radr_list_protocols",
        description="List protocols with status filtering.",
        inputSchema={
            "type": "object",
            "properties": {
                "scope": {"type": "string", "enum": ["protocols", "contracts", "canon", "all"], "default": "all"},
                "status_filter": {"type": "string", "default": ""},
                "max_results": {"type": "integer", "default": 50},
            },
        },
    ),
    Tool(
        name="radr_get_protocol_status",
        description="Get status of a specific protocol.",
        inputSchema={
            "type": "object",
            "properties": {
                "protocol_path": {"type": "string"},
            },
            "required": ["protocol_path"],
        },
    ),
    Tool(
        name="radr_check_drift",
        description="Compare two protocol versions for drift.",
        inputSchema={
            "type": "object",
            "properties": {
                "baseline_path": {"type": "string"},
                "compare_path": {"type": "string"},
            },
            "required": ["baseline_path", "compare_path"],
        },
    ),
]


async def _handle_validate_contract(args: dict[str, Any]) -> list[TextContent]:
    contract_path = args["contract_path"]
    required_fields = args.get("required_fields", ["version", "status"])
    if not _sentinel_check("validate", contract_path):
        return [TextContent(type="text", text="SENTINEL_REJECT")]
    target = (RADRILONIUMA_ROOT / contract_path).resolve()
    if not target.exists():
        return [TextContent(type="text", text=f"FILE_NOT_FOUND: {contract_path}")]
    content = target.read_text(encoding="utf-8")
    fm = _extract_frontmatter(content)
    errors = [f"MISSING_FIELD: {f}" for f in required_fields if f not in fm or not fm[f]]
    result = {"file": contract_path, "valid": len(errors) == 0, "errors": errors, "frontmatter": fm}
    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def _handle_list_protocols(args: dict[str, Any]) -> list[TextContent]:
    if not _sentinel_check("list"):
        return [TextContent(type="text", text="SENTINEL_REJECT")]
    results = _find_protocols(args.get("scope", "all"), args.get("status_filter", ""))[:args.get("max_results", 50)]
    return [TextContent(type="text", text=json.dumps(results, indent=2))]


async def _handle_get_protocol_status(args: dict[str, Any]) -> list[TextContent]:
    protocol_path = args["protocol_path"]
    if not _sentinel_check("status", protocol_path):
        return [TextContent(type="text", text="SENTINEL_REJECT")]
    target = (RADRILONIUMA_ROOT / protocol_path).resolve()
    if not target.exists():
        return [TextContent(type="text", text=f"FILE_NOT_FOUND: {protocol_path}")]
    content = target.read_text(encoding="utf-8")
    fm = _extract_frontmatter(content)
    result = {"file": protocol_path, "status": fm.get("status", "UNKNOWN"), "version": fm.get("version", "unknown")}
    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def _handle_check_drift(args: dict[str, Any]) -> list[TextContent]:
    baseline_path = args["baseline_path"]
    compare_path = args["compare_path"]
    if not _sentinel_check("drift", baseline_path) or not _sentinel_check("drift", compare_path):
        return [TextContent(type="text", text="SENTINEL_REJECT")]
    base_file = (RADRILONIUMA_ROOT / baseline_path).resolve()
    cmp_file = (RADRILONIUMA_ROOT / compare_path).resolve()
    if not base_file.exists():
        return [TextContent(type="text", text=f"FILE_NOT_FOUND: {baseline_path}")]
    if not cmp_file.exists():
        return [TextContent(type="text", text=f"FILE_NOT_FOUND: {compare_path}")]
    base_text = base_file.read_text(encoding="utf-8")
    cmp_text = cmp_file.read_text(encoding="utf-8")
    base_fm = _extract_frontmatter(base_text)
    cmp_fm = _extract_frontmatter(cmp_text)
    drift = {"baseline": baseline_path, "compare": compare_path, "frontmatter_drift": {}}
    for key in set(base_fm.keys()) | set(cmp_fm.keys()):
        if base_fm.get(key) != cmp_fm.get(key):
            drift["frontmatter_drift"][key] = {"baseline": base_fm.get(key, "MISSING"), "compare": cmp_fm.get(key, "MISSING")}

    # Structural drift: sections (## headers)
    import re
    base_sections = set(re.findall(r"^##\s+(.+)$", base_text, re.MULTILINE))
    cmp_sections = set(re.findall(r"^##\s+(.+)$", cmp_text, re.MULTILINE))
    added = cmp_sections - base_sections
    removed = base_sections - cmp_sections
    if added or removed:
        drift["structural_drift"] = {}
        if added:
            drift["structural_drift"]["sections_added"] = list(added)
        if removed:
            drift["structural_drift"]["sections_removed"] = list(removed)

    return [TextContent(type="text", text=json.dumps(drift, indent=2))]


HANDLERS = {
    "radr_validate_contract": _handle_validate_contract,
    "radr_list_protocols": _handle_list_protocols,
    "radr_get_protocol_status": _handle_get_protocol_status,
    "radr_check_drift": _handle_check_drift,
}


async def run_server() -> None:
    server = Server("radriloniuma-protocols")
    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return TOOLS
    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any] | None) -> list[TextContent]:
        if name not in HANDLERS:
            return [TextContent(type="text", text=f"UNKNOWN_TOOL: {name}")]
        return await HANDLERS[name](arguments or {})
    async with stdio_server(server) as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main() -> None:
    asyncio.run(run_server())


if __name__ == "__main__":
    main()
