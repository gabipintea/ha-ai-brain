"""Port Interface for Model Context Protocol (MCP) Servers & External Tool Extensions."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class McpClientPort(ABC):
    """
    Extensibility port enabling agents (such as the Repair & Diagnostics Agent)
    to discover and invoke tools exposed by external MCP servers (e.g., Network Router MCP,
    UniFi/MikroTik/OPNsense DHCP reservation tools, Zigbee2MQTT diagnostics, Solar Inverter APIs).
    """

    @abstractmethod
    async def list_tools(self, server_name: str | None = None) -> list[dict[str, Any]]:
        """List available MCP tools across connected MCP servers."""

    @abstractmethod
    async def call_tool(self, server_name: str, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Invoke a specific tool on an MCP server."""
