"""Tests for RADRILONIUMA MCP Filesystem Server."""

import os
import pytest
from pathlib import Path

from radriloniuma_mcp.filesystem import (
    _sentinel_check,
    _sha256,
    _handle_read_file,
    _handle_write_file,
    _handle_edit_file,
    _handle_sync_gateway,
)


@pytest.fixture(autouse=True)
def sentinel_active(monkeypatch):
    monkeypatch.setenv("MCP_SENTINEL_GUARD", "ACTIVE")
    monkeypatch.setenv("MCP_TRUST_CLASS", "TRUSTED_INTERNAL")


@pytest.fixture
def tmp_radr_root(tmp_path, monkeypatch):
    """Create a temporary RADRILONIUMA_ROOT structure."""
    root = tmp_path / "RADRILONIUMA"
    (root / ".gateway" / "storage" / "local").mkdir(parents=True)
    (root / "data" / "local").mkdir(parents=True)
    (root / "data" / "source").mkdir(parents=True)
    (root / "contract").mkdir(parents=True)
    monkeypatch.setenv("RADRILONIUMA_ROOT", str(root))
    import radriloniuma_mcp.filesystem as fs
    fs.RADRILONIUMA_ROOT = root
    return root


class TestSentinel:
    def test_sentinel_blocks_when_inactive(self, monkeypatch, tmp_radr_root):
        monkeypatch.setenv("MCP_SENTINEL_GUARD", "INACTIVE")
        assert _sentinel_check("read", ".gateway/test.txt") is False

    def test_sentinel_blocks_path_traversal(self, tmp_radr_root):
        assert _sentinel_check("read", "../etc/passwd") is False

    def test_sentinel_allows_read_scope(self, tmp_radr_root):
        assert _sentinel_check("read", "data/source/protocol.md") is True

    def test_sentinel_allows_write_scope(self, tmp_radr_root):
        assert _sentinel_check("write", ".gateway/test.txt", write=True) is True

    def test_sentinel_blocks_write_outside_scope(self, tmp_radr_root):
        assert _sentinel_check("write", "contract/secret.md", write=True) is False

    def test_sentinel_blocks_read_outside_scope(self, tmp_radr_root):
        assert _sentinel_check("read", "chronolog/hidden.log") is False


class TestReadFile:
    async def test_read_file_success(self, tmp_radr_root):
        test_file = tmp_radr_root / "data" / "source" / "test.md"
        test_file.write_text("# Hello\nWorld\n", encoding="utf-8")

        result = await _handle_read_file({"file_path": "data/source/test.md"})
        assert "FILE_NOT_FOUND" not in result[0].text
        assert "Hello" in result[0].text
        assert "lines 1-3 of 3" in result[0].text

    async def test_read_file_with_line_range(self, tmp_radr_root):
        test_file = tmp_radr_root / "data" / "source" / "test.md"
        test_file.write_text("line1\nline2\nline3\nline4\n", encoding="utf-8")

        result = await _handle_read_file({
            "file_path": "data/source/test.md",
            "start_line": 2,
            "end_line": 3,
        })
        assert "line2" in result[0].text
        assert "line1" not in result[0].text

    async def test_read_file_not_found(self, tmp_radr_root):
        result = await _handle_read_file({"file_path": "data/source/missing.md"})
        assert "FILE_NOT_FOUND" in result[0].text

    async def test_read_file_sentinel_reject(self, monkeypatch, tmp_radr_root):
        monkeypatch.setenv("MCP_SENTINEL_GUARD", "INACTIVE")
        result = await _handle_read_file({"file_path": "data/source/test.md"})
        assert "SENTINEL_REJECT" in result[0].text


