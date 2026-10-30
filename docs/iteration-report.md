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

---

## 2026-10-31 · 源码统一迁入 `src/`

### 涉及模块

| 模块 | 变更 |
|---|---|
| `app.py` → `src/main.py` | 移动 + 文档字符串重写（说明 `BASE_DIR = src/` 与 `from backend...` 的导入约定） |
| `launcher.py` → `src/launcher.py` | 移动 + `BASE_DIR` 改为 `parent.parent` + `APP_FILE` 指向 `src/main.py` |
| `backend/` → `src/backend/` | 移动；`config.py` 拆出 `SRC_ROOT` / `PROJECT_ROOT` 双锚点；`main.py` 文案与注释更新 |
| `features/` `shared/` `web/` | 移动，**内容零改动**（相对 import 自动成立） |
| `_env.bat` | 新增导出 `VLX_ENTRY=%VLX_HOME%src\main.py` |
| `run.bat` / `debug.bat` | `"%PY%" app.py` → `"%PY%" "%VLX_ENTRY%"` |
| `build_launcher.bat` | PyInstaller 入口 `launcher.py` → `src\launcher.py` |
| `README.md` | 首段、1.1 节启动说明、第 8 节目录树与分层规则重写 |
| `docs/requirements.md` | 新增 §6「第 2 轮范围」：迁移映射、7 条验收、4 条风险对策 |
| `docs/product-spec.md` | 代码地图加 `src/` 层级；「改东西去哪找」表全部换新路径；§5 补三种启动方式的实际命令 |

### 变更摘要

1. **物理隔离**：`src/` 收敛全部源码与前端静态资源；项目根只留四个 `.bat`、`config.ini`、`assets/`、`data/`、`docs/`、`README.md`、`requirements.txt`、`启动器.exe`、`server.log`。
2. **路径锚点显式化**：`config.py` 原来用 `parents[2]` 一把算出「项目根」，迁移后会错指向 `src/`；改为
   `SRC_ROOT = parents[2]`（`src/`）、`PROJECT_ROOT = SRC_ROOT.parent`，`WEB_DIR`/`FEATURES_DIR`/`SHARED_DIR`
   挂到 `SRC_ROOT`，`DATA_DIR` 仍挂 `PROJECT_ROOT`。
3. **导入约定不变**：`src/main.py` 把 `src/` 插入 `sys.path`，`backend` 仍作为顶层包导入，
   `src/backend/` 内部一行 import 都不用改。
4. **启动器路径自愈**：源码运行时 `BASE_DIR` 取 `parent.parent` 得到项目根（`config.ini`/`server.log` 在根），
   打包成 exe 后仍取 `sys.executable` 所在目录，两种形态共用一套常量。
5. **bat 用脚本改**：GBK 读 → 断言每条替换命中 1 次 → GBK+CRLF 写回，避免手工编辑破坏编码。

### 影响面

- **部署 / 启动方式已变更**：所有入口从 `python app.py` 改为 `python src/main.py`。`run.bat` / `debug.bat` / `启动器.exe` 对使用者仍是双击即用，但**已打包的 `启动器.exe` 必须重新打包**才能找到新入口（旧 exe 仍会去找根目录的 `app.py`）。
- 对外 HTTP 接口、静态 URL 前缀（`/assets` `/features` `/shared`）、`localStorage` 键、`data/images/` 布局：全部不变。
- 前端 `web/` 下 10 个 JS 文件：**零改动**（`src/web` 与 `src/features`、`src/shared` 同级）。
- bat 文件仍为 GBK + CRLF，端口优先级链未变。

### 自测结论

- 路径锚点：`SRC_ROOT=…\src`、`PROJECT_ROOT=…\Taozi-VLX-deepseek`，`WEB_DIR`/`FEATURES_DIR`/`SHARED_DIR`/`DATA_DIR`/`VLX_SEEK_ROOT` 五个目录 `is_dir()` 全 True。
- 后端（VLX-Seek venv，TestClient，不加载 10B 模型）：`/api/meta` 200、`/api/status` 200、`/` 200 html、`/assets/main.js`、`/assets/canvas/annotator.js`、`/features/api/vlx-api.js`、`/shared/contracts.js` 均 200 且 `application/javascript`，`/assets/style.css` 200 `text/css`。
- 入口 `__main__` 分支：用 `runpy` 干跑（替换 `uvicorn.run` 为空实现），得 `WOULD_RUN app=FastAPI host=127.0.0.1 port=7860`，证明 `python src/main.py` 的 argv/端口/应用构造链路正确。
- bat 编码：四个文件均 GBK 可解码，`纯LF=0`（全 CRLF）；`_env.bat` 展开后 `VLX_ENTRY` 指向真实存在的 `src\main.py`，`PY` 指向存在的 venv 解释器。
- 待人工确认：`启动器.exe` 需重新打包后才有新入口（见遗留项 1）。

### 遗留项（明确未做）

1. **`启动器.exe` 未重新打包**：本机打包依赖 `C:\Python310\python.exe` + PyInstaller，未在本次执行。在重新打包之前，双击 exe 会因找不到根目录 `app.py` 而报「未找到服务入口」。**下一步动作：双击 `build_launcher.bat`**。
2. **未在真实 cmd 里跑一次 `run.bat`**：本机安全策略禁止从工具调用 `cmd.exe`，bat 只做了静态校验（编码、CRLF、替换命中、路径展开存在性），未实测进程拉起。首次使用请手动跑一次 `run.bat`。
3. **未新增 `docs/deployment.md`**：本项目部署面就是「venv + 四个 bat + 启动器」，README 的「快速开始 / 1.1 启动器」两节已覆盖全部步骤与命令，另建文档会与 README 重复；若后续引入服务化部署再补。
4. `assets/` 未迁入 `src/`：它是 PyInstaller 构建资源（图标），不是运行时代码；迁入会让 `--icon` 变成 `src\assets\...` 而收益为零。
