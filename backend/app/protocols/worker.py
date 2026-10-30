"""推理能力接口：VLX-Seek worker 的七个任务方法。

`services/task_runner.py` 只依赖本 Protocol，因此可以用假 worker 做单元测试，
不必加载 10B 模型。
"""
from __future__ import annotations

from typing import Any, Optional, Protocol

from PIL import Image


class VisionWorker(Protocol):
    """VLX-Seek worker 的最小能力面。

    所有方法：
        入参：image 为 RGB 图；bbox_list 为候选框 `[[x1,y1,x2,y2], ...]`（原图像素）；
             **gen 透传 max_new_tokens / temperature / top_p。
        返回：至少包含 `answer`、`result_bbox_list`、`prompt_tokens`、`completion_tokens` 四键的 dict，
             不同任务可能另有字段。
        异常：参数不合法抛 `ValueError`（由 task_runner 翻译成 400）。
    """

    def predict(
        self,
        image: Image.Image,
        text: str,
        *,
        bbox_list: Optional[list[list[float]]] = None,
        **gen: Any,
    ) -> dict[str, Any]:
        """通用图文问答：text 原样作为 question，不套模板。"""
        ...

    def detect(
        self, image: Image.Image, bbox_list: list[list[float]], text: str, *, lang: str, **gen: Any
    ) -> dict[str, Any]:
        """多类别检测：给定类别名，挑出属于这些类的候选框并归类。"""
        ...

    def ground(
        self, image: Image.Image, bbox_list: list[list[float]], text: str, *, lang: str, **gen: Any
    ) -> dict[str, Any]:
        """单目标指代定位：永远返回 1 个框，无法区分「找到」与「没找到」。"""
        ...

    def count(
        self, image: Image.Image, bbox_list: list[list[float]], text: str, *, lang: str, **gen: Any
    ) -> dict[str, Any]:
        """计数：数量以 `len(result_bbox_list)` 为准，不要解析自然语言。"""
        ...

    def reasoning_detect(
        self, image: Image.Image, bbox_list: list[list[float]], text: str, *, lang: str, **gen: Any
    ) -> dict[str, Any]:
        """带思考链的检测：输出 `<think>` + `<answer>`，耗时约为普通检测的 10 倍。"""
        ...

    def describe_region(
        self,
        image: Image.Image,
        bbox_list: list[list[float]],
        target_region_indexes: list[int],
        *,
        lang: str,
        **gen: Any,
    ) -> dict[str, Any]:
        """指定区域描述：indexes 必须非空、不越界，否则抛 `ValueError`。"""
        ...

    def read_region_text(
        self,
        image: Image.Image,
        bbox_list: list[list[float]],
        target_region_indexes: list[int],
        *,
        lang: str,
        **gen: Any,
    ) -> dict[str, Any]:
        """区域文字识别：区域内无文字时会把物体名当答案返回，需人工核对。"""
        ...


class WorkerProvider(Protocol):
    """worker 的获取与生命周期。`services/model_runtime.py` 是其实现。"""

    def require(self) -> VisionWorker:
        """取已就绪的 worker。

        异常：加载失败抛 `ApiError(500)`；仍在加载抛 `ApiError(409)`。
        """
        ...

    def start_loading(self, retry: bool = False) -> None:
        """幂等启动异步加载；`retry=True` 允许从 error 状态重试。"""
        ...

    def status(self) -> dict[str, Any]:
        """返回模型状态快照（status / message / error / load_seconds / device ...）。"""
        ...
