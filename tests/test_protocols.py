"""Tests for RADRILONIUMA MCP Protocols Server."""

import pytest
from pathlib import Path

from radriloniuma_mcp.protocols import (
    _sentinel_check,
    _extract_frontmatter,
    _handle_validate_contract,
    _handle_list_protocols,
    _handle_get_protocol_status,
    _handle_check_drift,
)


@pytest.fixture(autouse=True)
def sentinel_active(monkeypatch):
    monkeypatch.setenv("MCP_SENTINEL_GUARD", "ACTIVE")
    monkeypatch.setenv("MCP_TRUST_CLASS", "TRUSTED_INTERNAL")


@pytest.fixture
def tmp_radr_root(tmp_path, monkeypatch):
    root = tmp_path / "RADRILONIUMA"
    (root / "data" / "source" / "protocols").mkdir(parents=True)
    (root / "contract").mkdir(parents=True)
    monkeypatch.setenv("RADRILONIUMA_ROOT", str(root))
    import radriloniuma_mcp.protocols as proto
    proto.RADRILONIUMA_ROOT = root
    return root


class TestSentinel:
    def test_blocks_inactive(self, monkeypatch):
        monkeypatch.setenv("MCP_SENTINEL_GUARD", "INACTIVE")
        assert _sentinel_check("validate", "contract/test.md") is False

    def test_blocks_traversal(self, tmp_radr_root):
        assert _sentinel_check("validate", "../etc/passwd") is False

    def test_allows_protocols(self, tmp_radr_root):
        assert _sentinel_check("list", "data/source/protocols") is True

    def test_blocks_outside_scope(self, tmp_radr_root):
        assert _sentinel_check("validate", "chronolog/log.md") is False


class TestExtractFrontmatter:
    def test_extracts_yaml_frontmatter(self):
        content = "---\nversion: v1\nstatus: ACTIVE\n---\n# Body\n"
        fm = _extract_frontmatter(content)
        assert fm.get("version") == "v1"
        assert fm.get("status") == "ACTIVE"

    def test_no_frontmatter(self):
        content = "# Just a header\nNo frontmatter here.\n"
        fm = _extract_frontmatter(content)
        assert fm == {}


class TestValidateContract:
    async def test_valid_contract(self, tmp_radr_root):
        test_file = tmp_radr_root / "contract" / "test_contract.md"
        test_file.write_text("---\nversion: v1\nstatus: ACTIVE\n---\n# Purpose\nDetails here.\n")

        result = await _handle_validate_contract({"contract_path": "contract/test_contract.md"})
        assert "SENTINEL_REJECT" not in result[0].text
        assert '"valid": true' in result[0].text

    async def test_missing_field(self, tmp_radr_root):
        test_file = tmp_radr_root / "contract" / "bad_contract.md"
        test_file.write_text("---\nversion: v1\n---\n# No status\n")

        result = await _handle_validate_contract({"contract_path": "contract/bad_contract.md"})
        assert "MISSING_FIELD: status" in result[0].text
        assert '"valid": false' in result[0].text

    async def test_file_not_found(self, tmp_radr_root):
        result = await _handle_validate_contract({"contract_path": "contract/missing.md"})
        assert "FILE_NOT_FOUND" in result[0].text

    async def test_sentinel_reject(self, monkeypatch, tmp_radr_root):
        monkeypatch.setenv("MCP_SENTINEL_GUARD", "INACTIVE")
        result = await _handle_validate_contract({"contract_path": "contract/test.md"})
        assert "SENTINEL_REJECT" in result[0].text


class TestListProtocols:
    async def test_list_all(self, tmp_radr_root):
        (tmp_radr_root / "contract" / "c1.md").write_text("---\nversion: v1\nstatus: ACTIVE\n---\n")
        (tmp_radr_root / "data" / "source" / "protocols" / "p1.md").write_text("---\nversion: v2\nstatus: DRAFT\n---\n")

        result = await _handle_list_protocols({"scope": "all", "status_filter": ""})
        assert "c1.md" in result[0].text
        assert "p1.md" in result[0].text

    async def test_filter_by_status(self, tmp_radr_root):
        (tmp_radr_root / "contract" / "active.md").write_text("---\nstatus: ACTIVE\n---\n")
        (tmp_radr_root / "contract" / "draft.md").write_text("---\nstatus: DRAFT\n---\n")

        result = await _handle_list_protocols({"scope": "contracts", "status_filter": "ACTIVE"})
        assert "active.md" in result[0].text
        assert "draft.md" not in result[0].text


class TestGetProtocolStatus:
    async def test_get_status(self, tmp_radr_root):
        test_file = tmp_radr_root / "contract" / "protocol.md"
        test_file.write_text("---\nversion: v1.2\nstatus: ACTIVE\nlast_updated_utc: 2026-01-01\n---\n")

        result = await _handle_get_protocol_status({"protocol_path": "contract/protocol.md"})
        assert "ACTIVE" in result[0].text
        assert "v1.2" in result[0].text

    async def test_not_found(self, tmp_radr_root):
        result = await _handle_get_protocol_status({"protocol_path": "contract/missing.md"})
        assert "FILE_NOT_FOUND" in result[0].text


class TestCheckDrift:
    async def test_drift_detected(self, tmp_radr_root):
        base = tmp_radr_root / "contract" / "base.md"
        base.write_text("---\nversion: v1\nstatus: ACTIVE\n---\n## Section A\n")
        cmp = tmp_radr_root / "contract" / "cmp.md"
        cmp.write_text("---\nversion: v2\nstatus: DEPRECATED\n---\n## Section A\n## Section B\n")

        result = await _handle_check_drift({"baseline_path": "contract/base.md", "compare_path": "contract/cmp.md"})
        assert "DEPRECATED" in result[0].text
        assert "sections_added" in result[0].text

    async def test_no_drift(self, tmp_radr_root):
        base = tmp_radr_root / "contract" / "base.md"
        base.write_text("---\nversion: v1\n---\n## Section\n")
        cmp = tmp_radr_root / "contract" / "cmp.md"
        cmp.write_text("---\nversion: v1\n---\n## Section\n")

        result = await _handle_check_drift({"baseline_path": "contract/base.md", "compare_path": "contract/cmp.md"})
        assert "SENTINEL_REJECT" not in result[0].text
