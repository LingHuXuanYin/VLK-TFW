"""图片存储实现：上传图落盘、缩放、候选框缓存。

只做磁盘与图像格式的事，不碰模型、不碰 HTTP。目录与长边上限由构造参数注入。
"""
from __future__ import annotations

import json
import uuid
from io import BytesIO
from pathlib import Path
from typing import Optional

from PIL import Image

from ..errors import ApiError
from ..schemas import ImageMeta


class LocalImageStore:
    """`ImageStore` 的本地磁盘实现。

    目录布局（root 下）：
        {image_id}.png                落盘图（已按长边上限缩放）
        {image_id}.json               元信息
        {image_id}.boxes.json         WeDetect 候选框缓存（整图）
        {image_id}.boxes.{roi}.json   带电子围栏时的候选框缓存（每个围栏一份）
    """

    def __init__(self, root: Path, max_side: int = 1280) -> None:
        """
        入参：root 为数据目录，不存在会自动创建；max_side 为长边上限，<=0 表示不缩放。
        """
        self._root = Path(root)
        self._max_side = int(max_side or 0)
        self._root.mkdir(parents=True, exist_ok=True)

    # -- 对外能力 -----------------------------------------------------------
    def create_from_bytes(self, raw: bytes, filename: str) -> ImageMeta:
        """见 `ImageStore.create_from_bytes`。"""
        if not raw:
            raise ApiError(400, "文件为空。")
        try:
            image = Image.open(BytesIO(raw)).convert("RGB")
        except Exception as exc:  # noqa: BLE001 - PIL 抛的异常类型很杂
            raise ApiError(400, f"无法解析图片：{exc}") from exc
        return self._persist(image, filename)

    def create_from_path(self, source: Path, filename: str) -> ImageMeta:
        """见 `ImageStore.create_from_path`。"""
        source = Path(source)
        if not source.is_file():
            raise ApiError(404, f"未找到 {filename}。")
        try:
            image = Image.open(source).convert("RGB")
        except Exception as exc:  # noqa: BLE001
            raise ApiError(400, f"无法解析图片：{exc}") from exc
        return self._persist(image, filename)

    def load(self, image_id: str) -> Image.Image:
        """见 `ImageStore.load`。"""
        path = self.path(image_id)
        if not path.is_file():
            raise ApiError(404, f"图片不存在或已过期：{image_id}")
        return Image.open(path).convert("RGB")

    def path(self, image_id: str) -> Path:
        """见 `ImageStore.path`。"""
        return self._root / f"{image_id}.png"

    def load_proposals(
        self, image_id: str, roi_key: Optional[str] = None
    ) -> Optional[list[list[float]]]:
        """见 `ImageStore.load_proposals`。"""
        path = self._boxes_path(image_id, roi_key)
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - 缓存损坏当作没有缓存
            return None
        return data if isinstance(data, list) and data else None

    def save_proposals(
        self, image_id: str, boxes: list[list[float]], roi_key: Optional[str] = None
    ) -> None:
        """见 `ImageStore.save_proposals`。"""
        self._boxes_path(image_id, roi_key).write_text(json.dumps(boxes), encoding="utf-8")

    # -- 内部实现 -----------------------------------------------------------
    def _boxes_path(self, image_id: str, roi_key: Optional[str] = None) -> Path:
        """候选框缓存路径。

        带围栏指纹时用独立文件名（`{id}.boxes.{key}.json`），整图那份保持原文件名，
        这样新旧缓存互不覆盖：同一张图画不同围栏各存一份。
        """
        suffix = f".boxes.{roi_key}.json" if roi_key else ".boxes.json"
        return self._root / f"{image_id}{suffix}"

    def _meta_path(self, image_id: str) -> Path:
        return self._root / f"{image_id}.json"

    def _persist(self, image: Image.Image, filename: str) -> ImageMeta:
        """缩放到长边上限并落盘，同时写元信息。坐标后续一律以落盘图为准。"""
        original_size = list(image.size)
        resized = False
        if self._max_side and max(image.size) > self._max_side:
            image.thumbnail((self._max_side, self._max_side), Image.LANCZOS)
            resized = True

        image_id = uuid.uuid4().hex[:12]
        image.save(self.path(image_id), format="PNG")
        meta: ImageMeta = {
            "image_id": image_id,
            "filename": filename,
            "width": image.size[0],
            "height": image.size[1],
            "original_size": original_size,
            "resized": resized,
        }
        self._meta_path(image_id).write_text(
            json.dumps(meta, ensure_ascii=False), encoding="utf-8"
        )
        return meta
