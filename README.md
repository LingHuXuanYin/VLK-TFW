# Taozi VLX 调测台

面向 **VLX-Seek 1.5-10B** 的 Web 调测框架：把《任务接口文档》里的七个任务做成可视化测试界面，逐项调测 `vlx_seek_worker.VLXSeekWorker` 的 L2 任务 API。

- 后端：FastAPI（模型常驻显存，只加载一次）
- 前端：原生 HTML/CSS/JS，ES module 零构建
- 源码统一放 `src/`，按三组物理隔离：`src/features/`（业务逻辑，无 DOM）/ `src/web/`（UI）/ `src/backend/`（Python），`src/shared/` 放类型契约与常量
- 任务划分：开放问答 / 检测与定位 / 区域理解 三组，共 7 个任务
- 图像上直接叠加候选框，点选即可指定区域任务的 `target_region_indexes`

---

## 1. 快速开始

三种启动方式，任选一种（都用 VLX-Seek 的虚拟环境，端口默认 `7860`）：

| 方式 | 适合场景 | 说明 |
|---|---|---|
| **双击 `启动器.exe`** | 日常 | 桌面客户端：改端口、一键启动/停止、看模型状态和日志、就绪后自动开浏览器 |
| `run.bat` | 想在窗口里看实时输出 | 前台运行，Ctrl+C 退出 |
| `debug.bat` | 无人值守 / 要留日志 | 输出重定向到 `server.log`，退出后回显最后 15 行 |

浏览器打开 <http://127.0.0.1:7860>。首次启动后台加载模型（本机 RTX 3090 实测 20~35s），页面右上角会实时显示加载状态，加载完成后「运行该任务」按钮才会解除禁用。

不想自己传图，点「示例图」即可载入 VLX-Seek 自带的 `demo/demo_image.jpg`；也可以直接访问 `http://127.0.0.1:7860/#demo` 一键载入示例图并生成候选框。

依赖（VLX-Seek 的 `.venv` 已经满足，若需单独安装）：

