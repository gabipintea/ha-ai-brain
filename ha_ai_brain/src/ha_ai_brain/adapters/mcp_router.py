"""Model Context Protocol (MCP) Client Adapter (Router Diagnostics, Network Scan & External MCPs)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from ha_ai_brain.ports.mcp import McpClientPort

ToolHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


class ExtensibleMcpClientAdapter(McpClientPort):
    """
    Connects external Model Context Protocol (MCP) servers (via stdio/SSE) and provides
    built-in network/router MCP tools for the Repair & Diagnostics Agent (e.g. discovering
    devices whose DHCP IP changed, reserving static DHCP leases on UniFi/MikroTik/OPNsense,
    and reconfiguring Home Assistant integrations).
    """

    def __init__(self) -> None:
        self._handlers: dict[tuple[str, str], ToolHandler] = {}
        self._registered_servers: dict[str, dict[str, Any]] = {
            "router_network_mcp": {
                "description": "Local Router & LAN Diagnostics MCP (DHCP Lease Table, ARP Scan, Static IP Reservation)",
                "tools": [
                    {
                        "name": "find_device_by_hostname_or_mac",
                        "description": "Scan router DHCP leases and ARP table to find the current IP of an unavailable HA device.",
                    },
                    {
                        "name": "reserve_static_dhcp_lease",
                        "description": "Lock a device's current IP address as a static DHCP reservation on the router.",
                    },
                ],
            }
        }

    def register_mcp_server(self, server_name: str, description: str, tools: list[dict[str, Any]]) -> None:
        self._registered_servers[server_name] = {"description": description, "tools": tools}

    async def list_tools(self, server_name: str | None = None) -> list[dict[str, Any]]:
        if server_name:
            srv = self._registered_servers.get(server_name, {})
            return list(srv.get("tools", []))
        out: list[dict[str, Any]] = []
        for s_name, info in self._registered_servers.items():
            for t in info.get("tools", []):
                out.append({"server": s_name, **t})
        return out

    def register_tool_handler(self, server_name: str, tool_name: str, handler: ToolHandler) -> None:
        """Attach a real implementation (e.g. a router API client) for a tool exposed by a registered server."""
        self._handlers[(server_name, tool_name)] = handler

    async def call_tool(self, server_name: str, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        handler = self._handlers.get((server_name, tool_name))
        if handler is None:
            # Never fabricate results: an agent must be able to tell a tool is not connected.
            return {
                "status": "unavailable",
                "server": server_name,
                "tool": tool_name,
                "message": "No connector is configured for this MCP tool.",
            }
        return await handler(arguments)
