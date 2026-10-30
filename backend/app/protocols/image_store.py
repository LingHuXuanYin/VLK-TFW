"""图片存储能力接口：落盘、读取、候选框缓存。

调用方（task_runner / wedetect_source / routers）只依赖本 Protocol，换实现（对象存储、内存盘）
不改调用方。
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Protocol

from PIL import Image

from ..schemas import ImageMeta


class ImageStore(Protocol):
    """图片与候选框的持久化边界。"""

    def create_from_bytes(self, raw: bytes, filename: str) -> ImageMeta:
        """保存上传的原始字节：解析 → 大图等比缩放到长边上限 → 落盘为 PNG。

        入参：raw 为完整文件字节；filename 仅用于展示。
        返回：落盘后的图片元信息。
        异常：空文件抛 `ApiError(400)`；无法解析为图片抛 `ApiError(400)`。
        """
        ...

    def create_from_path(self, source: Path, filename: str) -> ImageMeta:
        """把本地已有图片复制进数据目录（用于载入 demo 图）。

        入参：source 为源文件绝对路径。
        返回：落盘后的图片元信息。
        异常：源文件不存在抛 `ApiError(404)`；无法解析抛 `ApiError(400)`。
        """
        ...

    def load(self, image_id: str) -> Image.Image:
        """按 id 读取图片并转 RGB。

        异常：不存在抛 `ApiError(404)`。
        边界：返回的是新打开的对象，调用方负责不再写回磁盘。
        """
        ...

    def path(self, image_id: str) -> Path:
        """图片落盘路径（不校验存在性，供 FileResponse 使用）。"""
        ...

    def load_proposals(self, image_id: str) -> Optional[list[list[float]]]:
        """读取缓存的候选框；无缓存或缓存损坏返回 None（不抛异常）。"""
        ...

    def save_proposals(self, image_id: str, boxes: list[list[float]]) -> None:
        """写入候选框缓存，覆盖旧文件。"""
        ...