```bat
..\VLX-Seek\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

---

## 1.1 启动器.exe

双击后是一个 tkinter 客户端，不依赖浏览器和命令行：

- **端口**：输入框里改，启动时写入 `config.ini`，`run.bat` / `debug.bat` 读同一份配置，不会各跑各的端口
- **启动服务**：用 `..\VLX-Seek\.venv\Scripts\python.exe src\main.py` 拉起，进程隐藏，日志追加到 `server.log`
- **停止服务**：优先停自己拉起的进程；如果是 `run.bat` 起的，会按端口找到监听进程再 kill
- **状态**：每秒轮询 `/api/status`，显示 `未运行 / 启动中 / loading / ready / 出错`、设备、加载耗时
- **日志**：面板实时显示 `server.log` 末尾，已过滤 tqdm 进度条和自身轮询产生的 `/api/status` 访问记录
- **就绪后自动打开浏览器**（默认勾选，可取消）

端口优先级（三处保持一致）：

```
命令行参数  >  环境变量 PORT  >  config.ini 的 port  >  7860
```

改完 `src/launcher.py` 要重新打包时，双击 `build_launcher.bat`（需要本机 Python 3.10+ 带 tkinter 和 PyInstaller）。

> 注意：`.bat` 文件是 **GBK(ANSI) + CRLF** 编码，用编辑器改完请保持原编码，另存为 UTF-8 会导致 cmd 解析错行、中文提示乱码。

---

## 2. 界面结构

| 区域 | 说明 |
|---|---|
| 左侧任务导航 | 按文档分成 **开放问答 / 检测与定位 / 区域理解** 三组，另有「一键全量调测」。跑过的任务会打绿点 |
| 输入图像 | 拖拽或上传；长边超过 1280 会自动等比缩放（文档建议），坐标以缩放后的落盘图为准 |
| 候选框工具条 | 生成 WeDetect 候选框（100 个，结果按图缓存）、清空、显示/隐藏、手动粘贴 JSON |
| 画布 | 半透明细线为候选框，鼠标悬停高亮并显示 `objN`；**点击=选中/取消**，选中框为蓝色实心标签。多个框重叠时优先命中面积最小的那个 |
| 参数面板 | 每个任务的提示词模板、对应 Python 调用、`text`/`lang`/`max_new_tokens`/`temperature`/`top_p`，以及该任务已知的坑 |
| 调测结果 | 答案（`<ground>/<objects>/<think>/<answer>` 分色高亮）、统计（耗时/tokens/返回框数/候选框来源）、候选框结果表格、模板实际填充后的提示词、原始 JSON |
| 一键全量调测 | 串行跑完 7 个任务，表格逐行显示状态/tokens/耗时/答案摘要，点行可回看单任务详情 |

参数会按任务保存在 `localStorage`，刷新不丢。

---

## 3. 七个任务与接口对应

| # | 分组 | task | 后端调用 | 候选框 | 区域索引 | 默认 lang / max_new_tokens |
|---|---|---|---|---|---|---|
| 1 | 开放问答 | `vqa` | `worker.predict(img, text, bbox_list=None)` | 不需要 | 不需要 | en / 512 |
| 2 | 检测与定位 | `detection` | `worker.detect(img, boxes, text, lang=)` | 需要 | 不需要 | zh / 1024 |
| 3 | 检测与定位 | `grounding_single` | `worker.ground(img, boxes, text, lang=)` | 需要 | 不需要 | zh / 512 |
| 4 | 检测与定位 | `counting` | `worker.count(img, boxes, text, lang=)` | 需要 | 不需要 | zh / 512 |
| 5 | 检测与定位 | `reasoning_detection` | `worker.reasoning_detect(img, boxes, text, lang=)` | 需要 | 不需要 | zh / 2048 |
| 6 | 区域理解 | `brief_region_caption` | `worker.describe_region(img, boxes, indexes, lang=)` | 需要 | **需要** | zh / 512 |
| 7 | 区域理解 | `region_ocr` | `worker.read_region_text(img, boxes, indexes, lang=)` | 需要 | **需要** | zh / 512 |

说明：

- 候选框不传时，后端按文档路线 A 自动用 WeDetect 生成 100 个；生成结果按图片缓存，后续任务直接复用（`boxes_source` 会显示 `request` / `wedetect` / `wedetect-cache`）。
- 区域任务的索引来自画布点选，也支持在输入框里手填 `0, 2`。
- 一键全量调测时区域任务默认取 `[0]`，可在单任务面板里改写后再单独跑。

## 4. HTTP 接口

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/meta` | 任务元数据、模型/权重路径、分组 |
| GET | `/api/status` | 模型状态（idle/loading/ready/error）、device、加载耗时 |
| POST | `/api/model/load` | 触发（或失败后重试）加载 |
| POST | `/api/images` | 上传图片（multipart `file`） |
| GET | `/api/images/{id}` | 取图 |
| GET | `/api/demo` | 载入 VLX-Seek 示例图 |
| POST | `/api/proposals` | 生成/读取 WeDetect 候选框，`{"image_id": "...", "force": false}` |
| POST | `/api/tasks/{task}/run` | 跑单个任务 |
| POST | `/api/suite/run` | 串行跑完 7 个任务 |

单任务请求体：

```json
{
  "image_id": "421608b7bc4a",
  "text": "orange; apple",
  "lang": "zh",
  "bbox_list": null,
  "auto_proposals": true,
  "target_region_indexes": null,
  "max_new_tokens": 1024,
  "temperature": 0.0,
  "top_p": 1.0
}
```

返回体在 worker 原始字段（`answer` / `result_bbox_list` / `prompt_tokens` / `completion_tokens`）之外，补充了 `elapsed_ms`、`prompt`（模板实际填充结果）、`boxes_source`、`warnings`，方便排查。

---

## 5. 本机实测（RTX 3090，demo_image.jpg 500×399，100 个候选框）

