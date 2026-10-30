"""`/api/proposals`：生成或读取 WeDetect 候选框。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ..deps import get_image_store, get_proposal_source
from ..protocols.image_store import ImageStore
from ..protocols.proposal_source import ProposalSource
from ..schemas import ProposalsRequest

router = APIRouter(prefix="/api", tags=["proposals"])


@router.post("/proposals")
def api_proposals(
    req: ProposalsRequest,
    store: ImageStore = Depends(get_image_store),
    proposals: ProposalSource = Depends(get_proposal_source),
) -> dict[str, Any]:
    """取候选框，默认命中磁盘缓存就直接返回。

    入参：`{image_id, force}`，`force=true` 忽略缓存重新推理。
    返回：`{ok, boxes, source, count, elapsed_ms?}`，`source` 为 `cache` / `wedetect`；
         命中缓存时不返回 `elapsed_ms`。
    异常：图片不存在 `404`；权重缺失 `400`；推理失败 `500`。
    """
    image = store.load(req.image_id)
    result = proposals.get(req.image_id, image, force=req.force)
    payload: dict[str, Any] = {
        "ok": True,
        "boxes": result.boxes,
        "source": result.source,
        "count": len(result.boxes),
    }
    if result.elapsed_ms is not None:
        payload["elapsed_ms"] = result.elapsed_ms
    return payload
