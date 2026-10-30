"""FastAPI 组装层：lifespan、异常翻译、静态挂载、路由注册。

本文件不做任何业务计算，只负责把 `routers/` 接起来，把 `web/` `features/` `shared/`
三个目录挂成静态资源。
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import FEATURES_DIR, SHARED_DIR, WEB_DIR
from .deps import get_model_runtime
from .errors import ApiError
from .routers import ALL_ROUTERS


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """服务启动即在后台加载模型；前端轮询 `/api/status` 展示进度。"""
    get_model_runtime().start_loading()
    yield


def create_app() -> FastAPI:
    """构建应用实例。

    返回：配置好异常处理、静态挂载、全部路由的 FastAPI 实例。
    边界：每次调用都会新建实例，但依赖的单例（模型/存储）来自 `deps`，不会重复创建。
    """
    application = FastAPI(
        title="Taozi VLX · VLX-Seek 任务调测台", version="1.0.0", lifespan=lifespan
    )
    _register_error_handler(application)
    _mount_static(application)
    for router in ALL_ROUTERS:
        application.include_router(router)
    _register_index(application)
    return application


def _register_error_handler(application: FastAPI) -> None:
    """把 services 抛的 `ApiError` 翻译成 `{"detail": ...}`，与重构前 HTTPException 一致。"""

    @application.exception_handler(ApiError)
    async def _handle_api_error(_request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


def _mount_static(application: FastAPI) -> None:
    """挂载前端与 ES module 依赖目录。

    只暴露 web / features / shared 三个目录；`data/`、`server.log` 不对外。
    前端使用相对路径 import（`/assets/main.js` → `../features/...`），因此三者必须在同一层级。
    """
    for mount_path, directory in (
        ("/assets", WEB_DIR),
        ("/features", FEATURES_DIR),
        ("/shared", SHARED_DIR),
    ):
        if directory.is_dir():
            application.mount(
                mount_path, StaticFiles(directory=str(directory)), name=mount_path.strip("/")
            )


def _register_index(application: FastAPI) -> None:
    """根路径返回调测台页面。"""

    @application.get("/", include_in_schema=False)
    def index() -> FileResponse:
        page = WEB_DIR / "index.html"
        if not page.is_file():
            raise ApiError(404, "前端页面缺失：web/index.html 不存在。")
        return FileResponse(str(page))


app = create_app()
