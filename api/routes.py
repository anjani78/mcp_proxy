import logging
from fastapi import FastAPI, Request
from starlette.routing import Route, Mount
from starlette.responses import Response
from mcp.server.models import InitializationOptions
from mcp.server.sse import SseServerTransport
from core.proxy import MCPProxyEngine

logger = logging.getLogger("mcp-http-proxy.api")

def setup_routes(app: FastAPI, engine: MCPProxyEngine, sse_transport: SseServerTransport):
    async def handle_sse(request: Request):
        client_ip = request.client.host if request.client else "Unknown"
        logger.info(f"Inbound stream channel request received from client at IP: {client_ip}")
        
        async with sse_transport.connect_sse(
            request.scope, request.receive, request._send
        ) as (read_stream, write_stream):
            options = InitializationOptions(
                server_name=engine.server.name,
                server_version="2.0.0",
                capabilities=engine.server.get_capabilities()
            )
            await engine.server.run(read_stream, write_stream, options)
        
        logger.info("Client has disconnected from SSE channel cleanly.")
        return Response()

    app.router.routes.extend([
        Route("/sse", endpoint=handle_sse, methods=["GET"]),
        Mount("/messages", app=sse_transport.handle_post_message)
    ])
    logger.info("✅ Raw ASGI routing layers successfully mounted.")
