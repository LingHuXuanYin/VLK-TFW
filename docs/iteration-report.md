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

---

## 2026-10-31 · 电子围栏：只对 ROI 生成候选框与识别

### 涉及模块

| 组 | 文件 | 性质 |
|---|---|---|
| backend | `services/fence.py` | 新增，围栏几何唯一实现 |
| backend | `services/wedetect_source.py`、`services/task_runner.py`、`services/suite_runner.py`、`services/image_store.py` | 改 |
| backend | `protocols/proposal_source.py`、`protocols/image_store.py`、`schemas.py`、`routers/proposals.py` | 改（契约） |
| features | `features/fence/fence-geometry.js` | 新增，前端几何 |
| features | `features/form/form-model.js`、`features/api/vlx-api.js` | 改（请求体与端点参数） |
| web | `web/canvas/fence-editor.js` | 新增，绘制交互 |
| web | `web/canvas/annotator.js`、`web/main.js`、`web/index.html`、`web/style.css`、`web/render/result.js` | 改 |
| shared | `shared/contracts.js` | 改（`Fence` 类型 + 常量） |

### 变更摘要

围栏不是靠提示词约束实现的，而是把两段链路同时收窄：

1. **候选框段**：`wedetect_source._generate` 收到围栏时先裁外接矩形（外扩 8px）再推理，出框后把坐标加回 offset，最后按围栏过滤。围栏内分辨率更高，100 个候选框额度不再被围栏外的大目标吃掉。
2. **识别段**：`task_runner.run` 在派发前把围栏外像素填成中灰 `(128,128,128)`，**尺寸不变**。模型物理上看不见围栏外内容，而坐标体系零变动、不需要任何映射。

兜底来自模型结构：`result_bbox_list` 的坐标直接取自传入的候选框（`caller_boxes[object_index]`），模型只能输出 `<objects>0,2</objects>` 这类索引，报不出围栏外没有编号的框。

配套细节：

- 几何全部收在 `services/fence.py`：多边形归一化（夹边、2px 去重、面积下限）、外接矩形、鞋带面积、Sutherland–Hodgman 求框与围栏的交集面积、点在多边形内、灰化。
- 过滤规则取并集：交集面积 ≥ 框面积 50% **或** 框中心点在围栏内。单看中心点会漏掉「贴边大框」，单看占比会漏掉「框很大但主体在内」。
- 候选框缓存键加围栏指纹（`{id}.boxes.{key}.json`）。这是必须改的：否则「先跑整图、再画围栏」会命中整图那份缓存，表现为围栏完全没生效。整图那份文件名不变，向后兼容。
- 围栏过小（面积 < 整图 0.5% 或任一边 < 64px）时退回整图推理再过滤，避免把一小块噪声放大成模型输入尺寸。
- 显式传入的 `bbox_list` 同样过围栏过滤，保证「只看围栏内」语义一致。
- 前端新增矩形拖拽与多边形拾取两种画法；围栏以青色虚线画在候选框**下面**（半透明填充不糊住框线）；画完后清空旧候选框，避免整图的框与围栏的框混在一起误导。
- 绘制器的事件绑在 canvas 的**捕获阶段**并 `stopPropagation`：否则画围栏时的按下/抬起会被祖先 `dropzone` 的 click 当成候选框点选。

### 影响面

- **默认行为不变**：`roi` 为 `null` 时，候选框生成、缓存文件名、识别图、`boxes_source` 取值全部与旧版一致。新增的 3 个结果字段（`fence_applied` / `fence_vertices` / `fence_cropped`）在旧请求下分别是 `false` / `0` / `false`。
- **HTTP 接口**：3 个请求模型新增可选字段 `roi`，不传即旧行为；`/api/proposals` 的响应多返回 `fence_applied` 与 `cropped`。
- **磁盘**：`data/images/` 新增 `{id}.boxes.{key}.json` 一种文件，仍是可随时删除的缓存。
- **不动的东西**：任务元数据、提示词模板、七个任务的派发方式、`task_catalog.py`、启动链路、`.bat`、`localStorage` 键。

### 自测结论

后端（VLX-Seek venv）：

- 几何 26 项断言全过：夹边归一化、2px 去重、首尾闭合点剔除、面积/逆序面积、`pad=8` 外接矩形、边上与顶点算在内、半外框 `ratio=0.25`、全内 `1.0`、全外 `0.0`、灰化像素与尺寸。
- 行为 23 项断言全过（假模型 + 假 worker）：裁剪框坐标 `(2,2,158,158)`、子图坐标加 offset 后回填正确、同围栏命中缓存、换围栏不复用、三个围栏生成三份缓存文件、围栏内无框时返回空、显式框被过滤、灰化生效且尺寸不变、无围栏时不灰化、`vqa` 也灰化、围栏内无框报 400、非法围栏报 400、围栏内框过少时给警告。
- **真实模型验证**（`demo_image.jpg` 500×399）：整图 100 框，其中只有 48 个落在围栏内；围栏裁剪推理后 80 框且越界 0 个；换一个围栏得到 90 框且与前一围栏结果不同、越界 0 个；二次请求命中缓存；灰化后围栏外为 `(128,128,128)`、围栏内保持原色、尺寸不变。这组数据直接印证了「整图模式下围栏内召回归属被抢」的假设。
- 契约：`/openapi.json` 里三个请求模型均含 `roi`；9 个 `/api/*` 端点齐全；`/api/meta` 仍是 7 任务 3 组；非法 `roi` 类型由 pydantic 拦为 422。
- 静态：`/features/fence/fence-geometry.js` 与 `/assets/canvas/fence-editor.js` 均 200。

前端：

- 17 个 JS 文件语法全绿（node `--check`）。
- 29 条相对 import 零缺失；`features/` 无 `document`/`window`/`localStorage`/`canvas.` 越界。
- 几何纯函数 25 项断言全过（矩形乱序角点、闭合尾点、越界夹取、面积下限、包围盒、顶点吸附、`describeFence`、请求体透传）；凹多边形内外判定另 6 项全过，面积 `9400 = 10000 − 30×20` 与手算一致。
- DOM id：HTML 46 个，JS 引用 50 个，缺的 7 个全是表单与 chips 动态生成（与上一轮结论一致），新增的 5 个围栏 id 全部静态存在。
- 新增模块均被上一级引用（`fence-geometry` ← `fence-editor` ← `main`），无死代码。

浏览器人工回归（2026-11-02，实机跑 `debug.bat` 起的服务，用户确认通过）：

- 画矩形围栏 → 生成候选框，框只出现在围栏内；再跑 `detection`，结果框全部落在围栏内。
- 换多边形围栏 → 候选框重新按新围栏生成，未复用上一份缓存。
- 清除围栏 → 回到整图行为，候选框恢复全图生成。
- 画围栏过程中点画布不触发候选框点选（捕获阶段 `stopPropagation` + `suppressClick` 生效）。

这一轮把上一版遗留的「未做真实浏览器点击回归」闭环。

### 遗留项（明确未做）

1. **围栏不持久化**：换图或刷新即清空。坐标强绑定单张图，存进 `localStorage` 反而容易把旧图围栏套到新图上。
2. **只支持单围栏**：多个围栏同时生效、反向围栏（只检测围栏外）均未做。
3. **围栏不可编辑**：画歪了只能清除重画，没有顶点拖拽。
4. **`num_proposals` 仍是固定 100**：围栏提升的是「围栏内分到多少额度」，不是总额度上限。要放开上限需把它提成配置项（上一轮讨论过的第二个可选项），本轮未做。
