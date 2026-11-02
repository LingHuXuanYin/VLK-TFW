"""生产消费队列实现：外部服务投递 → 内存排队 → 单消费者串行推理 → 结果回查。

设计取舍（三条都不是随手选的）：

1. **内存队列，不落盘**：本服务的推理是单卡串行（`TaskRunner` 内部有锁），队列只是
   「把突发流量摊平」的缓冲区，不是可靠消息中间件。落盘会引入「服务崩溃后要不要重启
   未完成任务」的语义，而中断的推理结果对调用方本来也无意义。代价是**重启丢排队任务**，
   已在 README 与 docs/deployment 里写明。
2. **容量只算「等待中」**：正在推理的那个不占额度。这样 `queue_max_size=1` 的含义是
   「一次只缓冲一个」，而不是「容量 1 但又能跑 1 个」这种自相矛盾的语义。
3. **消费者跑在事件循环里、推理丢给线程**：`runner.run` 是同步阻塞（GPU 推理），
   必须 `asyncio.to_thread`，否则一次推理就把 `/api/status` 轮询也堵死。

串行策略：整个进程只有一个消费者协程，因此同一时刻只有一个任务在推理，
不会出现两个任务抢显存；一个任务里的多个 task_id 也是逐个跑。
"""
from __future__ import annotations

import asyncio
import time
import uuid
from collections import deque
from contextlib import suppress
from datetime import datetime
from typing import Any, Optional

from ..errors import ApiError
from ..protocols.image_store import ImageStore
from ..protocols.job_queue import JobSpec
from ..protocols.task_runner import TaskRunner
from .task_catalog import ALL_TASKS, get_task

# 队列里允许出现的状态取值（外部服务按这个判断是否要继续轮询）
STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_SUCCEEDED = "succeeded"
STATUS_PARTIAL = "partially_failed"
STATUS_FAILED = "failed"

_TERMINAL_STATUSES = (STATUS_SUCCEEDED, STATUS_PARTIAL, STATUS_FAILED)
_LIST_LIMIT_MAX = 200


def _now_iso() -> str:
    """本地时区时间戳，形如 `2026-11-02T10:30:00+08:00`。"""
    return datetime.now().astimezone().isoformat(timespec="seconds")


