"""WeDetect 候选框来源：懒加载权重（434MB），按图缓存到磁盘。

模型实例是进程级单例，缓存在本对象上；候选框缓存在 `ImageStore` 里，
因此同一张图重复请求不会重跑推理。
"""
from __future__ import annotations

import importlib
import sys
import threading
import time
from pathlib import Path
from typing import Any

from PIL import Image

from ..errors import ApiError
from ..protocols.image_store import ImageStore
from ..protocols.proposal_source import ProposalResult
from .device import resolve_device


class WedetectProposalSource:
    """`ProposalSource` 的 WeDetect 实现。"""

    def __init__(
        self,
        checkpoint: Path,
        vlx_root: Path,
        store: ImageStore,
        device_preference: str = "auto",
    ) -> None:
        """
        入参：
            checkpoint: `wedetect_base_uni.pth` 路径。
            vlx_root: VLX-Seek 根目录（`detect_tools/WeDetect` 在其下）。
            store: 候选框磁盘缓存的落点。
            device_preference: auto / cuda:0 / cpu。
        """
        self._checkpoint = Path(checkpoint)
        self._vlx_root = Path(vlx_root)
        self._store = store
        self._device_preference = device_preference
        self._model: Any = None
        self._lock = threading.Lock()

    # -- 对外能力 -----------------------------------------------------------
    def ready(self) -> bool:
        """见 `ProposalSource.ready`。"""
        return self._checkpoint.is_file()

    def get(self, image_id: str, image: Image.Image, force: bool = False) -> ProposalResult:
        """见 `ProposalSource.get`。命中缓存时 `elapsed_ms` 为 None。"""
        if not force:
            cached = self._store.load_proposals(image_id)
            if cached:
                return ProposalResult(boxes=cached, source="cache")

        started = time.perf_counter()
        boxes = self._generate(image)
        self._store.save_proposals(image_id, boxes)
        return ProposalResult(
            boxes=boxes,
            source="wedetect",
            elapsed_ms=round((time.perf_counter() - started) * 1000, 1),
        )

    # -- 内部实现 -----------------------------------------------------------
    def _generate(self, image: Image.Image) -> list[list[float]]:
        """跑一次推理，返回 100 个候选框（原图像素坐标，保留两位小数）。"""
        import torch

        model = self._ensure_model()
        try:
            with torch.inference_mode():
                outputs = model([image])
                boxes = outputs[0]["bboxes"].float().cpu().tolist()
            del outputs
        except Exception as exc:  # noqa: BLE001
            raise ApiError(500, f"候选框生成失败：{type(exc).__name__}: {exc}") from exc
        return [[round(float(v), 2) for v in box] for box in boxes]

    def _ensure_model(self) -> Any:
        """懒加载并缓存模型（双检锁）。"""
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is not None:
                return self._model
            if not self._checkpoint.is_file():
                raise ApiError(
                    400,
                    f"WeDetect 权重不存在：{self._checkpoint}。请手动传入 bbox_list，"
                    "或把 wedetect_base_uni.pth 放到 resources 目录。",
                )
            self._model = self._load_model()
            return self._model

    def _load_model(self) -> Any:
        """构建检测器并把官方权重键名重映射到当前结构。"""
        import torch

        wedetect_dir = self._vlx_root / "detect_tools" / "WeDetect"
        if str(wedetect_dir) not in sys.path:
            sys.path.insert(0, str(wedetect_dir))
        module = importlib.import_module("generate_proposal")
        model = module.SimpleYOLOWorldDetector(
            backbone_size="base", prompt_dim=768, num_prompts=256, num_proposals=100
        )
        state_dict = torch.load(self._checkpoint, map_location="cpu")
        state_dict = state_dict.get("state_dict", state_dict)
        model.load_state_dict(_remap_state_dict(state_dict), strict=False)
        return model.to(resolve_device(self._device_preference)).eval()


def _remap_state_dict(state_dict: dict[str, Any]) -> dict[str, Any]:
    """官方 checkpoint 的键名与 `SimpleYOLOWorldDetector` 不一致，逐条改写。

    backbone：`backbone.image_model.model.` → `backbone.`
    bbox_head：`bbox_head.head_module.` 去掉，且旧版层号（0.2/1.2/2.2、1.bn…）
               要映射到新版（0.6/1.6/2.6、4/3/1/0）。
    """
    for key in list(state_dict.keys()):
        if "backbone" in key:
            state_dict[key.replace("backbone.image_model.model.", "backbone.")] = state_dict.pop(key)
    for key in list(state_dict.keys()):
        if "bbox_head" in key:
            new_key = key.replace("bbox_head.head_module.", "bbox_head.")
            new_key = new_key.replace("0.2.", "0.6.")
            new_key = new_key.replace("1.2.", "1.6.")
            new_key = new_key.replace("2.2.", "2.6.")
            new_key = new_key.replace("1.bn", "4")
            new_key = new_key.replace("1.conv", "3")
            new_key = new_key.replace("0.bn", "1")
            new_key = new_key.replace("0.conv", "0")
            state_dict[new_key] = state_dict.pop(key)
    return state_dict
