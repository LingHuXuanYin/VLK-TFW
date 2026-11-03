# 部署手册 · Taozi-VLX-deepseek

本文是部署与运维的**全量细节**。给现场执行的简版步骤在项目根 `README.md` 的第 9 章，
两处口径必须一致；冲突时以本文为准并回头修 README。

---

## 1. 服务形态与硬约束

| 项 | 事实 | 带来的限制 |
|---|---|---|
| 形态 | 单进程 uvicorn，监听 `127.0.0.1:7860` | 不是集群服务，没有副本概念 |
| 模型 | VLX-Seek-1.5-10B + WeDetect（合计常驻显存 ~22.6GB / 24.5GB） | **一台机器只能跑一个实例**，另起一个必 OOM |
| 推理 | 串行（进程内单消费者 + 执行器锁） | 吞吐上限 = 1 / 单任务耗时；加并发只会互抢显存 |
| 队列 | 排队图落 `data/image_queue/`，结果记录在内存 | 重启不丢图（自动重跑），但**丢结果记录** |
| 平台 | Windows + cmd 脚本 | `run.bat` / `debug.bat` / `启动器.exe` 都是 cmd 体系，Linux 需自行改写启动脚本 |

**不能做的事**：

- `uvicorn --workers N`：会出现 N 个互相看不见的队列，容量翻倍、`job_id` 查不到、显存 OOM。
- 两台机器共用一个 `data/` 目录（网络盘）：`image_queue/` 的原子写依赖 `os.replace` 的同盘语义，
  跨机共享会读到半截文件。要横向扩容得先换掉这层的实现（`JobSpool` 是 Protocol，可以换，
  但需要配套的分布式锁与队列）。
- 把 `host` 改成 `0.0.0.0` 后直接暴露到公网：服务**没有鉴权、没有限流**。

---

## 2. 环境矩阵

| 组件 | 版本 / 位置 | 说明 |
|---|---|---|
| 操作系统 | Windows 10 / 11 x64 | 脚本依赖 `%SystemRoot%\System32\netstat.exe`、`findstr.exe` |
| Python | `../VLX-Seek/.venv/Scripts/python.exe`（3.10） | `_env.bat` 里 `PY` 写死这条路径，**不另建 venv** |
| Python 依赖 | `requirements.txt`（fastapi / uvicorn / pydantic / pillow / python-multipart） | 模型依赖由 VLX-Seek 侧管理 |
| GPU | NVIDIA，显存 ≥ 20GB | 实测 RTX 3090 加载后 22.6 / 24.5GB |
| 模型权重 | `../VLX-Seek/resources/VLX-Seek-1.5-10B`（约 20GB） | 可用 `VLX_SEEK_MODEL_PATH` 覆盖 |
| WeDetect 权重 | `../VLX-Seek/resources/wedetect_base_uni.pth`（434MB） | 可用 `VLX_WEDETECT_CHECKPOINT` 覆盖 |
| 目录布局 | `VLX-program/{VLX-Seek, Taozi-VLX-deepseek}` 同级 | 路径全部相对这个层级解析 |

---

## 3. 运行时目录

```
Taozi-VLX-deepseek/
├── config.ini                     # 端口 / host / queue_*
├── server.log                     # debug.bat 与启动器写入；超 20MB 自动归档
└── data/
    ├── images/                    # 处理完的图 + 候选框缓存
    │   ├── {image_id}.png
    │   ├── {image_id}.json        # 元信息
    │   ├── {image_id}.boxes.json  # 整图候选框缓存
    │   └── {image_id}.boxes.{roi}.json  # 带围栏的候选框缓存（每个围栏一份）
    └── image_queue/               # 排队缓冲区
        ├── {job_id}.json          # 排队记录（tasks / params / client_ref / attempts）
        ├── {job_id}.png           # 推上来的原图（未解析、未缩放）
        └── failed/                # 业务失败件（会持续增长，需巡检）
            ├── {job_id}.json      # 多出 error 与 failed_at
            └── {job_id}.png
```

### 3.1 三个目录的保留语义不同（最容易误删的地方）

