"""生产消费队列端点：投递、查单个、列历史、看队列水位。

外部服务（定时推图的那个系统）只需要两个动作：
1. `POST /api/queue/jobs` 投递，拿到 `202` + `job_id`；
2. `GET /api/queue/jobs/{job_id}` 轮询，`status` 进入终态（succeeded / partially_failed / failed）后取 `results`。

队列满了回 `429`，响应头带 `Retry-After`，响应体 `detail` 就是「队列已超限」的完整说明。

图片的两段式身份（外部服务最容易误解的地方）：
- 投递后原图落在 `data/image_queue/{job_id}.<ext>`，此时**没有 `image_id`**，响应里是 `null`；
- 轮到它处理时才搬进 `data/images/` 并生成 `image_id`，之后的 `GET /jobs/{id}` 就能看到。
所以「投递成功」不等于「图已在图像库」，只等于「已收下并排队」。服务重启不会丢排队图，
会自动重跑；但**结果记录**只在内存，重启后查不到，要结果得在重启前取走。

本文件只做 HTTP 形状转换（表单字符串 → 列表 / JSON），业务判断全在 `services/job_queue.py`。
"""
from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile

from ..deps import get_job_queue
from ..errors import ApiError
from ..protocols.job_queue import JobQueue, JobSpec

router = APIRouter(prefix="/api/queue", tags=["queue"])


@router.post("/jobs", status_code=202)
async def api_submit_job(
    file: Optional[UploadFile] = File(None),
    image_id: Optional[str] = Form(None),
    tasks: Optional[str] = Form(None),
    text: Optional[str] = Form(None),
    lang: Optional[str] = Form(None),
    roi: Optional[str] = Form(None),
    bbox_list: Optional[str] = Form(None),
    auto_proposals: Optional[bool] = Form(None),
    target_region_indexes: Optional[str] = Form(None),
    max_new_tokens: Optional[int] = Form(None),
    temperature: Optional[float] = Form(None),
    top_p: Optional[float] = Form(None),
    client_ref: Optional[str] = Form(None),
    queue: JobQueue = Depends(get_job_queue),
) -> dict[str, Any]:
    """投递一个检测任务，立即返回 `job_id`（不等推理完成）。

    入参（multipart/form-data）：
        file: 图片文件；与 `image_id` 二选一，同时传时以 `file` 为准。
        image_id: 已通过 `POST /api/images` 上传过的图片 id。
        tasks: 任务 id，逗号 / 分号 / 空格分隔，或 JSON 数组字符串（如 `["detection"]`）；
               取值必须是 `/api/meta` 里的 7 个任务之一。
        text / lang / bbox_list / roi / auto_proposals / target_region_indexes /
        max_new_tokens / temperature / top_p: 与 `POST /api/tasks/{task}/run` 同义；
               `bbox_list`、`roi`、`target_region_indexes` 传 JSON 字符串。
        client_ref: 调用方业务主键，原样回显，便于对账。
    返回：`202` + `{ok, job_id, status, position, capacity, tasks, image_source, image_id,
          image, queued_file, client_ref, submitted_at, attempts, recovered, progress}`。
          直接推图（`file`）时 `image_id` 为 `null`，`queued_file` 是它在
          `data/image_queue/` 里的文件名；处理完成后 `image_id` 才有值。
    异常：
        `400` 任务 id 未知 / JSON 字段格式错 / 图片与 image_id 都没给；
        `404` `image_id` 不存在；
        `429` 队列已超限（响应头 `Retry-After` 给出建议重试秒数）；
        `500` 排队图写盘失败（磁盘满 / 无权限）；
        `503` 队列接入被关闭（`queue_enabled=false`）。
    """
    raw = None
    filename = "queue-upload"
    if file is not None:
        raw = await file.read()
        filename = file.filename or filename
        if not raw:
            raise ApiError(400, "上传文件为空。")

    spec: JobSpec = {
        "tasks": _parse_tasks(tasks),
        "image_id": (image_id or "").strip() or None,
        "image_bytes": raw,
        "filename": filename,
        "text": text,
        "lang": lang,
        "roi": _parse_json_list(roi, "roi"),
        "bbox_list": _parse_json_list(bbox_list, "bbox_list"),
        "auto_proposals": True if auto_proposals is None else bool(auto_proposals),
        "target_region_indexes": _parse_json_list(target_region_indexes, "target_region_indexes"),
        "max_new_tokens": max_new_tokens,
        "temperature": temperature,
        "top_p": top_p,
        "client_ref": client_ref,
    }
    snapshot = await queue.submit(spec)
    return {"ok": True, **snapshot}


