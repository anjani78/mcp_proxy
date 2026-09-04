import logging
from pathlib import Path
from contextlib import asynccontextmanager
from logging.handlers import TimedRotatingFileHandler

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
from mcp.server.sse import SseServerTransport

from core.proxy import MCPProxyEngine
from api.routes import setup_routes

# Configure Logger Modules (Outputting to both console and dynamic Daily Timed Logs)
LOGS_DIR = Path("logs")
LOGS_DIR.mkdir(exist_ok=True)

log_formatter = logging.Formatter("%(asctime)s [%(levelname)s] [%(name)s] %(message)s")
logger = logging.getLogger("mcp-http-proxy")
logger.setLevel(logging.INFO)

console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)
logger.addHandler(console_handler)

file_handler = TimedRotatingFileHandler(
    filename=str(LOGS_DIR / "mcp_proxy.log"),
    when="midnight",
    interval=1,
    backupCount=30,
    encoding="utf-8"
)
file_handler.suffix = "%Y-%m-%d"
file_handler.setFormatter(log_formatter)
logger.addHandler(file_handler)
logger.propagate = False

# Initialize unified core elements
engine = MCPProxyEngine()
sse_transport = SseServerTransport("/messages/")

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Executing lifespan startup hooks sequence...")
    # Boot up downstream client network tunnels to proxied hosts
    await engine.init_all_remotes()
    yield
    logger.info("Tearing down server lifespan. Closing active loops.")

app = FastAPI(
    title="MCP HTTP/SSE Proxy Server", 
    version="2.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Bind routes
setup_routes(app, engine, sse_transport)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
