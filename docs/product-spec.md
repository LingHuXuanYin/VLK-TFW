# 产品说明 · 调测台怎么用（重构后无变化的部分 + 新增的结构说明）

> 本文件描述「人在页面上怎么用」和「代码放在哪里」。三个组的边界不是文档装饰，改动时按这张表决定文件该进哪个目录。
> 源码统一在 `src/` 下，项目根只放启动脚本、配置、运行时数据与文档。

## 1. 一条最短的调测路径

1. 双击 `启动器.exe`（或 `run.bat`），浏览器打开 `http://127.0.0.1:7860`。
2. 右上角状态从「模型加载中…」变成「模型就绪 · 28.4s」后，按钮才会解除禁用。
3. 左上「示例图」载入 `demo_image.jpg`，或拖一张图进画布。
4. 「生成候选框 (WeDetect)」→ 画布上出现 100 个半透明细框，鼠标悬停显示 `objN`。
5. 只想看画面某一块：点「矩形围栏」拖一块，或「多边形围栏」逐点点击（点首点 / 双击 / 回车闭合，Backspace 撤销，Esc 取消）。画完候选框会清空，重新点「生成候选框」就只在该区域内出框；送模型时围栏外像素灰化。**不画围栏则一切与旧版一致。**
6. 左侧导航选任务，右侧改 `text` / `lang` / `max_new_tokens`，点「运行该任务」。
7. 结果区四个面板：**答案**（标签分色）、**候选框结果**（表格）、**提示词**（模板实际填充后）、**原始 JSON**。
8. 区域任务（`brief_region_caption` / `region_ocr`）先在画布上点选框，索引会自动填进输入框。
9. 「跑完 7 个任务」串行跑全量，表格逐行更新，点任意行回看该任务详情。

参数按任务存在 `localStorage`（键 `taozi-vlx-forms-v1`），刷新不丢。围栏**不持久化**：换图或刷新即清空，避免拿上一张图的坐标套到新图上。

## 2. 代码地图

```
Taozi-VLX-deepseek/
├── src/                          # 全部源码只在这里
│   ├── main.py                   # 服务入口薄壳：只做 sys.path 兜底 + 交给 backend.app.main
│   ├── launcher.py               # 桌面启动器源码（tkinter）
│   ├── backend/app/
│   │   ├── config.py             # 唯一的路径/环境变量来源（含 chdir 到 VLX-Seek）
│   │   ├── schemas.py            # pydantic 请求模型
│   │   ├── protocols/            # ImageStore / ProposalSource / WorkerProvider / VisionWorker
│   │   ├── services/             # task_catalog（元数据）、model_runtime、wedetect_source、
│   │   │                         # image_store、fence（围栏几何）、task_runner、suite_runner
│   │   ├── deps.py               # 组装根：单例在此创建，路由通过 Depends 取
│   │   ├── routers/              # meta / status / images / proposals / tasks
│   │   └── main.py               # FastAPI 组装：lifespan、静态挂载、include_router
│   ├── features/
│   │   ├── api/                  # http-client（注入 fetch）、vlx-api（端点适配）
│   │   ├── task/                 # task-catalog：分组、序号、模板取值
│   │   ├── form/                 # form-model：默认值、请求体构造、索引解析
│   │   ├── bbox/                 # bbox-geometry：命中测试、坐标换算、label 配色
│   │   ├── fence/                # fence-geometry：矩形转多边形、顶点规整、面积、点在多边形内
│   │   └── suite/                # suite-summary：全量结果统计
│   ├── web/
│   │   ├── index.html / style.css
│   │   ├── main.js               # 状态持有 + 事件绑定 + 编排
│   │   ├── storage.js            # localStorage 读写
│   │   ├── canvas/annotator.js   # 画布绘制与点选（候选框 + 围栏）
│   │   ├── canvas/fence-editor.js# 围栏绘制交互（矩形拖拽 / 多边形拾取）
│   │   └── render/               # nav / form / result / suite 四块 DOM 渲染
│   └── shared/contracts.js       # JSDoc 契约 + 常量
├── docs/                         # 本目录
└── data/images/                  # 上传图与候选框缓存（运行时产物，不入库）
```

