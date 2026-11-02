# 需求说明 · 三组分架构重构

## 1. 背景

`Taozi-VLX-deepseek` 是 VLX-Seek 1.5-10B 七任务接口的本地调测台。重构前的工作形态：

| 文件 | 行数 | 混杂的职责 |
|---|---|---|
| `app.py` | 770 | 任务元数据 + 模型加载与状态 + WeDetect 候选框 + 图片落盘 + 参数校验 + 任务派发 + 全部 HTTP 路由 |
| `frontend/app.js` | 980 | HTTP 调用 + 全局状态 + 画布绘制与命中测试 + 表单渲染 + 结果渲染 + 全量调测编排 |

后果：改一个任务的默认参数要穿过业务逻辑找数据；想给画布命中测试补单测必须先造一个 DOM；`app.py` 里任何一处异常都会让路由、模型、磁盘三件事一起受影响。

## 2. 本次范围

按用户指定的三组分落地：`features/`（业务逻辑，框架无关）、`web/`（Web UI）、`backend/`（Python 后端），另设 `shared/` 放双端共用的类型契约与常量。

| 组 | 职责 | 允许依赖 |
|---|---|---|
| `features/` | HTTP 适配、任务目录、表单模型、候选框几何、全量结果汇总 | 只依赖 `shared/`、注入进来的 `fetch`；禁止 `document`/`window`/`wx.*`/任何 UI 框架 |
| `web/` | 状态持有、DOM 渲染、画布交互、localStorage | `features/`、`shared/`、浏览器 API |
| `backend/` | 路由、协议、服务、运行时状态、磁盘存储 | 允许持有进程级状态（模型、锁） |
| `shared/` | JSDoc 类型契约、调色板/存储键等常量 | 无依赖 |

## 3. 验收标准

1. **接口零变更**：`GET /api/meta`、`GET /api/status`、`POST /api/model/load`、`POST /api/images`、`GET /api/images/{id}`、`GET /api/demo`、`POST /api/proposals`、`POST /api/tasks/{task}/run`、`POST /api/suite/run` 的路径、入参、出参字段与重构前完全一致。
2. **启动契约零变更**：`run.bat`、`debug.bat`、`启动器.exe` 仍以 `python <服务入口>` 拉起，端口优先级（参数 > `PORT` > `config.ini` > 7860）不变。（第 1 轮入口为 `app.py`，第 2 轮迁至 `src/main.py`，见 §6；对外仍是「三个入口、同一条端口链」。）
3. **模型加载行为不变**：导入期 `chdir` 到 VLX-Seek 目录；lifespan 启动即异步加载；`/api/status` 反映 idle/loading/ready/error。
4. **`features/` 无 UI 依赖**：可被 `node` 直接 import 并执行，无需 DOM 环境。
5. **单文件对外功能 ≤ 10**：超出即按子域再拆。
6. **三层对外导出均有功能注释**：写明干什么 / 入参 / 返回 / 异常 / 边界。
7. **页面主路径可用**：上传图 → 生成候选框 → 跑单任务 → 看结果四个面板 → 跑全量，行为与重构前一致。

## 4. 不做的事（明确划出）

- 不引入 TypeScript / Vite / npm 构建链：项目定位是「零构建本地工具」，`features/` 用 ES module + JSDoc 类型注解即可满足类型化接口要求。
- 不改任何七任务语义、默认参数、提示词模板、已知坑文案。
- 不新增小程序端（`miniprogram/` 目录不在本次范围）。
- 不改 `launcher.py` 与 `.bat` 文件（第 1 轮范围如此；第 2 轮因入口迁移不得不改，改动点见 §6，编码仍为 GBK+CRLF）。
- 不引入数据库、不做多用户、不做鉴权。

## 5. 风险与对策

| 风险 | 对策 |
|---|---|
| 路由拆分后 import 循环 | 单向依赖：`config → schemas/protocols → services → deps → routers → main` |
| `chdir` 副作用被多次触发 | 只在 `backend/app/config.py` 导入时执行一次，且幂等 |
| 前端 ES module 加载路径失效 | `features`/`shared` 与 `web` 同为根级挂载点，全部使用相对路径 import |
| 静态资源暴露过度 | 只挂载 `web`、`features`、`shared` 三个目录，`data/`、`server.log` 不对外 |

