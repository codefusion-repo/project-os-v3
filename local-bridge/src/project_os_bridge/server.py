"""Stdio-only MCP bootstrap. No repository, command or credential access tools."""
import argparse
import os
from pathlib import Path

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from .probe import Probe


def build_server(probe: Probe):
    mcp = MCPServer("Project OS Local Bridge Probe")
    read_only = ToolAnnotations(read_only_hint=True, open_world_hint=False)

    @mcp.tool(annotations=read_only)
    def health() -> dict:
        """Report bootstrap capability and its limited authorization scope."""
        return {"status": "ready", "mode": "disposable-probe", "caller_identity_verified": False,
                "repository_access": False, "write_enabled": probe.write_enabled()}

    @mcp.tool(annotations=read_only)
    def sandbox_read() -> dict:
        """Read the single fixed disposable marker."""
        return probe.read()

    @mcp.tool(annotations=read_only)
    def sandbox_status() -> dict:
        """Report fixed marker and whether local write opt-in is enabled."""
        return {**probe.read(), "write_enabled": probe.write_enabled()}

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False,
                                         idempotent_hint=True, open_world_hint=False))
    def sandbox_write() -> dict:
        """Persist the fixed disposable marker only while local opt-in exists."""
        return probe.write()

    return mcp


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-dir", required=True, type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    build_server(Probe(args.state_dir)).run()


if __name__ == "__main__":
    main()