| 目录 | 删掉的后果 | 建议 |
|---|---|---|
| `data/images/` | 历史图看不了，候选框缓存重建 | 想清就清，无副作用 |
| `data/image_queue/`（不含 `failed/`） | **等于丢任务**：已回 202 的图没了，外部服务等不到结果 | 只允许在服务停止后按 `failed/` 记录确认过再动 |
| `data/image_queue/failed/` | 丢掉失败证据，无法复盘 | 可以清，但先读 sidecar 的 `error` |

`data/` 整体已在 `.gitignore` 中，不入库。

### 3.2 生命周期（一条推图任务的全过程）

1. `POST /api/queue/jobs` → 容量校验 → 原图写 `image_queue/{job_id}.<ext>` + sidecar →
   `202`（`image_id` 为 `null`）。
2. 消费者取到它 → 读原图 → 解析/缩放 → 写 `data/images/{image_id}.png` → **回填 `image_id`
   到 sidecar** → 跑任务。
3. 终态处置：
   - `succeeded` / `partially_failed` → 删 `image_queue` 里的两个文件；
   - `failed`（推理炸 / 图坏了 / 参数错）→ 搬到 `failed/`，sidecar 追加 `error`、`failed_at`；
   - **服务关停中断** → 原地不动，下次启动自动重跑（中断不算业务失败）。

### 3.3 重启恢复的行为

服务启动时扫描 `image_queue/*.json`，按 `submitted_at` 升序重新入队：

- **不受 `queue_max_size` 限制**：已经回过 202 的任务不能因重启被丢，代价是启动后可能短暂
  超水位，此时新投递会一直 `429` 直到消化下来（这是正确行为，不是 bug）。
- 任务 id 已不存在（任务目录被改）或 sidecar 损坏（`tasks` 为空）→ 直接进 `failed/`，不进队列空转。
- 恢复进来的记录在 `GET /jobs/{id}` 里 `recovered: true`、`attempts` 大于 0。
- **结果记录仍是内存态**：重启前已完成的 job 查不到了（`404` 文案会说明），要留痕请外部服务存库。

---

## 4. 配置项全量

来源优先级：**环境变量 > `config.ini` > 代码默认值**。改完必须重启服务。

| `config.ini` 键 | 环境变量 | 默认 | 取值范围 | 说明 |
|---|---|---|---|---|
| `port` | `PORT` | `7860` | 1~65535 | `_env.bat` 校验格式与范围；启动器也读写这个键 |
| `host` | `HOST` | `127.0.0.1` | IP | 跨机访问改 `0.0.0.0`，需自行前置换鉴权 |
| `queue_enabled` | `VLX_QUEUE_ENABLED` | `true` | true/false | `false` 时 `/api/queue/*` 一律 503，调测台不受影响 |
| `queue_max_size` | `VLX_QUEUE_MAX_SIZE` | `32` | ≥ 1 | 排队上限，**只算等待中**，正在推理的不占额度 |
| `queue_max_records` | `VLX_QUEUE_MAX_RECORDS` | `200` | ≥ 10 | 内存保留的记录条数，超出淘汰最早结束的 |
| `queue_retry_after` | `VLX_QUEUE_RETRY_AFTER` | `10` | ≥ 1 | 429 的 `Retry-After` 秒数 |

模型侧环境变量（`_env.bat` 已设好，一般不用动）：`HF_ENDPOINT`、`HF_HUB_DISABLE_XET`、
`HF_HUB_ENABLE_HF_TRANSFER`、`VLX_SEEK_BACKEND`、`PYTHONUNBUFFERED`、`PYTHONIOENCODING`；
另有 `VLX_SEEK_MODEL_PATH`、`VLX_WEDETECT_CHECKPOINT`、`VLX_MAX_IMAGE_SIDE`、`VLX_SEEK_DEVICE`、
`VLX_DEBUG_STACK`（详见 README 第 7 章）。

> **改端口不要手改文件后忘了同步启动器**：`启动器.exe` 保存配置时会重写 `config.ini` 的
> `port` / `host` 两行，其余行（`queue_*` 与注释）原样保留。

---

## 5. 发布流程

### 5.1 首次部署

