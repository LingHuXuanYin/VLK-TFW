"""`/api/status` 与 `/api/model/load`：模型状态查询与手动（重）加载。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ..deps import get_model_runtime, get_task_runner
from ..protocols.task_runner import TaskRunner
from ..services.model_runtime import ModelRuntime

router = APIRouter(prefix="/api", tags=["status"])


@router.get("/status")
def api_status(
    runtime: ModelRuntime = Depends(get_model_runtime),
    runner: TaskRunner = Depends(get_task_runner),
) -> dict[str, Any]:
    """返回模型状态快照。

    返回字段：`status`（idle/loading/ready/error）、`message`、`error`、`load_seconds`、
             `loaded_at`、`model_path`、`device`、`infer_busy`（当前是否有任务在推理）。
    异常：无。前端每 2.5s 轮询一次。
    """
    state = runtime.status()
    state["infer_busy"] = runner.is_busy
    return state


@router.post("/model/load")
def api_model_load(runtime: ModelRuntime = Depends(get_model_runtime)) -> dict[str, Any]:
    """触发模型加载；`error` 状态下作为重试入口。

    返回：`{ok, status, message}`，`status` 是触发后的即时状态（通常为 loading）。
    边界：已 ready / loading 时幂等返回，不会重复加载。
    """
    runtime.start_loading(retry=True)
    state = runtime.status()
    return {"ok": True, "status": state["status"], "message": state["message"]}