| 任务 | prompt→completion | 返回框 | 耗时 | 输出摘录 |
|---|---|---|---|---|
| vqa | 210 → 8 | 0 | 1.3s | `The image contains apples and oranges.` |
| detection | 411 → 19 | 7 | 2.9s | `<ground>orange</ground><objects><obj6><obj3>…` |
| grounding_single | 413 → 10 | 1 | 1.8s | `<ground>最左边的橙子</ground><objects><obj6>…` |
| counting | 420 → 19 | 5 | 2.8s | `<ground> 橙子</ground>…的总数是 5。` |
| reasoning_detection | 486 → 385 | 7 | 44.5s | `<think>好的，用户需要我们检测橙子和苹果…` |
| brief_region_caption | 412 → 9 | 1 | 1.7s | `<ground>一个红色的苹果</ground><objects><obj0>…` |
| region_ocr | 414 → 7 | 1 | 1.4s | `<ground>apple</ground><objects><obj0>…` |

七任务串行总耗时约 56s（reasoning 占了 44s）。detection 返回 5 个橙子 + 2 个苹果，与文档人工核对结果一致。

---

## 6. 已知坑（界面上也会按任务提示）

- **`max_new_tokens` 默认值不一致**：CLI 2048 / `predict()` 512。reasoning_detection 思考链实测 382 token，界面默认给 2048，并会在低于 1024 时给警告。
- **`label` 不可做精确匹配**：措辞与语言都会漂移（`orange`→`橙色`、`橙子`→` 橙子`）。计数请用 `len(result_bbox_list)`。
- **reasoning_detection 的 label 被合并**：多类别会并成一段 `<ground>橙色；苹果</ground>`，要分类结果只能用 `detection`。
- **grounding_single 永远返回 1 个框**：无法区分「找到了」和「没找到」。
- **region_ocr 不会说「无文字」**：区域内没有文字时会把物体名当答案返回。
- **`region_ocr` / `brief_region_caption` 缺索引会 400**：对应文档里的 argparse/ValueError 场景，后端返回中文错误提示。
- **视觉塔用相对路径**：`config.json` 里 `mm_vision_tower: resources/Qwen3.5-9B-Vision_Tower`，所以后端启动时会 `chdir` 到 VLX-Seek 目录，否则会去 HuggingFace 找仓库而卡住（本框架已处理）。

---

## 7. 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `PORT` / `HOST` | `7860` / `127.0.0.1` | 监听地址；`run.bat` / `debug.bat` 会从 `config.ini` 读取后注入 |
| `VLX_SEEK_MODEL_PATH` | `../VLX-Seek/resources/VLX-Seek-1.5-10B` | 模型目录 |
| `VLX_WEDETECT_CHECKPOINT` | `../VLX-Seek/resources/wedetect_base_uni.pth` | WeDetect 权重 |
| `VLX_MAX_IMAGE_SIDE` | `1280` | 上传图长边上限，0 表示不缩放 |
| `VLX_SEEK_DEVICE` | 自动 | 如 `cuda:0` / `cpu` |
| `VLX_DEBUG_STACK` | 空 | 设为秒数可让 faulthandler 定期打印线程栈，用于排查卡死 |

---

## 8. 目录结构与分层

