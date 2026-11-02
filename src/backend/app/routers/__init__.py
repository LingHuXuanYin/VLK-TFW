"""路由注册表：main.py 只需遍历这个元组，新增端点在这里补一项即可。"""
from __future__ import annotations

from fastapi import APIRouter

from .images import router as images_router
from .meta import router as meta_router
from .proposals import router as proposals_router
from .queue import router as queue_router
from .status import router as status_router
from .tasks import router as tasks_router

ALL_ROUTERS: tuple[APIRouter, ...] = (
    meta_router,
    status_router,
    images_router,
    proposals_router,
    tasks_router,
    queue_router,
)
