"""Tests for the Search MCP server."""

from __future__ import annotations

import pytest

from radriloniuma_mcp.search import _sentinel_check


class TestSentinelCheck:
    """Zero-trust validation gate tests for search."""

    def test_sentinel_active_allows_internal(self, monkeypatch):
        monkeypatch.setenv("MCP_SENTINEL_GUARD", "ACTIVE")
        assert _sentinel_check("data/source/protocols") is True

    def test_sentinel_inactive_blocks_all(self, monkeypatch):
        monkeypatch.setenv("MCP_SENTINEL_GUARD", "INACTIVE")
        assert _sentinel_check("data/source") is False

    def test_path_traversal_blocked(self, monkeypatch):
        monkeypatch.setenv("MCP_SENTINEL_GUARD", "ACTIVE")
        assert _sentinel_check("../../etc/passwd") is False

    def test_none_path_allowed(self, monkeypatch):
        monkeypatch.setenv("MCP_SENTINEL_GUARD", "ACTIVE")
        assert _sentinel_check(None) is True