```
Taozi-VLX-deepseek/
├── src/                        # 全部源码只在这里
│   ├── main.py                 # 服务入口薄壳：sys.path 兜底 + 交给 backend.app.main
│   ├── launcher.py             # 启动器源码：端口配置 / 启停服务 / 状态轮询 / 日志面板
│   ├── backend/app/            # Python 后端（分层单向依赖）
│   │   ├── config.py           # 唯一读取环境变量与拼路径的地方（含 chdir 到 VLX-Seek）
│   │   ├── schemas.py          # pydantic 请求模型 + ImageMeta/ModelStatus 契约
│   │   ├── errors.py           # ApiError：services 不依赖 fastapi 的关键
│   │   ├── protocols/          # ImageStore / ProposalSource / VisionWorker+WorkerProvider / TaskRunner
│   │   ├── services/           # task_catalog 元数据、image_store、wedetect_source、
│   │   │                       # model_runtime 状态机、task_runner 派发、suite_runner 编排
│   │   ├── deps.py             # 组装根：单例在此创建，路由用 Depends 取
│   │   ├── routers/            # meta / status / images / proposals / tasks
│   │   └── main.py             # 应用组装：lifespan、异常翻译、静态挂载、路由注册
│   ├── features/               # 业务逻辑：框架无关、无 DOM、无状态
│   │   ├── api/http-client.js  # 注入 fetch 的 HTTP 客户端（含 ApiError）
│   │   ├── api/vlx-api.js      # 端点适配器，UI 层唯一数据出入口
│   │   ├── task/task-catalog.js# 分组 / 序号 / 模板取值
│   │   ├── form/form-model.js  # 默认值 / 持久化合并 / 请求体构造 / 索引解析 / 校验
│   │   ├── bbox/bbox-geometry.js # 坐标映射 / 命中测试 / 配色 / 粘贴 JSON 校验 / 画布尺寸
│   │   └── suite/suite-summary.js# 全量结果统计与答案摘要
│   ├── web/                    # Web UI：持有状态、渲染 DOM、操作画布
│   │   ├── index.html          # 结构与元素 id（41 个）
│   │   ├── style.css
│   │   ├── main.js             # 状态 + 事件绑定 + 编排
│   │   ├── storage.js          # localStorage 读写
│   │   ├── dom.js              # $ / esc
│   │   ├── canvas/annotator.js # 画布绘制与点选
│   │   └── render/             # nav / form / result / suite 四块渲染
│   └── shared/contracts.js     # JSDoc 契约（TaskMeta/TaskResult/...）+ PALETTE/存储键
├── 启动器.exe                  # 桌面启动器（双击用；改完 src/launcher.py 用 build_launcher.bat 重打包）
├── build_launcher.bat          # 重新打包启动器（PyInstaller 入口 src/launcher.py）
├── _env.bat                    # run.bat / debug.bat 共用的环境变量与端口解析（导出 VLX_ENTRY）
├── run.bat                     # 前台启动（日志打在窗口里）
├── debug.bat                   # 后台启动（日志落 server.log，超 20MB 自动归档）
├── config.ini                  # 端口/监听地址，启动器与两个 bat 共用
├── server.log                  # 服务日志（由 debug.bat / 启动器写入，运行时可安全忽略）
├── assets/launcher.ico         # 构建资源：启动器图标（PyInstaller --icon 用）
├── requirements.txt
├── docs/                       # requirements.md / product-spec.md / iteration-report.md
└── data/images/                # 运行时数据：上传图 + 候选框缓存（可随时删除）
```

**为什么这么分**：`src/` 内全部是「可执行 / 可加载」的源码与前端资源；项目根只留启动脚本、配置、
构建资源、运行时数据和文档。运行时产物（`config.ini`、`server.log`、`data/`、`启动器.exe`）留在根目录，
不混进源码树。

分层规则（靠目录守，不靠自觉）：

| 规则 | 说明 |
|---|---|
| 源码不出 `src/` | 项目根不新建 `api/`、`utils/` 之类的裸源码目录；`main.py` / `launcher.py` 已在 `src/` |
| `features/` 无 UI | 出现 `document`/`window`/`localStorage`/`wx.` 即越界 |
| `features/` 无状态 | 不存缓存、不存当前用户、不存上一次结果 |
| `web/` 不直连网络 | 一律走 `features/api/vlx-api.js`，不出现裸 `fetch` |
| `backend` 路由不写业务 | `routers/` 里不出现 PIL / torch / 磁盘写入 |
| 单文件对外功能 ≤ 10 | 超出按子域再拆 |

三个静态挂载点：`/assets` → `src/web/`，`/features` → `src/features/`，`/shared` → `src/shared/`。
URL 前缀与重构前一致，前端无需改 import；前端用相对路径 import（`/assets/main.js` → `../features/...`），
所以三者必须同级挂载；`data/`、`server.log` 不对外。

路径锚点（`src/backend/app/config.py`，全项目只此一处拼绝对路径）：

| 常量 | 值 | 用途 |
|---|---|---|
| `SRC_ROOT` | `src/` | 源码根：`WEB_DIR` / `FEATURES_DIR` / `SHARED_DIR` 都基于它 |
| `PROJECT_ROOT` | 项目根 | 运行时产物：`data/images`、`config.ini`、`server.log` |

启动入口对应关系：`run.bat` / `debug.bat` 调用 `%PY% "%VLX_ENTRY%"`（= `src\main.py`），
`启动器.exe` 直接以 `src/main.py` 为参数拉起；三者 cwd 都是项目根。
