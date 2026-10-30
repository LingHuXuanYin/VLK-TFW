# 迭代报告

## 2026-10-30 · 三组分架构重构（features / web / backend）

### 涉及模块

| 模块 | 变更 |
|---|---|
| `app.py` | 770 行单体 → 32 行入口薄壳（`sys.path` 兜底 + 转发 `backend.app.main`） |
| `backend/app/` | 新增 26 个文件、19 个模块：config / schemas / errors / protocols(4) / services(7) / routers(6) / deps / main |
| `frontend/` | 整目录删除，迁到 `web/` 并拆成 9 个文件（含 render 4 个、canvas 1 个） |
| `features/` | 新增 6 个文件：api(2) / task(1) / form(1) / bbox(1) / suite(1) |
| `shared/` | 新增 `contracts.js`：JSDoc 契约 + PALETTE + 存储键 |
| `docs/` | 新增 requirements.md / product-spec.md / iteration-report.md（本次） |
| `README.md` | 第 8 节「目录结构」重写为分层表 + 分层规则；首段补三组分说明 |

### 变更摘要

1. **后端按能力拆分**，依赖单向 `config → schemas/protocols → services → deps → routers → main`：
   - `task_catalog.py`：七任务元数据的唯一数据源（`BBOX_TASK_IDS`/`REGION_TASK_IDS` 改为从数据派生，不再手写集合）
   - `model_runtime.py`：模型状态机（idle/loading/ready/error），是全项目唯一持进程级状态的地方
   - `image_store.py` / `wedetect_source.py` / `task_runner.py` / `suite_runner.py`：各自一个业务能力
   - `errors.py` 的 `ApiError` 让 services 不再 import fastapi；`main.py` 注册异常处理器翻译成 `{"detail": ...}`
   - `deps.py` 作为组装根创建单例，路由用 `Depends` 取，测试可覆盖
2. **前端抽出无框架业务逻辑**：HTTP 客户端注入 `fetch`、端点适配器、任务目录、表单模型、bbox 几何、全量汇总全部进 `features/`，可在 node 里直接跑。
3. **UI 拆层**：`main.js` 只持状态与编排，`render/*` 只画 DOM，`canvas/annotator.js` 只管画布，`storage.js` 只包 localStorage。
4. **零构建保持**：三个目录用 ES module + 相对路径 import，后端把 `web/` `features/` `shared/` 挂成同级静态目录。
5. **接口零变更**：9 个 HTTP 端点的路径、入参、出参字段、错误文案全部保持原样。

### 影响面

- `run.bat` / `debug.bat` / `启动器.exe`：**无需改动**（仍执行 `python app.py`，仍从 `config.ini` 取端口）。
- `launcher.py`：未改动。它只依赖 `app.py` 存在与 `/api/status` 响应字段，两者均未变。
- 模型加载：仍在导入期 `chdir` 到 VLX-Seek、lifespan 启动即异步加载，行为一致。
- 磁盘数据：`data/images/` 布局不变（`.png` / `.json` / `.boxes.json`），旧缓存可继续命中。
- 浏览器端：`localStorage` 键仍为 `taozi-vlx-forms-v1`，用户已存参数不丢。
- `.bat` 文件（GBK+CRLF）：本次未触碰。

### 自测结论

后端（VLX-Seek venv，假 worker，不加载 10B 模型）**47 项断言全过**：

- 图片存储：长边缩放 200×100 → 64×32、原尺寸保留、空文件 400、坏图 400、缺图 404、demo 缺失 404、候选框缓存读写
- 任务执行：detection 首次 `wedetect` / 二次 `wedetect-cache`、候选框只生成一次、vqa 不需要框、区域任务索引回传、四类 warnings 触发、显式传框优先
- 错误分支：未知任务 404、lang 非法 400、缺 image_id 400、图片不存在 404、缺索引 400、索引非整数 400、text 空 400、缺候选框 400、worker `ValueError`→400、worker 异常→500、模型未就绪 409
- 全量：7 任务串行、区域任务默认 `[0]`、overrides 生效、未就绪时逐条记失败
- 路由层：`ApiError` → HTTP 418 透传正确、`/api/meta` 7 任务、`/` 首页、`/assets` `/features` `/shared` 静态可访问且 MIME 正确、`data/` 与 `server.log` 返回 404
- 状态机：idle→loading→ready、`load_seconds`/`loaded_at` 写入、重复 `start_loading` 只加载一次、失败进 error、error 下非 retry 不重启、retry 生效

前端（node 22，ES module）**全部通过**：

- 语法：10 个 JS 文件 `node --check` 全绿
- 导入完整性：所有相对 import 目标在磁盘存在（0 缺失），保证浏览器相对路径可解析
- 越界扫描：`features/` 无 `document`/`window`/`localStorage`/`wx.`/`innerHTML`
- 纯函数行为：任务索引/序号/分组/模板回退、表单脏键丢弃与类型回退、索引解析、请求体（区域任务 text 恒空、空框传 null）、校验文案、命中测试取最小面积、坐标换算、配色回退、粘贴 JSON 四种错误、画布最小宽度与 DPR、全量统计、`ApiError` 文案与状态码
- DOM 一致性：JS 引用的 45 个 id 中，38 个在 index.html 静态存在，7 个为表单动态生成（预期）；无残留 `/assets/app.js`

### 遗留项（明确未做）

1. **未在浏览器里做真人点击回归**：本次通过纯函数断言 + DOM id 交叉检查 + 静态资源可达性验证，未跑真实浏览器交互（本机无 headless 环境）。首次启动建议手动走一遍「上传图 → 生成候选框 → 跑 detection → 跑全量」。
2. **`web/main.js` 仍为 584 行**（其中约四成是注释）：它是编排根，对外导出功能数为 0，未触发「单文件 ≤10 对外功能」阈值；若后续再加面板，应拆 `web/panels/`。
3. **未加自动化测试目录**：本次验证脚本为一次性运行（未入库），避免在零构建项目里引入测试框架依赖；如需长期回归，建议加 `tests/` + pytest 并把上面的断言固化。
4. **`miniprogram/`** 未创建：本次范围只到三组分（features / web / backend），小程序端按需再起。
