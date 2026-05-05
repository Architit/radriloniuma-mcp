"""Tests for RADRILONIUMA MCP Executor Server."""

import pytest
from pathlib import Path

from radriloniuma_mcp.executor import (
    _sentinel_check,
    _execute_command,
    _handle_do,
)


@pytest.fixture(autouse=True)
def sentinel_active(monkeypatch):
    monkeypatch.setenv("MCP_SENTINEL_GUARD", "ACTIVE")
    monkeypatch.setenv("MCP_TRUST_CLASS", "TRUSTED_INTERNAL")


@pytest.fixture
def tmp_radr_root(tmp_path, monkeypatch):
    root = tmp_path / "RADRILONIUMA"
    root.mkdir()
    monkeypatch.setenv("RADRILONIUMA_ROOT", str(root))
    import radriloniuma_mcp.executor as exe
    exe.RADRILONIUMA_ROOT = root
    return root


class TestSentinel:
    def test_blocks_inactive(self, monkeypatch):
        monkeypatch.setenv("MCP_SENTINEL_GUARD", "INACTIVE")
        assert _sentinel_check("shell") is False

    def test_blocks_untrusted_deploy(self, monkeypatch):
        monkeypatch.setenv("MCP_TRUST_CLASS", "TRUSTED_EXTERNAL")
        assert _sentinel_check("deploy") is False
        assert _sentinel_check("shell") is False

    def test_allows_safe_actions(self):
        assert _sentinel_check("sync") is True
        assert _sentinel_check("test") is True
        assert _sentinel_check("python") is True


class TestExecuteCommand:
    async def test_echo(self):
        result = await _execute_command(["echo", "hello"])
        assert result["success"] is True
        assert "hello" in result["stdout"]

    async def test_invalid_command(self):
        result = await _execute_command(["nonexistent_command_12345"])
        assert result["success"] is False

    async def test_timeout(self):
        result = await _execute_command(["sleep", "10"], timeout=1)
        assert result["success"] is False
        assert "TIMEOUT" in result["stderr"]


class TestHandleDo:
    async def test_shell_echo(self, tmp_radr_root):
        result = await _handle_do({
            "action_type": "shell",
            "command": "echo 'test passed'",
            "target_dir": "",
            "skip_preflight": True,
        })
        assert "SENTINEL_REJECT" not in result[0].text
        assert "test passed" in result[0].text

    async def test_python_execute(self, tmp_radr_root):
        result = await _handle_do({
            "action_type": "python",
            "command": "print('python ok')",
        })
        assert "SENTINEL_REJECT" not in result[0].text
        assert "python ok" in result[0].text

    async def test_git_status(self, tmp_radr_root):
        # Initialize git repo in tmp dir
        import subprocess
        subprocess.run(["git", "init"], cwd=str(tmp_radr_root), capture_output=True)
        result = await _handle_do({
            "action_type": "git",
            "command": "status --short",
            "target_dir": "",
            "skip_preflight": True,
        })
        assert "SENTINEL_REJECT" not in result[0].text
        assert result[0].text is not None

    async def test_sentinel_reject(self, monkeypatch):
        monkeypatch.setenv("MCP_SENTINEL_GUARD", "INACTIVE")
        result = await _handle_do({
            "action_type": "shell",
            "command": "echo test",
        })
        assert "SENTINEL_REJECT" in result[0].text

    async def test_unknown_action(self, tmp_radr_root):
        result = await _handle_do({
            "action_type": "unknown",
            "command": "test",
        })
        assert "UNKNOWN_ACTION_TYPE" in result[0].text
