"""`/api/meta`：任务元数据与环境信息，前端据此渲染整个界面（零硬编码任务）。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ..config import MAX_IMAGE_SIDE, WEDETECT_PATH
from ..deps import get_model_runtime, get_proposal_source
from ..protocols.proposal_source import ProposalSource
from ..services.model_runtime import ModelRuntime
from ..services.task_catalog import ALL_TASKS, GROUPS

router = APIRouter(prefix="/api", tags=["meta"])


@router.get("/meta")
def api_meta(
    runtime: ModelRuntime = Depends(get_model_runtime),
    proposals: ProposalSource = Depends(get_proposal_source),
) -> dict[str, Any]:
    """返回七任务定义、模型/权重路径、图像长边上限与分组顺序。

    入参：无。
    返回：`{model_path, device, wedetect_path, wedetect_ready, max_image_side, tasks, groups}`。
    异常：无（路径缺失只体现为 `wedetect_ready=false`）。
    """
    return {
        "model_path": runtime.model_path,
        "device": runtime.resolved_device(),
        "wedetect_path": str(WEDETECT_PATH),
        "wedetect_ready": proposals.ready(),
        "max_image_side": MAX_IMAGE_SIDE,
        "tasks": ALL_TASKS,
        "groups": GROUPS,
    }
