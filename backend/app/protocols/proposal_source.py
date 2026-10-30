"""候选框来源接口：WeDetect 或其他方案（如外部服务、固定网格）都实现本 Protocol。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol

from PIL import Image


@dataclass(frozen=True)
class ProposalResult:
    """一次候选框获取的结果。

    source 取值：
        cache     — 命中磁盘缓存
        wedetect  — 本次新生成
    """

    boxes: list[list[float]]
    source: str
    elapsed_ms: Optional[float] = None


class ProposalSource(Protocol):
    """候选框生产方。"""

    def get(self, image_id: str, image: Image.Image, force: bool = False) -> ProposalResult:
        """取候选框，默认优先用磁盘缓存。

        入参：image_id 用于缓存键；image 为原图（生成时会用到）；force=True 忽略缓存。
        返回：候选框与来源标记，boxes 为 `[[x1,y1,x2,y2], ...]` 原图像素坐标。
        异常：权重缺失抛 `ApiError(400)`；推理失败抛 `ApiError(500)`。
        """
        ...

    def ready(self) -> bool:
        """权重文件是否就位（供 `/api/meta` 告知前端可否点「生成候选框」）。"""
        ...
