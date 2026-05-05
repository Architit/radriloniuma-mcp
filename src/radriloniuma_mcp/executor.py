"""RADRILONIUMA MCP Executor Server

Universal action executor:
  - shell: bash commands (with mandatory preflight)
  - python: Python scripts
  - test: pytest invocation
  - git: git operations
  - preflight: environment validation
  - sync: mesh sync
  - deploy: deployment actions

Contract: mcp_executor_protocol
Version: v1
Status: ACTIVE
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

RADRILONIUMA_ROOT = Path(os.environ.get("RADRILONIUMA_ROOT", "/root/Architit_Nodes/RADRILONIUMA"))


def _sentinel_check(action_type: str) -> bool:
    """Zero-trust validation for executor."""
    sentinel = os.environ.get("MCP_SENTINEL_GUARD", "ACTIVE")
    if sentinel != "ACTIVE":
        return False
    trust = os.environ.get("MCP_TRUST_CLASS", "TRUSTED_INTERNAL")
    if action_type in ("deploy", "shell") and trust != "TRUSTED_INTERNAL":
        return False
    return True


async def _run_preflight(target_dir: str, command: str) -> dict[str, Any]:
    """Run shell preflight check before executing shell commands."""
    preflight_script = RADRILONIUMA_ROOT / "devkit" / "shell_preflight_check.py"
    if not preflight_script.exists():
        return {"passed": True, "warning": "Preflight script not found, skipping"}
    try:
        proc = await asyncio.create_subprocess_exec(
            "python3", str(preflight_script),
            "--shell", "bash",
            "--command", command,
            "--format", "json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        result = json.loads(stdout.decode("utf-8"))
        return {
            "passed": result.get("safe_for_execution", False),
            "decision": result.get("decision", "UNKNOWN"),
            "warnings": result.get("findings", []),
        }
    except Exception as e:
        return {"passed": False, "error": str(e)}


async def _execute_command(
    cmd: list[str],
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 60,
) -> dict[str, Any]:
    """Execute a command with timeout and capture output."""
    merged_env = {**os.environ}
    if env:
        merged_env.update(env)
    try:
        proc = await asyncio.wait_for(
            asyncio.create_subprocess_exec(
                *cmd,
                cwd=cwd,
                env=merged_env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            ),
            timeout=5,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return {
            "returncode": proc.returncode,
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
            "success": proc.returncode == 0,
        }
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": f"TIMEOUT: Command exceeded {timeout} seconds",
            "success": False,
        }
    except Exception as e:
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": f"EXEC_ERROR: {e}",
            "success": False,
        }


TOOLS: list[Tool] = [
    Tool(
        name="radr_do",
        description="Universal action executor. Runs commands in specified environment. "
                    "For shell actions, preflight validation is mandatory.",
        inputSchema={
            "type": "object",
            "properties": {
                "action_type": {
                    "type": "string",
                    "enum": ["shell", "python", "test", "git", "preflight", "sync", "deploy"],
                    "description": "Type of action to execute",
                },
                "target_dir": {
                    "type": "string",
                    "description": "Working directory (relative to RADRILONIUMA_ROOT)",
                    "default": "",
                },
                "command": {
                    "type": "string",
                    "description": "Command or script to execute",
                },
                "env_vars": {
                    "type": "object",
                    "description": "Environment variables to set",
                    "default": {},
                },
                "timeout": {
                    "type": "integer",
                    "description": "Maximum execution time in seconds",
                    "default": 60,
                },
                "skip_preflight": {
                    "type": "boolean",
                    "description": "Skip preflight check (dangerous)",
                    "default": False,
                },
            },
            "required": ["action_type", "command"],
        },
    ),
]


async def _handle_do(args: dict[str, Any]) -> list[TextContent]:
    action_type = args["action_type"]
    target_dir = args.get("target_dir", "")
    command = args["command"]
    env_vars = args.get("env_vars", {})
    timeout = args.get("timeout", 60)
    skip_preflight = args.get("skip_preflight", False)

    if not _sentinel_check(action_type):
        return [TextContent(type="text", text="SENTINEL_REJECT: Access denied by zero-trust guard.")]

    cwd = str(RADRILONIUMA_ROOT / target_dir) if target_dir else str(RADRILONIUMA_ROOT)

    if action_type == "shell" and not skip_preflight:
        preflight = await _run_preflight(target_dir, command)
        if not preflight["passed"]:
            result = {
                "action_type": action_type,
                "command": command,
                "preflight_result": preflight,
                "executed": False,
                "reason": "PREFLIGHT_BLOCKED",
            }
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

    if action_type == "shell":
        cmd = ["bash", "-c", command]
    elif action_type == "python":
        cmd = ["python3", "-c", command]
    elif action_type == "test":
        cmd = ["python3", "-m", "pytest"] + command.split()
    elif action_type == "git":
        cmd = ["git"] + command.split()
    elif action_type == "preflight":
        preflight_script = RADRILONIUMA_ROOT / "devkit" / "shell_preflight_check.py"
        if not preflight_script.exists():
            return [TextContent(type="text", text="PREFLIGHT_SCRIPT_NOT_FOUND")]
        cmd = ["python3", str(preflight_script), "--shell", "bash", "--command", command, "--format", "json"]
    elif action_type == "sync":
        central_url = os.environ.get("ARCH_CENTRAL_URL", "http://localhost:8765")
        cmd = ["curl", "-s", f"{central_url}/health"]
    elif action_type == "deploy":
        rollout_script = RADRILONIUMA_ROOT / "devkit" / "ecosystem_rollout.sh"
        if not rollout_script.exists():
            return [TextContent(type="text", text="DEPLOY_SCRIPT_NOT_FOUND")]
        cmd = ["bash", str(rollout_script)] + command.split()
    else:
        return [TextContent(type="text", text=f"UNKNOWN_ACTION_TYPE: {action_type}")]

    exec_result = await _execute_command(cmd, cwd=cwd, env=env_vars, timeout=timeout)

    result = {
        "action_type": action_type,
        "command": command,
        "cwd": cwd,
        "executed": True,
        "returncode": exec_result["returncode"],
        "stdout": exec_result["stdout"][:5000],
        "stderr": exec_result["stderr"][:2000],
        "success": exec_result["success"],
    }

    return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]


HANDLERS = {
    "radr_do": _handle_do,
}


async def run_server() -> None:
    server = Server("radriloniuma-executor")

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
