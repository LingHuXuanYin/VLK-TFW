"""全量调测：按文档顺序串行跑完七个任务，单任务失败不中断。

只在 `task_runner` 之上做编排，不重复任何任务细节。
"""
from __future__ import annotations

import time
from typing import Any, Mapping

from ..errors import ApiError
from ..protocols.task_runner import TaskRunner
from .task_catalog import ALL_TASKS


class DefaultSuiteRunner:
    """`SuiteRunner` 的实现。"""

    def __init__(self, runner: TaskRunner, tasks: list[dict[str, Any]] | None = None) -> None:
        """
        入参：
            runner: 单任务执行器。
            tasks: 任务列表，默认取任务目录全量（顺序即执行顺序）。
        """
        self._runner = runner
        self._tasks = tasks if tasks is not None else ALL_TASKS

    def run(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """见 `SuiteRunner.run`。"""
        image_id = payload.get("image_id")
        if not image_id:
            raise ApiError(400, "缺少 image_id。")
        bbox_list = payload.get("bbox_list")
        overrides: Mapping[str, Mapping[str, Any]] = payload.get("overrides") or {}

        results: list[dict[str, Any]] = []
        total_started = time.perf_counter()
        for task in self._tasks:
            task_payload: dict[str, Any] = {
                "image_id": image_id,
                "bbox_list": bbox_list,
                "auto_proposals": payload.get("auto_proposals", True),
            }
            task_payload.update(overrides.get(task["id"], {}))
            if task["needs_index"] and not task_payload.get("target_region_indexes"):
                task_payload["target_region_indexes"] = _default_indexes(bbox_list)

            started = time.perf_counter()
            try:
                results.append(self._runner.run(task["id"], task_payload))
            except ApiError as exc:
                # 单个任务失败不影响后续任务，错误直接回填到结果表
                results.append(
                    {
                        "ok": False,
                        "task": task["id"],
                        "task_name": task["name"],
                        "error": exc.detail,
                        "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
                    }
                )

        return {
            "ok": all(r.get("ok") for r in results),
            "results": results,
            "total_elapsed_ms": round((time.perf_counter() - total_started) * 1000, 1),
        }


def _default_indexes(bbox_list: Any) -> list[int]:
    """区域任务在全量调测时的默认索引：取第 0 个候选框，无候选框返回空列表。

    为什么默认给 100：不传 bbox_list 时后端会自动用 WeDetect 生成 100 个，
    所以索引 0 一定存在。
    """
    count = len(bbox_list) if bbox_list else 100
    return [0] if count else []