@router.get("/jobs/{job_id}")
def api_get_job(job_id: str, queue: JobQueue = Depends(get_job_queue)) -> dict[str, Any]:
    """查单个任务的快照与结果。

    入参：路径参数 `job_id`。
    返回：`{ok, job_id, status, position, tasks, image_source, image_id, image, queued_file,
             client_ref, submitted_at, started_at, finished_at, queue_wait_ms, elapsed_ms,
             attempts, recovered, progress, results}`；
          `results` 每项含 `task / ok / answer / result_bbox_list / boxes_source /
          elapsed_ms / warnings / error`。
    异常：`404` 任务不存在或已被内存保留上限淘汰（重启也会清空记录，排队图不受影响）。
    """
    return {"ok": True, **queue.get(job_id)}


@router.get("/jobs")
def api_list_jobs(
    status: Optional[str] = Query(None, description="queued / running / succeeded / partially_failed / failed"),
    limit: int = Query(50, ge=1, le=200),
    queue: JobQueue = Depends(get_job_queue),
) -> dict[str, Any]:
    """按状态倒序列出仍保留在内存里的任务（新 → 旧）。

    返回：`{ok, items: [...], count, queue: {...队列水位...}}`。
    异常：`400` status 取值非法。
    """
    items = queue.list(status=status, limit=limit)
    return {"ok": True, "items": items, "count": len(items), "queue": queue.status()}


@router.get("/status")
def api_queue_status(queue: JobQueue = Depends(get_job_queue)) -> dict[str, Any]:
    """队列水位：外部服务据此决定「继续投 / 退避多久」。

    返回：`{ok, enabled, consumer_running, capacity, queued, processing, current_job,
             retry_after, retained, max_records, submitted_total, recovered_total,
             succeeded_total, failed_total, rejected_total, tasks_run,
             spool: {pending, failed, bytes}}`。
          `spool.pending` 是 `data/image_queue/` 里还没处理的文件数，`spool.failed` 是
          `failed/` 里堆积的失败件数（会持续增长，需按 docs/deployment.md 定期清理）。
    异常：无。
    """
    return {"ok": True, **queue.status()}


# ---------------------------------------------------------------------------
# 表单字段解析：把 multipart 的字符串转成业务层要的结构
# ---------------------------------------------------------------------------
def _parse_tasks(raw: Optional[str]) -> list[str]:
    """解析 `tasks` 字段：JSON 数组、逗号 / 分号 / 空格 / 竖线分隔都接受。

    入参：`raw` 为原始表单值，可为 None。
    返回：任务 id 列表（去空、去重、保序）；空输入返回空列表（由业务层报「不能为空」）。
    异常：以 `[` 开头但 JSON 解析失败时抛 `ApiError(400)`。
    """
    text = (raw or "").strip()
    if not text:
        return []
    if text.startswith("["):
        parsed = _parse_json_list(text, "tasks")
        return [str(item) for item in parsed or []]
    for sep in (";", "|", ","):
        text = text.replace(sep, " ")
    seen: list[str] = []
    for item in text.split():
        if item not in seen:
            seen.append(item)
    return seen


def _parse_json_list(raw: Optional[str], field: str) -> Optional[list[Any]]:
    """解析 JSON 数组字段（`roi` / `bbox_list` / `target_region_indexes`）。

    入参：`raw` 为原始表单值；`field` 只用于错误文案。
    返回：`list` 或 None（空输入）。
    异常：JSON 非法或顶层不是数组时抛 `ApiError(400)`，文案带上字段名与示例。
    """
    text = (raw or "").strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ApiError(400, f"{field} 不是合法 JSON：{exc.msg}（列：{exc.colno}）") from exc
    if not isinstance(parsed, list):
        raise ApiError(400, f"{field} 必须是 JSON 数组，例如 [[10,10],[70,10],[70,70]]。")
    return parsed
