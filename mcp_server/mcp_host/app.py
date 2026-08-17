import os as _os

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from .runtime import lifespan
from .api_servers import router as mcp_router
from .api_agent import router as agent_router
from .api_ui import router as ui_router

app = FastAPI(
    title="MCP Host",
    description="提供 MCP 工具的 HTTP API + DeepSeek Agent + 管理页面",
    version="0.3.1",
    docs_url=None,  # P0 安全修复: 关闭公开 /docs /redoc
    redoc_url=None,
    lifespan=lifespan,
)

# P0 安全修复: token 鉴权（设置 MCP_API_KEY 后，所有请求需 X-API-Key 或 Bearer）
_MCP_API_KEY = _os.environ.get("MCP_API_KEY", "")


@app.middleware("http")
async def _api_key_auth(request, call_next):
    if _MCP_API_KEY:
        provided = request.headers.get("X-API-Key") or ""
        if not provided:
            auth = request.headers.get("Authorization", "")
            if auth.startswith("Bearer "):
                provided = auth[7:]
        if provided != _MCP_API_KEY:
            return JSONResponse(status_code=401, content={"detail": "unauthorized"})
    return await call_next(request)

app.include_router(mcp_router)
app.include_router(agent_router)
app.include_router(ui_router)