1. 确认目录布局：`VLX-program/` 下 `VLX-Seek/` 与 `Taozi-VLX-deepseek/` 同级。
2. 确认 `../VLX-Seek/.venv/Scripts/python.exe` 存在，且 `pip list` 里有 `requirements.txt` 的依赖。
3. 确认两个权重目录/文件存在（见第 2 章）。
4. 按需改 `config.ini`（端口、`queue_max_size`）。
5. 双击 `debug.bat`，等 `server.log` 出现模型加载完成。
6. 按 5.3 验证。

### 5.2 升级

```bash
git pull origin master
```

- 只改了 Python / 前端 → 重启服务，不重装依赖。
- 改了 `requirements.txt` → `pip install -r requirements.txt` 后重启。
- 改了 `src/launcher.py` → 额外跑 `build_launcher.bat`（PyInstaller 打包，产物 `启动器.exe`）。
- **升级前先确认 `image_queue/` 是空的**（或接受这些图在升级后由新版本继续处理）。sidecar 格式
  只增字段不改语义，跨版本可读。

重启步骤（现场最常用）：

```bat
rem 停：任务管理器结束 python.exe，或启动器里点「停止」
debug.bat
```

`debug.bat` 会在端口已监听时打印 `[WARN]`，别把旧进程当成新进程。

### 5.3 上线验证清单

```bash
curl http://127.0.0.1:7860/api/status
# 期望：model_state 收敛到 ready；device 与预期一致

curl http://127.0.0.1:7860/api/queue/status
# 期望：enabled=true, consumer_running=true,
#       capacity=config.ini 的值, spool.pending 为 0（或等于重启后的恢复条数）

curl -X POST http://127.0.0.1:7860/api/queue/jobs \
  -F "file=@data\images\024f33040501.png" -F "tasks=detection" -F "client_ref=deploy-smoke"
# 期望：202 + job_id；此时 data/image_queue/ 多出 {job_id}.png 与 {job_id}.json

curl http://127.0.0.1:7860/api/queue/jobs/<job_id>
# 期望：几秒后 status=succeeded，image_id 有值，data/images/ 多出该图，image_queue 已清空
```

浏览器 `http://127.0.0.1:7860/docs` 应显示 12 条 `/api` 路径。

---

## 6. 回滚

```bash
git checkout <上一个可用 commit>
```

按变更范围处理：

| 改了什么 | 回滚动作 |
|---|---|
| 仅 Python / 前端 | 重启服务即可 |
| `requirements.txt` | 按旧版本重装依赖后重启 |
| `src/launcher.py` | 重跑 `build_launcher.bat`，否则 exe 仍是新逻辑 |
| `config.ini` | 手动改回（Git 不跟踪本地配置改动时尤其注意） |

**回滚到「没有队列功能」的版本之前**：先处理掉 `data/image_queue/` 里的排队件（或整目录挪到
`data/image_queue_backup/`）。旧版本不认识这个目录，图会一直躺着，也不会有人来取。

回滚不会自动清理 `data/`，磁盘上的图与缓存都保留，重装新版本后仍可用。

---

## 7. 磁盘与数据运维

### 7.1 容量估算

| 目录 | 计算 | 典型值 |
|---|---|---|
| `data/image_queue/`（待处理） | 排队张数 × 单张大小 | 1280 长边 JPEG 约 0.2~0.5MB；`queue_max_size=32` 时 < 20MB |
| `data/image_queue/failed/` | 累计失败张数 × 单张大小 | **无上限**，偷懒不清会一直涨 |
| `data/images/` | 累计处理张数 × (PNG + 缓存 JSON) | 与推图总量线性相关，可按需清 |

### 7.2 `failed/` 清理（唯一需要例行巡检的目录）

顺序不能反：**先看错误，再删文件**。

```powershell
# 1) 看失败原因分布（不改任何东西）
Get-ChildItem .\data\image_queue\failed\*.json |
  ForEach-Object { (Get-Content $_ -Raw | ConvertFrom-Json).error } |
  Group-Object | Sort-Object Count -Descending |
  Select-Object Count, Name

# 2) 看堆积量与占用
$f = Get-ChildItem .\data\image_queue\failed
"{0} 个文件, {1:N1} MB" -f $f.Count, (($f | Measure-Object Length -Sum).Sum / 1MB)

# 3) 确认是坏图/参数错之后，停服务再整目录清空
Remove-Item .\data\image_queue\failed\* -Force
```

典型 `error` 与含义：

