"""任务执行能力接口：单任务与全量调测。

路由层只依赖本 Protocol，业务细节（校验、候选框解析、警告生成）全在实现里。
"""
from __future__ import annotations

from typing import Any, Mapping, Protocol


class TaskRunner(Protocol):
    """跑单个 VLX-Seek 任务。"""

    def run(self, task_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        """执行一个任务并返回结果字典。

        入参：
            task_id: 七个任务之一（vqa / detection / grounding_single / counting /
                     reasoning_detection / brief_region_caption / region_ocr）。
            payload: 与 `RunRequest` 同构的 dict（image_id 必填，其余可选）。
        返回：含 `ok`、`answer`、`result_bbox_list`、`elapsed_ms`、`prompt`、`warnings` 等字段的 dict。
        异常：未知任务 `ApiError(404)`；参数问题 `ApiError(400)`；模型未就绪 `ApiError(409)`；
             推理失败 `ApiError(500)`。
        边界：进程内串行执行（同一时刻只跑一个任务），由实现方加锁。
        """
        ...

    @property
    def is_busy(self) -> bool:
        """当前是否有任务在推理中（`/api/status` 的 infer_busy 字段）。"""
        ...


class SuiteRunner(Protocol):
    """串行跑完七个任务。"""

    def run(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """按文档顺序串行执行全部任务。

        入参：与 `SuiteRequest` 同构（image_id 必填，overrides 按 task_id 覆盖参数）。
        返回：`{ok, results: [...], total_elapsed_ms}`；单个任务失败不中断，失败项带 `error` 字段。
        异常：不抛任务级异常（全部在 results 里体现）；模型未就绪时每个任务都记失败。
        """
        ...
