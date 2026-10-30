"""任务端点：单任务运行、全量串行调测。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ..deps import get_suite_runner, get_task_runner
from ..protocols.task_runner import SuiteRunner, TaskRunner
from ..schemas import RunRequest, SuiteRequest

router = APIRouter(prefix="/api", tags=["tasks"])


@router.post("/tasks/{task_id}/run")
def api_run_task(
    task_id: str, req: RunRequest, runner: TaskRunner = Depends(get_task_runner)
) -> dict[str, Any]:
    """跑单个任务。

    入参：路径参数 `task_id`；body 同 `RunRequest`。
    返回：`{ok, task, task_name, answer, result_bbox_list, prompt_tokens, completion_tokens,
          elapsed_ms, prompt, lang, text, max_new_tokens, temperature, top_p,
          boxes_source, boxes_count, target_region_indexes, warnings}`。
    异常：未知任务 `404`；参数问题 `400`；模型未就绪 `409`；推理失败 `500`。
    """
    return runner.run(task_id, req.model_dump())


@router.post("/suite/run")
def api_run_suite(
    req: SuiteRequest, runner: SuiteRunner = Depends(get_suite_runner)
) -> dict[str, Any]:
    """按文档顺序串行跑完七个任务，单任务失败不影响后续。

    返回：`{ok, results, total_elapsed_ms}`；`results` 里失败项形如
         `{ok:false, task, task_name, error, elapsed_ms}`。
    异常：缺 image_id `400`。
    """
    return runner.run(req.model_dump())