## 6. 第 2 轮范围：源码统一迁入 `src/`

### 6.1 背景

第 1 轮把代码按三组分拆开了，但 `backend/`、`features/`、`shared/`、`web/` 四个源码目录和
`app.py`、`launcher.py` 仍摊在项目根，与 `启动器.exe`、`config.ini`、`server.log`、`data/` 等
运行时产物、构建物混在同一层。要求：**全部源码收进 `src/`**，项目根只留启动脚本、配置、构建资源、
运行时数据与文档。

### 6.2 迁移映射

| 原位置 | 新位置 |
|---|---|
| `app.py` | `src/main.py` |
| `launcher.py` | `src/launcher.py` |
| `backend/` | `src/backend/` |
| `features/` | `src/features/` |
| `shared/` | `src/shared/` |
| `web/` | `src/web/` |
| `data/`、`assets/`、`config.ini`、`server.log`、`启动器.exe`、四个 `.bat` | **不动**（非源码） |

### 6.3 验收标准

1. **对外零变更**：所有 `/api/*` 路径、请求/响应字段、错误文案不变；静态 URL 前缀仍是 `/assets`、`/features`、`/shared`。
2. **前端零改动**：`src/web` 与 `src/features`、`src/shared` 同级，相对 import 自动成立，`web/` 下不出现任何因迁移产生的路径修改。
3. **三种启动方式全部可用**：`run.bat`、`debug.bat`、`启动器.exe` 均拉起 `src/main.py`，cwd 仍为项目根。
4. **路径锚点唯一**：绝对路径仅在 `src/backend/app/config.py` 拼接，且明确区分 `SRC_ROOT`（源码）与 `PROJECT_ROOT`（运行时产物）。
5. **bat 编码不破**：四个 `.bat` 改后仍为 GBK + CRLF，无裸 LF。
6. **构建链可用**：`build_launcher.bat` 的 PyInstaller 入口指向 `src/launcher.py`，`--icon assets\launcher.ico` 不再依赖源码位置。
7. **`features/` 仍无 UI 依赖**，可直接被 `node` import。

### 6.4 风险与对策

| 风险 | 对策 |
|---|---|
| `config.py` 的 `parents[N]` 层级因迁移错位，静态目录 404 | 引入 `SRC_ROOT`/`PROJECT_ROOT` 双锚点，并以 `is_dir()` 实测校验 |
| `launcher.py` 的 `BASE_DIR` 指向 `src/`，导致 `config.ini`、`server.log` 找不到 | 源码运行时取 `parent.parent`（项目根），打包后仍取 exe 所在目录 |
| bat 改写破坏 GBK 编码 | 脚本化 GBK 读 → 精确替换（断言命中 1 次）→ GBK + CRLF 写回，改后校验可解码且裸 LF 为 0 |
| `assets/` 是否该跟着进 `src/` | 它是 PyInstaller 构建资源而非运行时代码，留在根；`--icon` 路径不变 |

---

## 7. 第 3 轮范围：电子围栏（ROI）

### 7.1 背景

需要「只对画面某一块生成候选框并识别」。只靠后处理过滤框不行，有两个硬伤：

1. **额度被抢**：100 个候选框是整图 NMS 后截断的。围栏只占画面一角时，围栏外的大目标会把额度吃满，围栏内的小目标根本没进候选池。
2. **模型仍看得见**：框少了但图没变。围栏内是橙子、围栏外是苹果时，模型可能输出「苹果」标签却挂到围栏内的框上。

所以必须两段同时收窄，而不是靠提示词约束区域。

### 7.2 做法

| 阶段 | 位置 | 做法 |
|---|---|---|
| 候选框 | `services/wedetect_source.py` | 裁围栏外接矩形（外扩 8px）推理 → 坐标加 offset 回填 → 按围栏过滤 |
| 识别 | `services/task_runner.py` | 围栏外填中灰 `(128,128,128)`，**尺寸不变**，坐标体系零变动 |

几何计算全部收在 `services/fence.py`：多边形归一化、外接矩形、鞋带面积、Sutherland–Hodgman 裁剪求交集、点在多边形内、灰化。

兜底来自模型结构本身：`result_bbox_list` 的坐标直接取自传入的候选框（`caller_boxes[object_index]`），模型只能输出索引，**无法报出围栏外没有编号的框**。

