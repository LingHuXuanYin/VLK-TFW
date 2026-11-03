"""生产消费队列实现：外部服务投递 → 落盘排队 → 单消费者串行推理 → 结果回查。

设计取舍（四条都不是随手选的）：

1. **串行，不并行**：整个进程只有一个消费者协程，`runner.run` 内部还有锁。同一时刻只有
   一个任务在推理，不会出现两个任务抢显存；一个 job 里的多个 task_id 也是逐个跑。
   队列的作用是**摊平突发流量**，不是提高吞吐。
2. **先落盘再入队**：推上来的原图写进 `data/image_queue/`，`submit` 返回 202 时文件已经
   在磁盘上。进程被 kill 也不丢图，重启后自动恢复重跑（见 `_recover`）。
3. **处理完才进图像库**：排队中的图**没有 `image_id`**；消费到它时才解析、缩放、写入
   `data/images/` 并分配 `image_id`。成功后删排队件，业务失败移到 `image_queue/failed/`。
4. **容量只算「等待中」**：正在推理的那个不占额度。这样 `queue_max_size=1` 的含义是
   「一次只缓冲一个」，而不是「容量 1 但又能跑 1 个」这种自相矛盾的语义。

两个容易写错的细节：

- **容量判断必须在落盘之前**：否则队列满时已经在磁盘上留了一张没人处理的图。
- **空闲唤醒不能丢事件**：唤醒用「先查队列 → 清标志 → 再查 → 才 await」的顺序；
  `submit` 在「append + set」之间没有 `await`，单线程事件循环下不存在丢失窗口。

中断与失败的区分（重要）：服务关停导致的中断**不算业务失败**，排队件留在原地等下次启动
恢复；只有推理炸了、图坏了、参数错了才移到 `failed/`，避免一台机器重启一次就把整队图
全打进失败目录。
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
from ..protocols.job_spool import JobSpool
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
_IMAGE_SOURCE_UPLOAD = "upload"
_IMAGE_SOURCE_EXISTING = "existing"


def _now_iso() -> str:
    """本地时区时间戳，形如 `2026-11-02T10:30:00+08:00`。"""
    return datetime.now().astimezone().isoformat(timespec="seconds")


class SpoolBackedJobQueue:
    """`JobQueue` 的默认实现：磁盘排队（`JobSpool`）+ 单消费者协程 + 内存结果留存。

    线程模型：`submit` / `get` / `status` 都在事件循环线程上执行，deque 与 dict 无需加锁；
    唯一离开事件循环的是 `runner.run`（`asyncio.to_thread`）。

    状态分布：
        排队中的图与参数   → `data/image_queue/`（进程重启不丢）
        任务记录与结果     → 进程内存（重启清空，`get` 返回 404）
        处理完的图         → `data/images/`（由 `ImageStore` 管）
    """

    def __init__(
        self,
        runner: TaskRunner,
        image_store: ImageStore,
        spool: JobSpool,
        *,
        capacity: int = 32,
        max_records: int = 200,
        retry_after: int = 10,
        enabled: bool = True,
    ) -> None:
        """
        入参：
            runner: 任务执行器（同步阻塞，内部自己保证串行）。
            image_store: 图像库；消费阶段把排队图落进 `data/images/`。
            spool: 排队目录；`submit` 写、消费读、成功删、失败转 `failed/`。
            capacity: 排队上限（只算等待中的任务），最小 1。
            max_records: 内存里保留的任务记录条数上限，超出淘汰最早结束的。
            retry_after: 队列超限时回给外部服务的建议重试秒数（同时写进 `Retry-After` 头）。
            enabled: 关闭后 `submit` 一律 503，`start` 不启动消费者、也不做恢复。
        """
        self._runner = runner
        self._store = image_store
        self._spool = spool
        self._capacity = max(1, int(capacity))
        self._max_records = max(10, int(max_records))
        self._retry_after = max(1, int(retry_after))
        self._enabled = bool(enabled)

        self._pending: deque[str] = deque()  # 等待中的 job_id（队首最先被消费）
        self._records: dict[str, dict[str, Any]] = {}  # job_id -> 快照（对外可见）
        self._specs: dict[str, dict[str, Any]] = {}  # job_id -> 排队元信息（内部用，不对外）
        self._finished: deque[str] = deque()  # 已结束的 job_id，用于淘汰

        self._wakeup = asyncio.Event()
        self._consumer: Optional[asyncio.Task[None]] = None
        self._current: Optional[str] = None

        self._submitted_total = 0
        self._recovered_total = 0
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

        # 先判容量再落盘：队列满了就不该在磁盘上留一张没人处理的图
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

        image_source, image_id, image_meta, filename = self._resolve_image(spec)
        job_id = uuid.uuid4().hex[:12]
        submitted_at = _now_iso()

        # 落盘：原图 + sidecar。返回 202 时文件已经在磁盘上，重启可恢复
        meta: dict[str, Any] = {
            "tasks": list(tasks),
            "params": self._params_from_spec(spec),
            "image_source": image_source,
            "image_id": image_id,
            "filename": filename,
            "client_ref": spec.get("client_ref"),
            "submitted_at": submitted_at,
            "attempts": 0,
        }
        queued_file = self._spool.put(
            job_id, image_bytes=spec.get("image_bytes"), filename=filename, meta=meta
        )

        record: dict[str, Any] = {
            "job_id": job_id,
            "status": STATUS_QUEUED,
            "position": len(self._pending) + 1,
            "tasks": list(tasks),
            "image_source": image_source,
            "image_id": image_id,
            "image": image_meta,
            "queued_file": queued_file,
            "client_ref": spec.get("client_ref"),
            "submitted_at": submitted_at,
            "started_at": None,
            "finished_at": None,
            "queue_wait_ms": None,
            "elapsed_ms": None,
            "attempts": 0,
            "recovered": False,
            "progress": {"done": 0, "total": len(tasks)},
            "results": [],
            "error": None,
            "capacity": self._capacity,
        }
        self._records[job_id] = record
        self._specs[job_id] = meta
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
                f"任务不存在或已被淘汰：{job_id}（服务只保留最近 {self._max_records} 条记录，"
                "重启也会清空；排队中的图仍在 data/image_queue/ 里，重启后自动重跑）。",
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
            "recovered_total": self._recovered_total,
            "succeeded_total": self._succeeded_total,
            "failed_total": self._failed_total,
            "rejected_total": self._rejected_total,
            "tasks_run": self._tasks_run,
            "spool": self._spool.stats(),
        }

    async def start(self) -> None:
        """见 `JobQueue.start`。启动前先把上次没跑完的排队件恢复进来。"""
        if not self._enabled or self._consumer is not None:
            return
        self._recover()
        self._consumer = asyncio.create_task(self._consume(), name="vlx-job-queue")

    async def stop(self) -> None:
        """见 `JobQueue.stop`。中断的任务**不搬** `failed/`，排队件留给下次启动恢复。"""
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
                record["error"] = "服务关闭，任务中断（排队件已保留，下次启动会重新处理）。"
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
        meta = self._specs.get(job_id)
        if record is None or meta is None:
            return

        self._current = job_id
        record["status"] = STATUS_RUNNING
        record["position"] = 1
        record["started_at"] = _now_iso()
        record["queue_wait_ms"] = _since_ms(str(record["submitted_at"]))
        started = time.perf_counter()

        interrupted = False
        try:
            record["attempts"] = int(record.get("attempts") or 0) + 1
            self._spool.update(job_id, {"attempts": record["attempts"]})

            # 排队图在这一步才进图像库：解析 → 缩放 → 写 data/images/ → 拿到 image_id
            try:
                self._materialize(job_id, record, meta)
            except ApiError as exc:
                record["error"] = exc.detail
            else:
                payload = self._payload(meta, record.get("image_id"))
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
            self._settle_spool(job_id, record, interrupted=interrupted)
            self._evict()

    def _materialize(
        self, job_id: str, record: dict[str, Any], meta: dict[str, Any]
    ) -> None:
        """把排队中的图搬进图像库，成功时回填 `image_id`。

        入参：`job_id` 为任务 id；`record` 为对外快照（就地回填）；`meta` 为排队元信息。
        返回：无。
        异常：排队件缺失抛 `ApiError(410)`；图片无法解析抛 `ApiError(400)`。
        边界：
            - `image_source=existing`（复用图像库已有的图）不搬，只校验 `image_id` 存在；
            - 崩溃恢复时若上次已经搬过（`images/` 里已有该 id），跳过重复搬运，避免一张图存两份。
        """
        source = meta.get("image_source")
        if source != _IMAGE_SOURCE_UPLOAD:
            image_id = str(record.get("image_id") or "")
            if not image_id:
                raise ApiError(410, f"排队记录缺少 image_id：{job_id}，请重新投递。")
            return

        previous = str(record.get("image_id") or "")
        if previous and self._store.path(previous).is_file():
            return

        raw = self._spool.read_image(job_id)
        image_meta = self._store.create_from_bytes(raw, str(meta.get("filename") or "queue-upload"))
        record["image_id"] = image_meta["image_id"]
        record["image"] = dict(image_meta)
        self._spool.update(job_id, {"image_id": image_meta["image_id"]})

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

    def _settle_spool(self, job_id: str, record: dict[str, Any], *, interrupted: bool) -> None:
        """按终态处置排队件：成功删除、业务失败移 `failed/`、中断原地保留。

        入参：`interrupted` 为 True 表示服务关停导致的取消，此时**不动磁盘**，
             排队件留给下次 `start()` 恢复重跑。
        """
        if interrupted:
            return
        if record["status"] in (STATUS_SUCCEEDED, STATUS_PARTIAL):
            self._spool.discard(job_id)
            return
        self._spool.fail(job_id, str(record.get("error") or "任务失败。"))

    def _finalize(self, record: dict[str, Any], interrupted: bool = False) -> None:
        """按「全部成功 / 部分成功 / 全部失败 / 关停中断」定终态，并累加计数。"""
        results = record["results"]
        if interrupted:
            record["status"] = STATUS_FAILED
            record["error"] = "服务关闭，任务中断（排队件已保留，下次启动会重新处理）。"
            self._failed_total += 1
            return
        if not results:
            # 材料化阶段就失败了（图坏了、排队件被清理），没有逐任务结果可看
            record["status"] = STATUS_FAILED
            record["error"] = record.get("error") or "没有可执行的任务。"
            self._failed_total += 1
            return
        ok_count = sum(1 for item in results if item["ok"])
        if ok_count == len(results):
            record["status"] = STATUS_SUCCEEDED
            self._succeeded_total += 1
        elif ok_count:
            record["status"] = STATUS_PARTIAL
            record["error"] = f"{len(results) - ok_count}/{len(results)} 个任务失败。"
            self._failed_total += 1
        else:
            record["status"] = STATUS_FAILED
            record["error"] = results[0]["error"] or "任务全部失败。"
            self._failed_total += 1

    def _recover(self) -> int:
        """把 `image_queue/` 里上次没跑完的记录重新排队（按提交时间升序）。

        返回：恢复的条数。
        边界：
            - 任务 id 已不存在（比如任务目录被删）的记录直接移进 `failed/`，不进队列空转；
            - 记录损坏（`tasks` 为空）同样进 `failed/`，不做猜测性修复；
            - 恢复的条数不受 `capacity` 限制——这些是已经被接受、已经回 202 的任务，
              拒掉会让外部服务拿到「已接收但永不出结果」的鬼状态。代价是启动后队列可能
              暂时超水位，`submit` 会一直 429 直到消化到水位以下，这是正确行为。
        """
        restored = 0
        for entry in self._spool.list_entries():
            job_id = str(entry.get("job_id") or "")
            if not job_id or job_id in self._records:
                continue
            tasks = [str(item) for item in (entry.get("tasks") or []) if str(item).strip()]
            if not tasks:
                self._spool.fail(job_id, "排队记录损坏：tasks 为空。")
                continue
            unknown = [task for task in tasks if get_task(task) is None]
            if unknown:
                self._spool.fail(job_id, f"排队记录里的任务 id 已不存在：{', '.join(unknown)}。")
                continue

            record: dict[str, Any] = {
                "job_id": job_id,
                "status": STATUS_QUEUED,
                "position": len(self._pending) + 1,
                "tasks": tasks,
                "image_source": entry.get("image_source") or _IMAGE_SOURCE_UPLOAD,
                "image_id": entry.get("image_id"),
                "image": None,
                "queued_file": entry.get("image_file"),
                "client_ref": entry.get("client_ref"),
                "submitted_at": entry.get("submitted_at") or _now_iso(),
                "started_at": None,
                "finished_at": None,
                "queue_wait_ms": None,
                "elapsed_ms": None,
                "attempts": int(entry.get("attempts") or 0),
                "recovered": True,
                "progress": {"done": 0, "total": len(tasks)},
                "results": [],
                "error": None,
                "capacity": self._capacity,
            }
            self._records[job_id] = record
            self._specs[job_id] = dict(entry)
            self._pending.append(job_id)
            self._recovered_total += 1
            restored += 1
        if restored:
            self._wakeup.set()
        return restored

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

    def _resolve_image(
        self, spec: JobSpec
    ) -> tuple[str, Optional[str], Optional[dict[str, Any]], str]:
        """确定本次任务用哪张图，返回 `(来源, image_id, 元信息, 原始文件名)`。

        边界：优先用推上来的字节（`upload`），此时 `image_id` 为 None，处理阶段才生成；
             其次复用 `image_id`（`existing`），图已经在 `data/images/` 里。
        异常：两者都没给抛 `ApiError(400)`；`image_id` 不存在抛 `ApiError(404)`。
        """
        raw = spec.get("image_bytes")
        filename = spec.get("filename") or "queue-upload"
        if raw:
            return _IMAGE_SOURCE_UPLOAD, None, None, filename

        image_id = str(spec.get("image_id") or "").strip()
        if not image_id:
            raise ApiError(400, "缺少图片：multipart 里必须给 file（直接推图）或 image_id（复用已上传图）。")
        if not self._store.path(image_id).is_file():
            raise ApiError(404, f"图片不存在或已过期：{image_id}")
        return _IMAGE_SOURCE_EXISTING, image_id, None, filename

    @staticmethod
    def _params_from_spec(spec: JobSpec) -> dict[str, Any]:
        """从投递参数里抽出可 JSON 序列化的执行参数（落进 sidecar，重启后原样回放）。"""
        return {
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

    @staticmethod
    def _payload(meta: dict[str, Any], image_id: Optional[str]) -> dict[str, Any]:
        """拼出与 `RunRequest` 同构的 payload（None 原样传，执行器会回落到任务默认值）。"""
        payload = dict(meta.get("params") or {})
        payload["image_id"] = image_id
        return payload

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
