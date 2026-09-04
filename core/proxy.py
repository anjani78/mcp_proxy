import asyncio
import logging
import json
from typing import Dict, Any, List

from mcp.server import Server, ServerRequestContext
from mcp.client.streamable_http import streamable_http_client
from mcp.client.session import ClientSession
import mcp.types as types
from mcp.types import ListToolsResult, CallToolResult, PaginatedRequestParams, CallToolRequestParams

from config.manager import ConfigManager
from observability.tracker import ObservabilityTracker

logger = logging.getLogger("mcp-http-proxy.core")

class MCPProxyEngine:
    def __init__(self, name: str = "agnostic-http-mcp-proxy"):
        self.remote_configs: Dict[str, str] = ConfigManager.load_config()
        self.active_sessions: Dict[str, ClientSession] = {}
        
        self.server = Server(
            name,
            on_list_tools=self.handle_list_tools,
            on_call_tool=self.handle_call_tool
        )

    async def connect_to_remote(self, name: str, url: str):
        async def session_loop():
            try:
                logger.info(f"Connecting to unified remote gateway [{name}] at {url}...")
                async with streamable_http_client(url) as (read_stream, write_stream):
                    async with ClientSession(read_stream, write_stream) as session:
                        await session.initialize()
                        self.active_sessions[name] = session
                        logger.info(f"✅ Successfully integrated remote server [{name}]. Discovery complete.")
                        
                        while name in self.active_sessions:
                            await asyncio.sleep(1)
            except (Exception, ExceptionGroup) as e:
                logger.error(f"⚠️ Remote server [{name}] handshake failed or dropped: {e}")
                if name in self.active_sessions:
                    del self.active_sessions[name]
                
                await asyncio.sleep(10)
                if name in self.remote_configs:
                    logger.info(f"Retrying connection to remote server [{name}]...")
                    asyncio.create_task(session_loop())

        asyncio.create_task(session_loop())

    async def init_all_remotes(self):
        if not self.remote_configs:
            logger.info("No remote servers scheduled for boot orchestration.")
            return
        for name, url in self.remote_configs.items():
            await self.connect_to_remote(name, url)

    async def handle_list_tools(self, ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
        logger.info("Received request to compile full tools registry schema list...")
        tools = [
            types.Tool(
                name="proxy_add_server",
                description="Dynamically add and connect a new remote HTTP/SSE MCP Server.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Unique identifier for the server."},
                        "url": {"type": "string", "description": "The remote HTTP SSE endpoint URL."}
                    },
                    "required": ["name", "url"]
                }
            ),
            types.Tool(
                name="proxy_list_servers",
                description="Lists all currently configured and active remote proxied servers.",
                input_schema={"type": "object", "properties": {}}
            )
        ]
        
        for server_name, session in self.active_sessions.items():
            try:
                remote_tools = await session.list_tools()
                for tool in remote_tools.tools:
                    if hasattr(tool, "output_schema") or "outputSchema" in str(tool):
                        tool.output_schema = None
                    tool.name = f"{server_name}__{tool.name}"
                    tools.append(tool)
            except Exception as e:
                logger.error(f"Could not fetch tools from remote server [{server_name}]: {e}")
        
        return ListToolsResult(tools=tools)

    async def handle_call_tool(self, ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        name = params.name
        arguments = params.arguments or {}
        
        async with ObservabilityTracker(tool_name=name, arguments=arguments) as metrics:
            if name == "proxy_add_server":
                s_name = arguments.get("name")
                s_url = arguments.get("url")
                if not s_name or not s_url:
                    return CallToolResult(content=[types.TextContent(type="text", text="Error: Missing 'name' or 'url'.")])
                
                self.remote_configs[s_name] = s_url
                ConfigManager.save_config(self.remote_configs)
                await self.connect_to_remote(s_name, s_url)
                return CallToolResult(content=[types.TextContent(type="text", text=f"Server '{s_name}' registered and initialization started.")])

            if name == "proxy_list_servers":
                status = {k: ("Active" if k in self.active_sessions else "Disconnected") for k in self.remote_configs}
                return CallToolResult(content=[types.TextContent(type="text", text=json.dumps(status, indent=2))])

            if "__" in name:
                target_server, original_tool_name = name.split("__", 1)
                session = self.active_sessions.get(target_server)
                
                if not session:
                    return CallToolResult(content=[types.TextContent(type="text", text=f"Error: Target server '{target_server}' is offline.")])
                
                try:
                    response = await session.call_tool(name=original_tool_name, arguments=arguments)
                    metrics["status"] = "success"
                    metrics["response_summary"] = str(response.content)[:200]
                    return CallToolResult(content=response.content)
                except Exception as e:
                    metrics["status"] = "failed"
                    metrics["error"] = str(e)
                    return CallToolResult(content=[types.TextContent(type="text", text=f"Error during remote execution: {e}")])

            return CallToolResult(content=[types.TextContent(type="text", text=f"Unknown tool error: {name}")])