class TestWriteFile:
    async def test_write_file_success(self, tmp_radr_root):
        content = "# New File\nContent here.\n"
        sha = _sha256(content)

        result = await _handle_write_file({
            "file_path": ".gateway/storage/local/new.md",
            "content": content,
            "content_sha256": sha,
        })
        assert "SUCCESS" in result[0].text
        assert (tmp_radr_root / ".gateway" / "storage" / "local" / "new.md").read_text() == content

    async def test_write_file_integrity_mismatch(self, tmp_radr_root):
        result = await _handle_write_file({
            "file_path": ".gateway/storage/local/new.md",
            "content": "test",
            "content_sha256": "0000",
        })
        assert "INTEGRITY_MISMATCH" in result[0].text

    async def test_write_file_sentinel_reject(self, monkeypatch, tmp_radr_root):
        monkeypatch.setenv("MCP_SENTINEL_GUARD", "INACTIVE")
        content = "test"
        result = await _handle_write_file({
            "file_path": ".gateway/storage/local/new.md",
            "content": content,
            "content_sha256": _sha256(content),
        })
        assert "SENTINEL_REJECT" in result[0].text


class TestEditFile:
    async def test_edit_replace(self, tmp_radr_root):
        test_file = tmp_radr_root / ".gateway" / "config.yaml"
        test_file.write_text("old_value: 1\nother: 2\n", encoding="utf-8")

        result = await _handle_edit_file({
            "file_path": ".gateway/config.yaml",
            "mode": "replace",
            "old_string": "old_value: 1",
            "new_string": "new_value: 99",
        })
        assert "SUCCESS" in result[0].text
        text = test_file.read_text()
        assert "new_value: 99" in text
        assert "old_value: 1" not in text

    async def test_edit_insert(self, tmp_radr_root):
        test_file = tmp_radr_root / ".gateway" / "config.yaml"
        test_file.write_text("header: true\n", encoding="utf-8")

        result = await _handle_edit_file({
            "file_path": ".gateway/config.yaml",
            "mode": "insert",
            "anchor": "header: true",
            "new_string": "\ninserted: yes",
        })
        assert "SUCCESS" in result[0].text
        assert "inserted: yes" in test_file.read_text()

    async def test_edit_delete(self, tmp_radr_root):
        test_file = tmp_radr_root / ".gateway" / "config.yaml"
        test_file.write_text("line1\nline2\nline3\nline4\n", encoding="utf-8")

        result = await _handle_edit_file({
            "file_path": ".gateway/config.yaml",
            "mode": "delete",
            "start_line": 2,
            "end_line": 3,
        })
        assert "SUCCESS" in result[0].text
        text = test_file.read_text()
        assert "line1" in text
        assert "line2" not in text
        assert "line3" not in text
        assert "line4" in text

    async def test_edit_anchor_not_found(self, tmp_radr_root):
        test_file = tmp_radr_root / ".gateway" / "config.yaml"
        test_file.write_text("header: true\n", encoding="utf-8")

        result = await _handle_edit_file({
            "file_path": ".gateway/config.yaml",
            "mode": "replace",
            "old_string": "missing",
            "new_string": "new",
        })
        assert "REPLACE_ANCHOR_NOT_FOUND" in result[0].text


class TestSyncGateway:
    async def test_sync_list(self, tmp_radr_root):
        (tmp_radr_root / ".gateway" / "storage" / "local" / "file1.txt").write_text("a")
        (tmp_radr_root / ".gateway" / "storage" / "local" / "subdir").mkdir()
        (tmp_radr_root / ".gateway" / "storage" / "local" / "subdir" / "file2.txt").write_text("b")

        result = await _handle_sync_gateway({"action": "list"})
        assert "file1.txt" in result[0].text
        assert "file2.txt" in result[0].text

    async def test_sync_from_data_dry_run(self, tmp_radr_root):
        (tmp_radr_root / "data" / "local" / "test.md").write_text("data content")

        result = await _handle_sync_gateway({"action": "sync_from_data", "dry_run": True})
        assert "DRY_RUN" in result[0].text
        assert "test.md" in result[0].text
        assert not (tmp_radr_root / ".gateway" / "storage" / "local" / "test.md").exists()

    async def test_sync_from_data_executed(self, tmp_radr_root):
        (tmp_radr_root / "data" / "local" / "test.md").write_text("data content")

        result = await _handle_sync_gateway({"action": "sync_from_data", "dry_run": False})
        assert "EXECUTED" in result[0].text
        assert (tmp_radr_root / ".gateway" / "storage" / "local" / "test.md").read_text() == "data content"
