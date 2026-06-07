# Copyright (c) 2026-06-07 RADRILONIUMA / TRIANIUMA Kingdom. All rights reserved.
"""Unit tests for the Gateway MCP server."""

from __future__ import annotations

import pytest

from radriloniuma_mcp.gateway import _sentinel_check


class TestSentinelCheck:
    """Zero-trust validation gate tests."""

    def test_sentinel_active_allows_internal(self, monkeypatch):
        monkeypatch.setenv("MCP_SENTINEL_GUARD", "ACTIVE")
        monkeypatch.setenv("MCP_TRUST_CLASS", "TRUSTED_INTERNAL")
        assert _sentinel_check("mcp_local_gateway", "read", "data/source/protocols") is True

    def test_sentinel_inactive_blocks_all(self, monkeypatch):
        monkeypatch.setenv("MCP_SENTINEL_GUARD", "INACTIVE")
        monkeypatch.setenv("MCP_TRUST_CLASS", "TRUSTED_INTERNAL")
        assert _sentinel_check("mcp_local_gateway", "read", "data/source") is False

    def test_path_traversal_blocked(self, monkeypatch):
        monkeypatch.setenv("MCP_SENTINEL_GUARD", "ACTIVE")
        monkeypatch.setenv("MCP_TRUST_CLASS", "TRUSTED_INTERNAL")
        assert _sentinel_check("mcp_local_gateway", "read", "../../etc/passwd") is False

    def test_untrusted_class_blocked(self, monkeypatch):
        monkeypatch.setenv("MCP_SENTINEL_GUARD", "ACTIVE")
        monkeypatch.setenv("MCP_TRUST_CLASS", "UNTRUSTED")
        assert _sentinel_check("mcp_local_gateway", "read", "data/source") is False