## 3. 改东西时去哪找

| 想改什么 | 去哪个文件 |
|---|---|
| 某任务的默认 `text` / `max_new_tokens` / 提示词模板 / 提示文案 | `src/backend/app/services/task_catalog.py` |
| 加一个新任务 | 同上加一条 + `task_runner.py` 的派发表 + 前端无需改（元数据驱动） |
| 参数校验规则、错误文案 | `src/backend/app/services/task_runner.py` |
| 模型加载方式、设备选择 | `src/backend/app/services/model_runtime.py` |
| 候选框生成与缓存 | `src/backend/app/services/wedetect_source.py` |
| 围栏裁剪/过滤/灰化的几何实现 | `src/backend/app/services/fence.py` |
| 围栏在画布上的绘制与拾取交互 | `src/web/canvas/fence-editor.js` + `src/web/canvas/annotator.js` |
| 围栏前端校验（顶点、面积、贴合首点） | `src/features/fence/fence-geometry.js` |
| 图片缩放与落盘 | `src/backend/app/services/image_store.py` |
| 新增 HTTP 端点 | `src/backend/app/routers/` 下对应文件 |
| 服务入口 / 启动参数 | `src/main.py` |
| 启动器界面与启停逻辑 | `src/launcher.py`（改完要跑 `build_launcher.bat` 重打包） |
| 画布命中/配色 | `src/features/bbox/bbox-geometry.js` |
| 请求体拼装 | `src/features/form/form-model.js` |
| 画布绘制 | `src/web/canvas/annotator.js` |
| 结果面板长什么样 | `src/web/render/result.js` |

## 4. 边界约定（改动前先读）

- **源码不出 `src/`**：项目根不新建 `api/`、`utils/`、`pages/` 之类的裸源码目录。
- `features/` 里出现 `document`、`window`、`localStorage`、`wx.`，就是越界：说明这段逻辑该搬到 `web/`。
- `features/` 里出现模块级可变变量（缓存、当前用户、上一次结果），立即改为参数传递。
- `web/` 里出现 `fetch(` 直调，越界：走 `features/api/vlx-api.js`。
- `backend/app/routers/` 里出现 `PIL`、`torch`、`json.dump`，越界：说明业务落到了路由层。
- 模型对象、锁、磁盘路径只在 `services/` 与 `deps.py` 出现。
- 拼绝对路径只在 `src/backend/app/config.py` 一处：它导出 `SRC_ROOT`（源码根）与 `PROJECT_ROOT`（项目根），其他文件一律 import 常量。
- **围栏几何有两份实现**：`backend/app/services/fence.py` 与 `features/fence/fence-geometry.js`。前端负责「画得出、拦得住明显错误」，后端负责「算得准、说了算」。改判定口径（顶点容差 2px、点在多边形边界算在内）必须两边同步，否则会出现前端能画、后端 400 的割裂。

## 5. 启动与端口

端口优先级：命令行参数 > 环境变量 `PORT` > `config.ini` 的 `port` > `7860`。`run.bat` / `debug.bat` / `启动器.exe` 共用这条链。

三种方式最终都执行同一个入口 `src/main.py`，cwd 都是项目根（`config.ini`、`server.log`、`data/` 的相对位置因此不变）：

| 方式 | 实际命令 |
|---|---|
| `run.bat` / `debug.bat` | `_env.bat` 解析出 `%VLX_ENTRY%`，再 `"%PY%" "%VLX_ENTRY%"` |
| `启动器.exe` | `[python.exe, <项目根>\src\main.py]`，`cwd=<项目根>` |
| 手动 | `..\VLX-Seek\.venv\Scripts\python.exe src\main.py` |