### 7.3 契约变更

| 层 | 变更 |
|---|---|
| `RunRequest` / `ProposalsRequest` / `SuiteRequest` | 新增 `roi: [[x,y],...] \| null`（原图像素，≥3 顶点） |
| `ProposalSource.get` | 新增 `roi` 参数；`ProposalResult` 新增 `cropped` |
| `ImageStore.load_proposals` / `save_proposals` | 新增 `roi_key`；缓存文件名 `{id}.boxes.{key}.json`，整图那份仍为 `{id}.boxes.json` |
| 任务结果 | 新增 `fence_applied` / `fence_vertices` / `fence_cropped` |

### 7.4 验收标准

1. **不传 `roi` 时行为与旧版一致**：缓存文件名、`boxes_source` 取值、结果字段（新增字段除外）均不变。
2. **围栏外框数为 0**：返回的候选框满足「交集占比 ≥ 50%」或「中心点在围栏内」。
3. **缓存互不覆盖**：同一张图画两个围栏 + 一次整图，产生三份缓存文件；换围栏不复用旧结果。
4. **灰化不改坐标**：送模型的图尺寸与围栏内像素不变，围栏外为 `(128,128,128)`。
5. **围栏内无框报 400**，文案指向围栏（提示扩大围栏或关掉围栏）。
6. **非法围栏报 400**：顶点不足 3 个、顶点重合过多、面积过小。
7. **两种画法都可用**：矩形拖拽与多边形逐点拾取都能落成合法多边形。
8. **绘制时不误触**：画围栏期间点击画布不触发候选框点选。

### 7.5 不做的事

- 不做反向围栏（只检测围栏**外**）。
- 不支持多个围栏同时生效。
- 不做围栏形状编辑（画歪了只能清除重画）。
- 围栏不持久化：换图、刷新页面即清空。
- 不改提示词模板：围栏是空间约束，不往 prompt 里塞区域描述。

### 7.6 风险与对策

| 风险 | 对策 |
|---|---|
| 裁剪后坐标错位 | 偏移统一走 `fence.box_to_fence_box`，用假模型断言回填结果 |
| 换围栏命中整图缓存（表现为围栏失效） | 缓存键带围栏指纹，实测三围栏三文件 |
| 围栏过小，裁剪后放大成噪声 | 面积 < 整图 0.5% 或任一边 < 64px 时退回整图推理再过滤 |
| 贴边大框被误丢 | 过滤取「交集占比」与「中心点在内」的并集 |
| 区域任务索引错位 | 前端画布上的框列表就是后端过滤后的那批，`objN` 天然对齐 |
| 边界点判定歧义 | 点在多边形边上、顶点上均算「在内」，前后端同为 2px 容差 |

---

## 8. 第 4 轮范围：生产消费队列（外部服务接入）

### 8.1 背景

本服务外侧还有一个采集服务，会**定期推图**并要求"按某个检测类别处理"。两个矛盾必须解决：

1. **等不起**：同步接口 `POST /api/tasks/{task}/run` 单次 1~45s（`reasoning_detection` 实测 44.5s），采集端按间隔推图，同步等待会把自己的调度器堵死。
2. **扛不住并发**：10B 模型单卡只能串行跑，多个请求同时进来只会互相抢显存、变慢甚至 OOM。

所以需要一层缓冲：投递立即返回、服务端串行消化、队列有明确上限，超限能给采集端一个**可编程识别的回执**（"队列已超限"），而不是让它超时或 500。

### 8.2 做法

| 环节 | 位置 | 做法 |
|---|---|---|
| 接入 | `routers/queue.py` | `POST /api/queue/jobs`（multipart：`file` 或 `image_id` + `tasks`），通过校验后 `202` 返回 `job_id` |
| 容量 | `services/job_queue.py` | 上限只算「等待中」；满了抛 `ApiError(429)`，`detail` 含「队列已超限」，头带 `Retry-After` |
| 消费 | 同上 | 单个消费者协程；推理用 `asyncio.to_thread` 跑，避免阻塞事件循环把 `/api/status` 一起堵死 |
| 结果 | 同上 | 内存记录 + 逐任务结果；终态 `succeeded` / `partially_failed` / `failed` |
| 配置 | `config.py` + `config.ini` | `queue_enabled` / `queue_max_size` / `queue_max_records` / `queue_retry_after`，环境变量 `VLX_QUEUE_*` 优先 |
| 生命周期 | `main.py` lifespan | 启动拉起消费者，关停时取消并把运行中的任务记 `failed`（文案「服务关闭，任务中断。」） |

