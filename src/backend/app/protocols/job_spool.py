"""排队图片的落盘缓冲接口：未处理的图先落 `image_queue`，处理完再进 `images`。

为什么单独抽一层：队列必须区分两个阶段——
1. **还没轮到它**：图是外部服务推上来的原始文件，住在 `data/image_queue/`，还没有 `image_id`；
2. **轮到它了**：图被解析、缩放、写入 `data/images/` 并分配 `image_id`，此后才是「图库里的图」。

这层只负责第 1 阶段的磁盘读写与搬运（成功删除 / 失败移到 `failed/`），不碰调度顺序、
不碰模型、不碰 HTTP。抽成 Protocol 的收益：换实现（对象存储、共享盘、NFS）不改 `job_queue`，
测试时可以塞一个纯内存假实现。

一致性约定：**先落盘再入队**。`submit` 返回 202 时文件已经写在磁盘上，进程被 kill 也不会丢图；
代价是普通失败（推理炸、图坏了）会在 `failed/` 里留证据，需要运维定期清理（见 `docs/deployment.md`）。
"""
from __future__ import annotations

from typing import Any, Optional, Protocol, TypedDict


class SpoolEntry(TypedDict, total=False):
    """`image_queue/` 里一条排队记录的元信息（sidecar `.json` 的内容）。

    字段含义：
        job_id: 任务 id（`uuid4().hex[:12]`），同时是 sidecar 与原图的文件名主干。
        tasks: 要跑的任务 id 列表。
        params: 与 `RunRequest` 同构的执行参数（`text` / `roi` / `bbox_list` / …）。
        image_source: `upload`（外部推图，原图就在本目录）或 `existing`（复用 `images/` 里已有的图）。
        image_id: 仅 `existing` 时有值；`upload` 时在处理阶段才生成。
        image_file: 原图在本目录下的文件名；`existing` 时为 None。
        filename: 原始文件名（仅用于展示与元信息）。
        client_ref: 外部服务自己的业务主键，原样回显。
        submitted_at: 投递时间（ISO 8601，带时区），恢复时按它排序。
        attempts: 已经被消费过几次（含被中断的），用于观测而非限流。
    """

    job_id: str
    tasks: list[str]
    params: dict[str, Any]
    image_source: str
    image_id: Optional[str]
    image_file: Optional[str]
    filename: str
    client_ref: Optional[str]
    submitted_at: str
    attempts: int


class JobSpool(Protocol):
    """排队图的磁盘缓冲：写入、读取、丢弃、转失败、扫描恢复。"""

    def put(
        self,
        job_id: str,
        *,
        image_bytes: Optional[bytes],
        filename: str,
        meta: dict[str, Any],
    ) -> Optional[str]:
        """把一条排队记录写到磁盘：原图字节（有则写）+ 元信息 sidecar。

        入参：
            job_id: 任务 id，调用方保证唯一且只含 `[0-9a-f]`。
            image_bytes: 外部推上来的原始字节；为 None 时只写 sidecar（复用 `images/` 已有图）。
            filename: 原始文件名，扩展名经白名单过滤后作为原图后缀。
            meta: sidecar 内容，见 `SpoolEntry`（`job_id` / `image_file` 由本方法补全）。
        返回：原图在本目录下的文件名；`image_bytes` 为 None 时返回 None。
        异常：磁盘不可写时抛 `ApiError(500)`，文案说明写入失败（调用方据此返回 500）。
        边界：先写 `.tmp` 再 `os.replace`，避免半截文件被恢复流程读到。
        """
        ...

    def read_image(self, job_id: str) -> bytes:
        """读取排队中的原图字节，供消费阶段解析落库。

        异常：sidecar 或原图缺失时抛 `ApiError(410)`，文案说明排队件已被清理。
        边界：返回的是完整文件字节，不做任何解析或校验。
        """
        ...

    def read(self, job_id: str) -> Optional[dict[str, Any]]:
        """读取 sidecar；不存在或损坏返回 None（不抛异常，供恢复流程容错）。"""
        ...

    def discard(self, job_id: str) -> None:
        """处理完成后清掉排队件（sidecar + 原图）。

        幂等：文件已不存在时静默返回，不抛异常。
        """
        ...

    def update(self, job_id: str, patch: dict[str, Any]) -> None:
        """把 `patch` 合并进 sidecar（用于回填 `image_id` 与 `attempts`）。

        入参：`patch` 为要覆盖的字段，其余字段原样保留。
        返回：无。异常：无——sidecar 不存在或磁盘不可写时静默返回，调用方不因此失败。
        边界：写入是原子的（`.tmp` + `os.replace`），恢复流程不会读到半截 JSON。
        """
        ...

    def fail(self, job_id: str, error: str) -> Optional[str]:
        """把排队件转成失败件：搬到 `failed/` 子目录，并在 sidecar 里追加失败原因。

        入参：`error` 为面向人的失败说明，原样写进 sidecar 的 `error` 字段。
        返回：搬过去后的 sidecar 文件名；原件已不存在时返回 None。
        边界：搬运失败（目标目录不可写）时不抛异常，只返回 None——磁盘问题不该让消费者崩掉。
        """
        ...

    def list_entries(self) -> list[dict[str, Any]]:
        """扫描本目录下全部待处理 sidecar，按 `submitted_at` 升序返回。

        返回：`SpoolEntry` 列表；损坏的 sidecar 被跳过（不出现在结果里）。
        边界：只扫本层 `*.json`，不进 `failed/` 子目录；`*.tmp` 一律忽略。
        """
        ...

    def stats(self) -> dict[str, Any]:
        """磁盘水位：待处理件数、失败件数、占用字节数，供 `/api/queue/status` 展示。

        返回：`{pending: int, failed: int, bytes: int}`；目录不可读时三项均为 0。
        """
        ...
