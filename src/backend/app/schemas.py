"""数据契约：HTTP 入参的 pydantic 模型 + 跨层传递用的 TypedDict。

改动这里的字段等于改动对外接口，前端 `features/api/vlx-api.js` 需同步。
"""
from __future__ import annotations

from typing import Any, Optional, TypedDict

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------
class RunRequest(BaseModel):
    """单任务运行请求。字段含义见 README「HTTP 接口」一节，均为可选（缺省走任务默认值）。

    `roi` 为电子围栏多边形（原图像素顶点列）。传了它就只在围栏内生成候选框、
    并把围栏外像素灰化后再送模型；不传则与旧行为完全一致。
    """

    image_id: str
    text: Optional[str] = None
    lang: Optional[str] = None
    bbox_list: Optional[list[list[float]]] = None
    roi: Optional[list[list[float]]] = None
    auto_proposals: bool = True
    target_region_indexes: Optional[list[int]] = None
    max_new_tokens: Optional[int] = None
    temperature: Optional[float] = None
    top_p: Optional[float] = None


class ProposalsRequest(BaseModel):
    """候选框请求。`force=True` 忽略磁盘缓存重新跑 WeDetect。

    `roi` 存在时只裁围栏外接矩形推理，并把围栏外的框过滤掉。
    """

    image_id: str
    force: bool = False
    roi: Optional[list[list[float]]] = None


class SuiteRequest(BaseModel):
    """全量调测请求。`overrides` 按 task_id 覆盖单个任务的参数。"""

    image_id: str
    bbox_list: Optional[list[list[float]]] = None
    roi: Optional[list[list[float]]] = None
    auto_proposals: bool = True
    overrides: dict[str, dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# 跨层数据契约
# ---------------------------------------------------------------------------
class ImageMeta(TypedDict):
    """图片落盘后的元信息，同时作为 `/api/images`、`/api/demo` 的响应体主体。"""

    image_id: str
    filename: str
    width: int
    height: int
    original_size: list[int]
    resized: bool


class ModelStatus(TypedDict):
    """模型运行时状态，`/api/status` 的响应体主体。"""

    status: str  # idle | loading | ready | error
    message: str
    error: Optional[str]
    load_seconds: Optional[float]
    loaded_at: Optional[str]
    model_path: str
    device: Optional[str]
