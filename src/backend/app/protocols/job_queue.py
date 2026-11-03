"""生产消费队列能力接口：外部服务推图进队列，服务端串行消费。

为什么单独抽一层：队列是**外部系统的边界**，它要同时依赖 `TaskRunner`（跑任务）、
`ImageStore`（处理完落图像库）、`JobSpool`（排队期落磁盘）与进程级的调度状态
（容量、排队顺序、结果保留）。把接口放这里，路由只依赖 Protocol，测试时可以换成假实现。

一致性约定（三条，外部服务必须知道）：
1. **串行**：同一进程只有一个消费者，同一时刻只有一个任务在推理，多个 job 排队而不是并行。
2. **先落盘再入队**：`submit` 返回 202 时原图已写进 `data/image_queue/`。进程重启后这些
   未处理的图会被自动恢复重跑，因此**外部服务不需要为「服务重启」重投**；但**任务结果
   记录**只在内存，重启后 `get` 得到 404，要结果就得在重启前取走。
3. **排队中没有 `image_id`**：`image_id` 是「进了图像库」的身份，在处理阶段才生成。
"""
from __future__ import annotations

from typing import Any, Optional, Protocol, TypedDict


class JobSpec(TypedDict, total=False):
    """投递一个队列任务所需的全部入参（与 `RunRequest` 同构，多了图片与任务列表）。

    字段含义：
        tasks: 要跑的任务 id 列表（1~7 个，取自 `/api/meta` 的 7 个任务），串行执行。
        image_id: 复用图像库里已有的图；与 `image_bytes` 二选一。给了它就不写排队图，
                  排队期只写 sidecar，处理时直接读 `data/images/` 里的那份。
        image_bytes: 图片原始字节；外部服务直接推图时传它，服务端先原样落进
                     `data/image_queue/`（不解析），处理阶段才解析、缩放、搬进 `data/images/`。
        filename: 落盘用的原始文件名（仅用于元信息与后缀白名单，可为空）。
        text / lang / bbox_list / roi / auto_proposals / target_region_indexes /
        max_new_tokens / temperature / top_p: 与 `RunRequest` 完全一致，逐个透传给任务执行器。
        client_ref: 外部服务自己的业务主键（如设备号+时间戳），仅原样回显，便于对账。
    """

    tasks: list[str]
    image_id: Optional[str]
    image_bytes: Optional[bytes]
    filename: str
    text: Optional[str]
    lang: Optional[str]
    bbox_list: Optional[list[list[float]]]
    roi: Optional[list[list[float]]]
    auto_proposals: bool
    target_region_indexes: Optional[list[int]]
    max_new_tokens: Optional[int]
    temperature: Optional[float]
    top_p: Optional[float]
    client_ref: Optional[str]


class JobQueue(Protocol):
    """生产消费队列：`submit` 落盘入队，后台单消费者串行执行，`get` 查结果。"""

    async def submit(self, spec: JobSpec) -> dict[str, Any]:
        """校验并把一个任务放进队列，立即返回，不等推理完成。

        入参：`spec` 见 `JobSpec`。
        返回：任务快照 `{job_id, status: "queued", position, capacity, tasks, image_source,
             image_id, queued_file, client_ref, submitted_at}`。
             其中 `queued_file` 是 `data/image_queue/` 里的原图文件名；`image_source=upload`
             时 `image_id` 为 None（处理完成后才有）。
        异常：
            `ApiError(400)` 缺图片 / 任务为空 / 任务 id 未知；
            `ApiError(404)` `image_id` 指向的图片不存在；
            `ApiError(429)` 排队数已达上限（文案含队列现状，响应头带 `Retry-After`）；
            `ApiError(500)` 排队图写盘失败（磁盘满 / 无权限）；
            `ApiError(503)` 队列接入被关闭，或消费者未启动。
        边界：容量只算「等待中」的任务，正在推理的那个不占额度；写入发生在容量校验之后，
             所以超限请求不会在磁盘上留孤儿图。
        """
        ...

    def get(self, job_id: str) -> dict[str, Any]:
        """按 id 取任务快照（含逐任务结果）。

        入参：`job_id` 为 `submit` 返回的 id。
        返回：`{job_id, status, position, tasks, image_source, image_id, image, queued_file,
             client_ref, submitted_at, started_at, finished_at, queue_wait_ms, elapsed_ms,
             attempts, recovered, progress, results, error}`。
              `status` 取值 queued / running / succeeded / partially_failed / failed。
        异常：`ApiError(404)` id 不存在或记录已被保留上限淘汰（重启也会清空记录）。
        """
        ...

    def list(self, status: Optional[str] = None, limit: int = 50) -> list[dict[str, Any]]:
        """按状态倒序（新→旧）列出任务快照。

        入参：`status` 为 None 时不过滤；`limit` 上限 200。
        返回：任务快照列表（无结果时为空数组，不抛异常）。
        边界：只返回内存中仍保留的记录，被淘汰的历史任务查不到。
        """
        ...

    def status(self) -> dict[str, Any]:
        """队列运行态汇总，供外部服务判断要不要继续投递。

        返回：`{enabled, consumer_running, capacity, queued, processing, current_job,
             retry_after, retained, max_records, submitted_total, recovered_total,
             succeeded_total, failed_total, rejected_total, tasks_run,
             spool: {pending, failed, bytes}}`。
             `spool` 是磁盘排队目录的水位：`pending` 为待处理文件数、`failed` 为失败件数、
             `bytes` 为两者占用字节数（failed/ 会持续增长，需要定期清理）。
        异常：无。
        """
        ...

    async def start(self) -> None:
        """启动后台消费者（服务 lifespan 里调用，幂等）。

        入参：无。返回：无。异常：无（队列关闭时直接返回）。
        边界：启动时会先把 `data/image_queue/` 里上次没跑完的记录恢复进内存队列，
             恢复的条数不受 `capacity` 限制（已接受的任务不能因为重启被丢掉）。
        """
        ...

    async def stop(self) -> None:
        """停止消费者；正在执行的任务记为失败（`服务关闭中断`），但**排队件保留在磁盘上**。

        入参：无。返回：无。异常：无。
        边界：中断不算业务失败，因此不会把图片移进 `failed/`，下次启动会自动重跑。
        """
        ...
