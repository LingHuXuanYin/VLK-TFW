"""全局配置：路径、环境变量、config.ini、VLX-Seek 引导。

这是**唯一**允许读取环境变量与拼接磁盘路径的地方。其他地方一律 `from .config import XXX`。

路径约定：
- `SRC_ROOT`（= `src/`）放全部源码与前端静态资源；
- `PROJECT_ROOT`（= 项目根）放 `config.ini`、`server.log`、`data/`、`assets/` 等运行/构建产物。

配置优先级（本文件里所有可配项都遵守）：环境变量 > `config.ini` > 代码默认值。
`config.ini` 是扁平 `key=value`（无节名），因为 `_env.bat` 用 `for /f` 逐行解析它，
启动器也按同一格式读写；加节名会让 bat 的解析出现无意义的分支。

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


# ---------------------------------------------------------------------------
# config.ini（扁平 key=value，UTF-8）
# ---------------------------------------------------------------------------
CONFIG_FILE = PROJECT_ROOT / "config.ini"


def read_config_file() -> dict[str, str]:
    """读取 `config.ini` 的全部键值，键名一律小写。

    入参：无（路径固定为 `PROJECT_ROOT/config.ini`）。
    返回：`{key: value}`；文件不存在、不可读或解析失败时返回空 dict（不抛异常）。
    边界：忽略空行、以 `#` / `;` 开头的注释行、以 `[` 开头的节名行；
         值里允许出现 `=`（只按第一个 `=` 切分）。
    """
    values: dict[str, str] = {}
    if not CONFIG_FILE.is_file():
        return values
    try:
        text = CONFIG_FILE.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return values
    for line in text.splitlines():
        line = line.strip()
        if not line or line[0] in "#;[" or "=" not in line:
            continue
        key, val = line.split("=", 1)
        values[key.strip().lower()] = val.strip()
    return values


_CONFIG_VALUES = read_config_file()


def _setting(env_name: str, ini_key: str, default: str) -> str:
    """按「环境变量 > config.ini > 默认值」取一个字符串配置。"""
    raw = os.environ.get(env_name)
    if raw is None or not str(raw).strip():
        raw = _CONFIG_VALUES.get(ini_key)
    if raw is None or not str(raw).strip():
        return default
    return str(raw).strip()


def _setting_int(env_name: str, ini_key: str, default: int, minimum: int) -> int:
    """取整数配置；非法值回落默认值，结果不低于 `minimum`（避免 0 上限把队列锁死）。"""
    try:
        value = int(_setting(env_name, ini_key, str(default)))
    except ValueError:
        value = default
    return max(minimum, value)


def _setting_bool(env_name: str, ini_key: str, default: bool) -> bool:
    """取布尔配置；`1/true/yes/on` 为真，`0/false/no/off` 为假，其余回落默认值。"""
    raw = _setting(env_name, ini_key, "true" if default else "false").lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return default


# ---------------------------------------------------------------------------
# 生产消费队列（外部服务定期推图用）
# ---------------------------------------------------------------------------
# 是否开启队列接入；关掉后 /api/queue/* 一律 503，前端调测台不受影响
QUEUE_ENABLED = _setting_bool("VLX_QUEUE_ENABLED", "queue_enabled", True)
# 排队上限（只算「等待中」的任务；正在推理的那个不占额度）
QUEUE_MAX_SIZE = _setting_int("VLX_QUEUE_MAX_SIZE", "queue_max_size", 32, 1)
# 内存里最多保留多少条任务记录（含已完成），超出淘汰最老的，防止进程内存无上限增长
QUEUE_MAX_RECORDS = _setting_int("VLX_QUEUE_MAX_RECORDS", "queue_max_records", 200, 10)
# 队列超限时返回给外部服务的 Retry-After 秒数
QUEUE_RETRY_AFTER = _setting_int("VLX_QUEUE_RETRY_AFTER", "queue_retry_after", 10, 1)



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
