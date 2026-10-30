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