class InMemoryJobQueue:
    """`JobQueue` 的进程内实现：deque 排队 + 单个消费者协程。

    线程模型：`submit` / `get` / `status` 都在事件循环线程上执行，deque 与 dict 无需加锁；
    唯一离开事件循环的是 `runner.run`（`asyncio.to_thread`）。
    """

    def __init__(
        self,
        runner: TaskRunner,
        image_store: ImageStore,
        *,
        capacity: int = 32,
        max_records: int = 200,
        retry_after: int = 10,
        enabled: bool = True,
    ) -> None:
        """
        入参：
            runner: 任务执行器（同步阻塞，内部自己保证串行）。
            image_store: 图片落盘与读取；外部服务推图时由本类代存。
            capacity: 排队上限（只算等待中的任务），最小 1。
            max_records: 内存里保留的任务记录条数上限，超出淘汰最早结束的。
            retry_after: 队列超限时回给外部服务的建议重试秒数（同时写进 `Retry-After` 头）。
            enabled: 关闭后 `submit` 一律 503，`start` 不启动消费者。
        """
        self._runner = runner
        self._store = image_store
        self._capacity = max(1, int(capacity))
        self._max_records = max(10, int(max_records))
        self._retry_after = max(1, int(retry_after))
        self._enabled = bool(enabled)

        self._pending: deque[str] = deque()  # 等待中的 job_id（队首最先被消费）
        self._records: dict[str, dict[str, Any]] = {}  # job_id -> 快照（对外可见）
        self._specs: dict[str, JobSpec] = {}  # job_id -> 原始入参（内部用，不对外）
        self._finished: deque[str] = deque()  # 已结束的 job_id，用于淘汰

        self._wakeup = asyncio.Event()
        self._consumer: Optional[asyncio.Task[None]] = None
        self._current: Optional[str] = None

        self._submitted_total = 0
        self._succeeded_total = 0
        self._failed_total = 0
        self._rejected_total = 0
        self._tasks_run = 0

    # -- 对外能力 -----------------------------------------------------------
    async def submit(self, spec: JobSpec) -> dict[str, Any]:
        """见 `JobQueue.submit`。"""
        if not self._enabled:
            raise ApiError(503, "队列接入已关闭：请把 config.ini 的 queue_enabled 改成 true 后重启服务。")
        if self._consumer is None:
            raise ApiError(503, "队列消费者未启动：服务可能正在启动或已停止，请稍后重试。")

        tasks = self._normalize_tasks(spec)

        # 先判容量再落盘：队列满了就不该在磁盘上留一张没人用的图
        if len(self._pending) >= self._capacity:
            self._rejected_total += 1
            raise ApiError(
                429,
                (
                    f"队列已超限：当前排队 {len(self._pending)} 个，上限 {self._capacity} 个。"
                    f"请 {self._retry_after} 秒后再投递，或先查 GET /api/queue/status 看消化进度。"
                ),
                headers={"Retry-After": str(self._retry_after)},
            )

        image_id, image_meta = self._resolve_image(spec)

        job_id = uuid.uuid4().hex[:12]
        position = len(self._pending) + 1
        record: dict[str, Any] = {
            "job_id": job_id,
            "status": STATUS_QUEUED,
            "position": position,
            "tasks": list(tasks),
            "image_id": image_id,
            "image": image_meta,
            "client_ref": spec.get("client_ref"),
            "submitted_at": _now_iso(),
            "started_at": None,
            "finished_at": None,
            "queue_wait_ms": None,
            "elapsed_ms": None,
            "progress": {"done": 0, "total": len(tasks)},
            "results": [],
            "error": None,
            "capacity": self._capacity,
        }
        self._records[job_id] = record
        self._specs[job_id] = dict(spec, tasks=list(tasks), image_id=image_id)  # type: ignore[typeddict-item]
        self._pending.append(job_id)
        self._wakeup.set()
        self._submitted_total += 1
        return self._public(job_id, record)

    def get(self, job_id: str) -> dict[str, Any]:
        """见 `JobQueue.get`。"""
        record = self._records.get(job_id)
        if record is None:
            raise ApiError(
                404,
                f"任务不存在或已被淘汰：{job_id}（内存只保留最近 {self._max_records} 条记录）。",
            )
        return self._public(job_id, record)

    def list(self, status: Optional[str] = None, limit: int = 50) -> list[dict[str, Any]]:
        """见 `JobQueue.list`。"""
        limit = max(1, min(int(limit or 50), _LIST_LIMIT_MAX))
        wanted = (status or "").strip().lower() or None
        if wanted and wanted not in (STATUS_QUEUED, STATUS_RUNNING, *_TERMINAL_STATUSES):
            raise ApiError(
                400,
                f"未知的 status：{status}，可选 queued / running / succeeded / "
                "partially_failed / failed。",
            )
        items: list[dict[str, Any]] = []
        for job_id in reversed(self._records):  # 新的在前
            record = self._records[job_id]
            if wanted and record["status"] != wanted:
                continue
            items.append(self._public(job_id, record))
            if len(items) >= limit:
                break
        return items

    def status(self) -> dict[str, Any]:
        """见 `JobQueue.status`。"""
        return {
            "enabled": self._enabled,
            "consumer_running": self._consumer is not None and not self._consumer.done(),
            "capacity": self._capacity,
            "queued": len(self._pending),
            "processing": 1 if self._current else 0,
            "current_job": self._current,
            "retry_after": self._retry_after,
            "retained": len(self._records),
            "max_records": self._max_records,
            "submitted_total": self._submitted_total,
            "succeeded_total": self._succeeded_total,
            "failed_total": self._failed_total,
            "rejected_total": self._rejected_total,
            "tasks_run": self._tasks_run,
        }

    async def start(self) -> None:
        """见 `JobQueue.start`。"""
        if not self._enabled or self._consumer is not None:
            return
        self._consumer = asyncio.create_task(self._consume(), name="vlx-job-queue")

    async def stop(self) -> None:
        """见 `JobQueue.stop`。"""
        consumer, self._consumer = self._consumer, None
        if consumer is not None:
            consumer.cancel()
            with suppress(asyncio.CancelledError):
                await consumer
        current, self._current = self._current, None
        if current:
            record = self._records.get(current)
            if record is not None and record["status"] == STATUS_RUNNING:
                record["status"] = STATUS_FAILED
                record["error"] = "服务关闭，任务中断。"
                record["finished_at"] = _now_iso()
                self._failed_total += 1

    # -- 内部实现 -----------------------------------------------------------
    async def _consume(self) -> None:
        """消费者主循环：取一个跑一个，永远不放并行。"""
        while True:
            job_id = await self._next_job()
            await self._execute(job_id)

    async def _next_job(self) -> str:
        """等待并取出队首 job_id。

        事件循环是单线程：`submit` 在「append + set」之间没有 await，所以这里的
        「清标志 → 再查一次 → 才 await」不会丢唤醒。
        """
        while True:
            if self._pending:
                return self._pending.popleft()
            self._wakeup.clear()
            if self._pending:
                continue
            await self._wakeup.wait()

    async def _execute(self, job_id: str) -> None:
        """串行跑完一个任务的所有 task_id，逐条记录结果，写回最终状态。"""
        record = self._records.get(job_id)
        spec = self._specs.get(job_id)
        if record is None or spec is None:
            return

        self._current = job_id
        record["status"] = STATUS_RUNNING
        record["position"] = 1
        record["started_at"] = _now_iso()
        record["queue_wait_ms"] = _since_ms(str(record["submitted_at"]))
        payload = self._payload(spec)
        started = time.perf_counter()

        interrupted = False
        try:
            for task_id in record["tasks"]:
                await self._run_one(record, task_id, payload)
        except asyncio.CancelledError:
            # 关停时取消：正在推理的线程收不回来，但状态必须变成终态，
            # 否则外部服务会一直轮询一个永远 running 的任务
            interrupted = True
            raise
        finally:
            record["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 1)
            record["finished_at"] = _now_iso()
            self._finalize(record, interrupted=interrupted)
            self._current = None
            self._finished.append(job_id)
            self._evict()

    async def _run_one(
        self, record: dict[str, Any], task_id: str, payload: dict[str, Any]
    ) -> None:
        """跑单个 task_id：成功写结果，失败写 `error` 但**不中断**后续任务。"""
        started = time.perf_counter()
        try:
            result = await asyncio.to_thread(self._runner.run, task_id, dict(payload))
        except ApiError as exc:
            self._append_failure(record, task_id, exc.detail, exc.status_code, started)
        except Exception as exc:  # noqa: BLE001 - 线程里抛的任何异常都要落成结果，别让消费者挂掉
            self._append_failure(
                record, task_id, f"推理失败：{type(exc).__name__}: {exc}", 500, started
            )
        else:
            record["results"].append(
                {
                    "task": task_id,
                    "task_name": result.get("task_name"),
                    "ok": True,
                    "answer": result.get("answer", ""),
                    "result_bbox_list": result.get("result_bbox_list", []),
                    "boxes_source": result.get("boxes_source"),
                    "boxes_count": result.get("boxes_count"),
                    "prompt_tokens": result.get("prompt_tokens"),
                    "completion_tokens": result.get("completion_tokens"),
                    "elapsed_ms": result.get("elapsed_ms"),
                    "warnings": result.get("warnings", []),
                    "error": None,
                }
            )
        finally:
            record["progress"]["done"] += 1
            self._tasks_run += 1

    def _append_failure(
        self,
        record: dict[str, Any],
        task_id: str,
        detail: str,
        status_code: int,
        started: float,
    ) -> None:
        """记一条失败结果；`status_code` 保留下来便于外部区分「参数错」和「推理炸」。"""
        task = get_task(task_id)
        record["results"].append(
            {
                "task": task_id,
                "task_name": task["name"] if task else task_id,
                "ok": False,
                "answer": "",
                "result_bbox_list": [],
                "boxes_source": None,
                "boxes_count": 0,
                "prompt_tokens": None,
                "completion_tokens": None,
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
                "warnings": [],
                "error": detail,
                "status_code": status_code,
            }
        )

    def _finalize(self, record: dict[str, Any], interrupted: bool = False) -> None:
        """按「全部成功 / 部分成功 / 全部失败 / 关停中断」定终态，并累加计数。"""
        results = record["results"]
        if interrupted:
            record["status"] = STATUS_FAILED
            record["error"] = "服务关闭，任务中断。"
            self._failed_total += 1
            return
        ok_count = sum(1 for item in results if item["ok"])
        if ok_count == len(results) and results:
            record["status"] = STATUS_SUCCEEDED
            self._succeeded_total += 1
        elif ok_count:
            record["status"] = STATUS_PARTIAL
            record["error"] = f"{len(results) - ok_count}/{len(results)} 个任务失败。"
            self._failed_total += 1
        else:
            record["status"] = STATUS_FAILED
            record["error"] = results[0]["error"] if results else "没有可执行的任务。"
            self._failed_total += 1

    def _evict(self) -> None:
        """按结束顺序淘汰老记录，保证内存占用有上限。"""
        while len(self._records) > self._max_records and self._finished:
            old = self._finished.popleft()
            if old == self._current:
                continue
            self._records.pop(old, None)
            self._specs.pop(old, None)

    def _normalize_tasks(self, spec: JobSpec) -> list[str]:
        """校验任务 id 列表：去空、去重、保序，任一未知 id 直接 400。"""
        raw = spec.get("tasks") or []
        tasks: list[str] = []
        for item in raw:
            task_id = str(item).strip()
            if task_id and task_id not in tasks:
                tasks.append(task_id)
        if not tasks:
            raise ApiError(400, "tasks 不能为空：至少要指定一个任务 id。")
        unknown = [t for t in tasks if get_task(t) is None]
        if unknown:
            available = " / ".join(t["id"] for t in ALL_TASKS)
            raise ApiError(400, f"未知任务 id：{', '.join(unknown)}，可选：{available}。")
        return tasks

    def _resolve_image(self, spec: JobSpec) -> tuple[str, Optional[dict[str, Any]]]:
        """确定本次任务用哪张图：优先用推上来的字节，其次复用 `image_id`。"""
        raw = spec.get("image_bytes")
        if raw:
            meta = self._store.create_from_bytes(bytes(raw), spec.get("filename") or "queue-upload")
            return str(meta["image_id"]), dict(meta)
        image_id = str(spec.get("image_id") or "").strip()
        if not image_id:
            raise ApiError(400, "缺少图片：multipart 里必须给 file（直接推图）或 image_id（复用已上传图）。")
        if not self._store.path(image_id).is_file():
            raise ApiError(404, f"图片不存在或已过期：{image_id}")
        return image_id, None

    def _payload(self, spec: JobSpec) -> dict[str, Any]:
        """拼出与 `RunRequest` 同构的 payload（None 原样传，执行器会回落到任务默认值）。"""
        return {
            "image_id": spec.get("image_id"),
            "text": spec.get("text"),
            "lang": spec.get("lang"),
            "bbox_list": spec.get("bbox_list"),
            "roi": spec.get("roi"),
            "auto_proposals": spec.get("auto_proposals", True),
            "target_region_indexes": spec.get("target_region_indexes"),
            "max_new_tokens": spec.get("max_new_tokens"),
            "temperature": spec.get("temperature"),
            "top_p": spec.get("top_p"),
        }

    def _public(self, job_id: str, record: dict[str, Any]) -> dict[str, Any]:
        """对外快照：补上会变的 `position`，丢掉内部字段（`spec` 不落进响应）。"""
        snapshot = {key: value for key, value in record.items() if key != "results"}
        snapshot["job_id"] = job_id
        snapshot["results"] = [dict(item) for item in record["results"]]
        if record["status"] == STATUS_QUEUED:
            try:
                snapshot["position"] = self._pending.index(job_id) + 1
            except ValueError:
                snapshot["position"] = 1
        elif record["status"] == STATUS_RUNNING:
            snapshot["position"] = 1
        else:
            snapshot["position"] = 0
        return snapshot


def _since_ms(iso_text: str) -> Optional[float]:
    """两个 ISO 时间戳之间的毫秒差；解析失败返回 None（不影响主流程）。"""
    try:
        started = datetime.fromisoformat(iso_text)
    except ValueError:
        return None
    return round((datetime.now().astimezone() - started).total_seconds() * 1000, 1)
