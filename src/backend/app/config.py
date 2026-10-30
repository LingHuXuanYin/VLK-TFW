"""全局配置：路径、环境变量、VLX-Seek 引导。

这是**唯一**允许读取环境变量与拼接磁盘路径的地方。其他地方一律 `from .config import XXX`。

路径约定：
- `SRC_ROOT`（= `src/`）放全部源码与前端静态资源；
- `PROJECT_ROOT`（= 项目根）放 `config.ini`、`server.log`、`data/`、`assets/` 等运行/构建产物。

副作用说明（有意为之，不可移除）：
- `bootstrap_vlx_seek()` 会在本模块导入时执行一次：把 `VLX-Seek` 加入 `sys.path`，并
  `chdir` 到 VLX-Seek 目录。因为 `VLX-Seek/config.json` 里视觉塔写的是相对路径
  （`resources/Qwen3.5-9B-Vision_Tower`），不切目录会去找 HuggingFace 仓库而卡死。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# 路径锚点：src/backend/app/config.py -> src/backend/app -> src/backend -> src
# 源码（backend / features / shared / web）全部在 SRC_ROOT 下；
# 运行时产物（config.ini、server.log、data/）与构建物仍在 PROJECT_ROOT（项目根）。
SRC_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = SRC_ROOT.parent

# 推理代码库（默认与本项目同级）
VLX_SEEK_ROOT = Path(
    os.environ.get("VLX_SEEK_ROOT", str(PROJECT_ROOT.parent / "VLX-Seek"))
).resolve()

# 模型与权重
MODEL_PATH = os.environ.get(
    "VLX_SEEK_MODEL_PATH", str(VLX_SEEK_ROOT / "resources" / "VLX-Seek-1.5-10B")
)
WEDETECT_PATH = os.environ.get(
    "VLX_WEDETECT_CHECKPOINT", str(VLX_SEEK_ROOT / "resources" / "wedetect_base_uni.pth")
)

# 上传图长边上限（0 表示不缩放），接口文档建议 1280
MAX_IMAGE_SIDE = int(os.environ.get("VLX_MAX_IMAGE_SIDE", "1280"))

# 设备偏好：auto / cuda:0 / cpu，最终由 services/device.py 解析
DEVICE_PREFERENCE = os.environ.get("VLX_SEEK_DEVICE") or "auto"

# 静态资源目录（前端源码，随源码一起放在 src/ 下）
WEB_DIR = SRC_ROOT / "web"
FEATURES_DIR = SRC_ROOT / "features"
SHARED_DIR = SRC_ROOT / "shared"

# 运行时数据（上传图 + 候选框缓存），可随时删除
DATA_DIR = PROJECT_ROOT / "data" / "images"

# 监听地址：uvicorn 启动参数，port 优先级由 run.bat / 启动器处理
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "7860"))


def bootstrap_vlx_seek() -> None:
    """把 VLX-Seek 加入 `sys.path` 并切换工作目录。幂等，可重复调用。

    入参：无。
    返回：无。
    异常：目录不存在时不抛异常（后续加载模型时会给出更明确的报错）。
    边界：`chdir` 是进程级的，调用后所有相对路径都相对 VLX-Seek 解析。
    """
    if str(VLX_SEEK_ROOT) not in sys.path:
        sys.path.insert(0, str(VLX_SEEK_ROOT))
    if VLX_SEEK_ROOT.is_dir():
        os.chdir(VLX_SEEK_ROOT)


# 导入即引导，保持与重构前「运行服务入口就能加载模型」的行为一致
bootstrap_vlx_seek()

# 数据目录按需创建（models 层不负责建目录）
DATA_DIR.mkdir(parents=True, exist_ok=True)

# 需要定期打印线程栈排查卡死时：set VLX_DEBUG_STACK=30
if os.environ.get("VLX_DEBUG_STACK"):
    import faulthandler

    faulthandler.dump_traceback_later(int(os.environ["VLX_DEBUG_STACK"]), repeat=True)