| error 片段 | 含义 | 处理 |
|---|---|---|
| `无法解析图片` | 推上来的不是图片或文件损坏 | 清掉，让采集端检查源文件 |
| `推理失败：…` | 模型侧异常（显存、CUDA、超时） | 先修模型问题，再清，否则会继续堆 |
| `1/3 个任务失败。` | 一个 job 里部分任务失败 | 看 `results` 里具体哪条 |
| `排队记录里的任务 id 已不存在` | 升级后任务目录变了 | 清掉即可 |
| `排队记录损坏：tasks 为空` | sidecar 被外部改坏 | 清掉即可 |

### 7.3 孤儿文件检查

以下情况会留下孤儿文件，不影响运行，定期清即可：

- 写原图成功但 sidecar 写失败（磁盘满）→ `image_queue/` 里只有图没有 json。
- 手工删过 sidecar → 同上。

```powershell
# 列出没有同名 sidecar 的孤立原图
Get-ChildItem .\data\image_queue\*.* -File |
  Where-Object { $_.Extension -ne '.json' } |
  Where-Object { -not (Test-Path ($_.FullName -replace '\.[^.]+$', '.json')) }
```

### 7.4 候选框缓存

`data/images/{image_id}.boxes*.json` 是可再生的（删了下次重新推理）。同一张图在不同围栏下
各存一份，所以图片数多 + 围栏多时这里会明显变大，可整体清空。

---

## 8. 监控指标

`GET /api/queue/status` 是唯一的运行态入口，建议外部服务或运维脚本按 30s 采集：

| 字段 | 健康基线 | 异常含义 |
|---|---|---|
| `consumer_running` | `true` | `false` = 消费者挂了或服务在关停 |
| `queued` / `capacity` | 长期 < 0.8×capacity | 持续顶满 = 推图频率高于处理吞吐，见下 |
| `processing` | 0 或 1 | 出现 > 1 说明有人改成了并行，违反硬约束 |
| `spool.pending` | 与 `queued` 大致匹配（每任务 2 个文件） | 明显偏大 = 有孤儿文件或恢复失败 |
| `spool.failed` | 缓慢增长 | 短时间暴涨 = 模型侧或采集端出问题 |
| `rejected_total` | 偶发增长 | 持续增长 = 队列长期满，需要降推图频率 |
| `failed_total` | 偶发增长 | 持续增长 = 看 `failed/` 的 error |

**长期 `429` 的正确处置是降推图频率，不是调大 `queue_max_size`**——调大只是让积压变多、结果更晚。

---

## 9. 故障处置速查

| 现象 | 原因 | 处置 |
|---|---|---|
| 启动报「端口已监听」 | 上一个实例没退干净 | 结束 `python.exe` 再起；或 `run.bat 7861` 换端口 |
| 页面 404 / 样式丢失 | 三个静态挂载点（`/assets` `/features` `/shared`）被改坏 | 检查 `backend/app/main.py` 的 `StaticFiles` 挂载 |
| 模型加载卡在 `loading` | 视觉塔相对路径没生效 / 需下载权重 | 确认 cwd 是项目根（脚本已处理）；`VLX_SEEK_DEVICE=cpu` 先排除 GPU 问题 |
| `/api/queue/*` 全 503 | `queue_enabled=false`，或消费者未启动 | 改 `config.ini` 重启；查 `consumer_running` |
| 投递一直 429 | 队列真的满 / 启动恢复了大量排队件 | 看 `queued` 与 `spool.pending`；降推图频率 |
| 投递 500 | 磁盘满或无写权限 | 清 `failed/`、腾空间，检查 `data/` 权限 |
| `GET /jobs/{id}` 404 | 记录被淘汰或服务重启过 | 排队图会自动重跑，但旧结果记录已丢 |
| 重启后同一张图跑了两遍 | 崩溃点落在「已写 images、未删 sidecar」之间 | 属已知窗口（极窄）；重复结果无害，`data/images/` 里可能多一份图 |
| `启动器.exe` 改端口把 `queue_*` 抹了 | exe 是旧 `launcher.py` 打包的 | 重跑 `build_launcher.bat` |
| 显存 OOM | 起了两个实例，或同机还有别的模型服务 | 保证单实例；`nvidia-smi` 确认占用 |