### 8.3 契约变更

| 层 | 变更 |
|---|---|
| `protocols/job_queue.py` | 新增 `JobQueue`（submit / get / list / status / start / stop）与 `JobSpec` |
| `errors.py` | `ApiError` 新增可选 `headers`，`main.py` 的异常处理器透传给响应（`Retry-After` 靠它） |
| `routers/queue.py` | 新增 4 个端点：投递 / 查单个 / 列表 / 水位 |
| `config.py` | 新增 `CONFIG_FILE`、`read_config_file()`、`_setting*` 与 4 个 `QUEUE_*` 常量 |
| `config.ini` | 新增 4 个 `queue_*` 键（扁平键值，注释说明语义） |
| `launcher.py` | `save_config` 改为「只改 `port`/`host`，其余行原样保留」，否则启动器改端口会抹掉队列配置 |
| `main.py` lifespan | 启动/关停队列消费者 |

### 8.4 验收标准

1. **投递即返回**：`202` + `job_id`，不等推理结束。
2. **超限可识别**：队列满时 `429`，`detail` 含「队列已超限」与当前排队数/上限，响应头有 `Retry-After`。
3. **超限不落盘**：容量判断在图片落盘之前，队列满时不产生孤儿图。
4. **串行消费**：同一时刻最多 1 个任务在推理（断言靠假 runner 统计并发峰值）。
5. **多任务容错**：一个 job 带多个 `task` 时，单任务失败不中断其它；三态判定正确。
6. **错误分流**：未知任务 id / JSON 字段非法 / 缺图片 → `400`；`image_id` 不存在 → `404`；接入关闭 → `503`。
7. **记录有界**：内存记录不超过 `queue_max_records`，超出淘汰最早结束的，查不到时返回 `404` 且文案说明淘汰。
8. **关停不留 running**：服务停止时正在跑的任务必须变成 `failed`，外部服务不会永远轮询。
9. **不影响旧行为**：不传 `roi`、不走队列时，7 个任务的行为与第 3 轮完全一致；传 `roi` 时围栏在队列链路里同样生效。
10. **配置可改**：改 `config.ini` 的 `queue_max_size` 后重启，`/api/queue/status` 的 `capacity` 随之变化；环境变量可覆盖文件值。

### 8.5 不做的事

- **不做持久化队列**：不引入 Redis / Kafka / 磁盘 spool。重启丢失未处理任务，由外部服务自行重投。
- **不做多消费者 / 并发推理**：单卡串行是物理约束，加并发只会互抢显存。
- **不做鉴权、多租户、限流**：定位是本机内部服务（`127.0.0.1`），跨机接入请在反向代理层解决。
- **不做优先级 / 取消 / 自动重试**：队列只负责摊平突发，重试语义归调用方。
- **不做前端队列面板**：调测台 UI 本轮不动，队列只对外部服务暴露 HTTP。

### 8.6 风险与对策

| 风险 | 对策 |
|---|---|
| 推理阻塞事件循环，`/api/status` 卡死 | 推理走 `asyncio.to_thread`；验证里断言排队期间状态接口仍可响应 |
| 队列满时仍落盘，产生没人用的孤儿图 | 容量判断前置到 `create_from_bytes` 之前；断言超限时落盘计数不变 |
| 服务重启后外部服务一直轮询旧 `job_id` | 记录清空即 `404`，文案写明「不存在或已被淘汰」，调用方据此重投 |
| 加 `--workers N` 破坏队列语义（N 个独立队列、容量翻倍） | README 4.2 写明单进程约束，`src/main.py` 本身不带 workers |
| 关停留下永远 `running` 的记录 | 取消时走 `_finalize(interrupted=True)` → `failed` |
| 启动器改端口把 `queue_*` 抹掉 | `save_config` 改为只改 `port`/`host`，其余行原样保留 |
| 空闲唤醒丢事件（消费者睡死） | 唤醒用「先查队列 → 清标志 → 再查 → 才 await」，单线程事件循环下无丢唤醒窗口 |
