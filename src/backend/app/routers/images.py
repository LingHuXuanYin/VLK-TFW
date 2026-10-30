"""图片相关端点：上传、取图、载入 demo 图。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse

from ..config import VLX_SEEK_ROOT
from ..deps import get_image_store
from ..errors import ApiError
from ..protocols.image_store import ImageStore

router = APIRouter(prefix="/api", tags=["images"])

# VLX-Seek 自带的示例图（相对其根目录）
DEMO_IMAGE = VLX_SEEK_ROOT / "demo" / "demo_image.jpg"


@router.post("/images")
async def api_upload(
    file: UploadFile = File(...), store: ImageStore = Depends(get_image_store)
) -> dict[str, Any]:
    """上传图片：解析 → 长边超限等比缩放 → 落盘为 PNG。

    入参：multipart 字段 `file`。
    返回：`{ok, image_id, filename, width, height, original_size, resized}`。
    异常：空文件 `400`；无法解析 `400`。
    """
    raw = await file.read()
    meta = store.create_from_bytes(raw, file.filename or "upload")
    return {"ok": True, **meta}


@router.get("/images/{image_id}")
def api_image(image_id: str, store: ImageStore = Depends(get_image_store)) -> FileResponse:
    """按 id 返回落盘 PNG。

    异常：不存在 `404`。
    """
    path = store.path(image_id)
    if not path.is_file():
        raise ApiError(404, "图片不存在。")
    return FileResponse(str(path))


@router.get("/demo")
def api_demo(store: ImageStore = Depends(get_image_store)) -> dict[str, Any]:
    """载入 VLX-Seek 自带 `demo/demo_image.jpg`，方便快速开测。

    返回：同 `/api/images`。
    异常：示例图缺失 `404`。
    """
    meta = store.create_from_path(DEMO_IMAGE, "demo/demo_image.jpg")
    return {"ok": True, **meta}
