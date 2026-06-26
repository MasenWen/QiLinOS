from fastapi import FastAPI

from .runtime import lifespan
from .api_servers import router as mcp_router
from .api_agent import router as agent_router
from .api_ui import router as ui_router

app = FastAPI(
    title="MCP Host",
    description="提供 MCP 工具的 HTTP API + DeepSeek Agent + 管理页面",
    version="0.3.1",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.include_router(mcp_router)
app.include_router(agent_router)
app.include_router(ui_router)
