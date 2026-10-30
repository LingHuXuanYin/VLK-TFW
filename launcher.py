# -*- coding: utf-8 -*-
"""Taozi VLX 调测台启动器（Windows 桌面客户端）

双击「启动器.exe」后可以：
  * 配置服务端口（写入 config.ini，run.bat / debug.bat 共用同一份配置）
  * 一键启动 / 停止 VLX-Seek 调测服务，无需命令行
  * 实时查看模型加载状态（未运行 / 加载中 / 已就绪 / 出错）与 server.log

开发期可用的隐藏参数（打包成 exe 后无控制台，仅供调试）：
  python launcher.py --selftest        自检：配置读写、端口探测、进程查找、日志读取
  python launcher.py --start 7860      用命令行方式启动服务（验证用）
  python launcher.py --stop 7860       用命令行方式停止服务
  python launcher.py --snap out.png    渲染窗口并截图（验证 UI 用）
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

import tkinter as tk
from tkinter import messagebox
from tkinter import ttk

# ---------------------------------------------------------------- 基础路径

IS_FROZEN = bool(getattr(sys, "frozen", False))
BASE_DIR = (Path(sys.executable).resolve().parent if IS_FROZEN
            else Path(__file__).resolve().parent)
CONFIG_FILE = BASE_DIR / "config.ini"
LOG_FILE = BASE_DIR / "server.log"
APP_FILE = BASE_DIR / "app.py"
VENV_PY = BASE_DIR.parent / "VLX-Seek" / ".venv" / "Scripts" / "python.exe"

DEFAULT_PORT = "7860"
DEFAULT_HOST = "127.0.0.1"

IF_WIN = os.name == "nt"
CREATE_NO_WINDOW = 0x08000000 if IF_WIN else 0

# ---------------------------------------------------------------- 配色

BRAND = "#3d5afe"
BRAND_DARK = "#2338c9"
BRAND_SOFT = "#eef1ff"
INK = "#101828"
INK2 = "#475467"
INK3 = "#7c8798"
LINE = "#e4e9f2"
BG = "#f4f6fb"
WHITE = "#ffffff"
OK = "#0f9d58"
OK_SOFT = "#e9f8ef"
WARN = "#b54708"
WARN_SOFT = "#fffaeb"
DANGER = "#d92d20"
DANGER_SOFT = "#fef3f2"

FONT = ("Microsoft YaHei UI", 10)
FONT_SM = ("Microsoft YaHei UI", 9)
FONT_B = ("Microsoft YaHei UI", 10, "bold")
FONT_TITLE = ("Microsoft YaHei UI", 14, "bold")
MONO = ("Consolas", 9)


# ---------------------------------------------------------------- 配置读写

def load_config() -> dict:
    cfg = {"port": DEFAULT_PORT, "host": DEFAULT_HOST}
    if CONFIG_FILE.exists():
        try:
            text = CONFIG_FILE.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return cfg
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith((";", "#", "[")) or "=" not in line:
                continue
            key, val = line.split("=", 1)
            cfg[key.strip().lower()] = val.strip()
    return cfg


def save_config(port: str, host: str) -> None:
    body = (
        "# Taozi VLX 调测台 · 本地配置\n"
        "# 由「启动器.exe」读写，run.bat / debug.bat 也会读取这里的 port\n"
        "# 端口优先级：命令行参数 > 环境变量 PORT > 本文件 > 7860\n"
        f"port={port}\n"
        f"host={host}\n"
    )
    CONFIG_FILE.write_text(body, encoding="utf-8")


def valid_port(text: str) -> int | None:
    text = (text or "").strip()
    if not text.isdigit():
        return None
    num = int(text)
    return num if 1 <= num <= 65535 else None


# ---------------------------------------------------------------- 进程/端口探测

def http_status(host: str, port: int, timeout: float = 1.2) -> dict | None:
    """请求 /api/status；服务没起或未响应时返回 None。"""
    url = f"http://{host}:{port}/api/status"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception:  # noqa: BLE001 - 连不上就是没起
        return None


def port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.6):
            return True
    except OSError:
        return False


def pid_on_port(port: int) -> int | None:
    """从 netstat 里找出监听该端口的进程号。"""
    if not IF_WIN:
        return None
    try:
        out = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"],
            capture_output=True, text=True, timeout=8,
            creationflags=CREATE_NO_WINDOW,
            encoding="gbk", errors="replace",
        ).stdout
    except Exception:  # noqa: BLE001
        return None
    if not out:
        try:
            out = subprocess.run(
                ["netstat", "-ano", "-p", "TCP"],
                capture_output=True, text=True, timeout=8,
                creationflags=CREATE_NO_WINDOW,
                errors="replace",
            ).stdout
        except Exception:  # noqa: BLE001
            return None
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 5 or not parts[0].upper().startswith("TCP"):
            continue
        local, state, pid = parts[1], parts[3].upper(), parts[4]
        if state != "LISTENING":
            continue
        if local.rsplit(":", 1)[-1] == str(port) and pid.isdigit():
            return int(pid)
    return None


def kill_tree(pid: int) -> bool:
    if not IF_WIN:
        return False
    try:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True, timeout=15, creationflags=CREATE_NO_WINDOW,
        )
        return True
    except Exception:  # noqa: BLE001
        return False


def read_log_tail(max_lines: int = 150, max_bytes: int = 200_000) -> tuple[list[str], int]:
    """读取 server.log 末尾若干行，返回 (行列表, 文件大小)。

    tqdm 加载进度用 \\r 原地刷新、一行能刷出上千次，这里压成最终状态并整体过滤，
    否则面板里全是 "Loading weights: 4%|▎" 这种噪音。
    """
    if not LOG_FILE.exists():
        return [], 0
    try:
        size = LOG_FILE.stat().st_size
        with open(LOG_FILE, "rb") as fh:
            fh.seek(max(0, size - max_bytes))
            data = fh.read()
    except OSError:
        return [], 0

    text = data.decode("utf-8", errors="replace").replace("\r\n", "\n")
    lines: list[str] = []
    for raw in text.split("\n"):
        if "\r" in raw:            # 同一行被 \r 反复刷新，只留最后一次
            raw = raw.split("\r")[-1]
        if not raw.strip():
            continue
        if "%|" in raw or "Loading weights:" in raw or "it/s]" in raw:
            continue                # tqdm 进度条
        if "GET /api/status" in raw:
            continue                # 启动器自己每秒轮询产生的访问日志
        lines.append(raw)
    return lines[-max_lines:], size


# ---------------------------------------------------------------- 服务控制

class ServiceController:
    """负责拉起 / 停止 app.py，并记录是否由自己启动的进程。"""

    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None
        self._log_handle = None

    # -- 状态
    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def exit_code(self) -> int | None:
        return None if self.proc is None else self.proc.poll()

    # -- 启动
    def start(self, port: int, host: str) -> tuple[bool, str]:
        if not VENV_PY.exists():
            return False, (f"未找到 VLX-Seek 虚拟环境：\n{VENV_PY}\n\n"
                           "请先按 VLX-Seek 的《使用教程.md》创建 .venv 并安装依赖。")
        if not APP_FILE.exists():
            return False, f"未找到 app.py：\n{APP_FILE}"
        if self.alive():
            return False, f"服务已在运行（PID {self.proc.pid}）"
        if port_open(host, port):
            if http_status(host, port):
                return False, f"端口 {port} 上已有本服务在运行，直接「打开页面」即可。"
            return False, f"端口 {port} 已被其他程序占用，请换一个端口。"

        env = os.environ.copy()
        env.update({
            "HF_ENDPOINT": "https://hf-mirror.com",
            "HF_HUB_DISABLE_XET": "1",
            "HF_HUB_ENABLE_HF_TRANSFER": "0",
            "VLX_SEEK_BACKEND": "nvidia",
            "PYTHONUNBUFFERED": "1",
            "PYTHONIOENCODING": "utf-8",
            "PORT": str(port),
            "HOST": host,
        })

        try:
            handle = open(LOG_FILE, "a", encoding="utf-8", buffering=1)
            handle.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} "
                         f"启动服务 · 端口 {port} · 由启动器拉起 =====\n")
            handle.flush()
        except OSError as exc:
            return False, f"无法写入日志文件 {LOG_FILE}：{exc}"

        try:
            self.proc = subprocess.Popen(
                [str(VENV_PY), "app.py"],
                cwd=str(BASE_DIR),
                env=env,
                stdout=handle,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                creationflags=CREATE_NO_WINDOW,
            )
        except Exception as exc:  # noqa: BLE001
            handle.close()
            return False, f"启动失败：{type(exc).__name__}: {exc}"

        self._log_handle = handle
        return True, f"已启动（PID {self.proc.pid}），模型加载中，约 20~40 秒…"

    # -- 停止
    def stop(self, port: int, host: str) -> tuple[bool, str]:
        details = []
        if self.alive():
            kill_tree(self.proc.pid)
            self.proc = None
            details.append("已停止启动器拉起的进程")
        if self._log_handle:
            try:
                self._log_handle.close()
            except Exception:  # noqa: BLE001
                pass
            self._log_handle = None

        # 服务可能是 run.bat / debug.bat 拉起的，按端口找进程
        if not details:
            pid = pid_on_port(port)
            if pid:
                kill_tree(pid)
                details.append(f"已停止占用端口 {port} 的进程（PID {pid}）")
        if not details:
            return False, "没有发现正在运行的服务。"

        deadline = time.time() + 6
        while time.time() < deadline:
            if not port_open(host, port):
                return True, "；".join(details) + "，端口已释放。"
            time.sleep(0.25)
        return True, "；".join(details) + f"，但端口 {port} 仍在监听，请稍后确认。"


# ---------------------------------------------------------------- GUI

class LauncherApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.svc = ServiceController()
        self.cfg = load_config()
        self.busy = False
        self.pending_open = False       # 启动完成后自动开浏览器
        self._snapshot: dict = {}
        self._log_sig = None
        self._log_lines: list[str] = []
        self._stop_evt = threading.Event()
        self._last_proc_state = None

        self._init_window()
        self._build_ui()
        self._sync_buttons()
        threading.Thread(target=self._poll_loop, daemon=True).start()
        self.root.after(300, self._tick)
        # 冒烟测试用：带这个环境变量启动会自动点一次「启动服务」
        if os.environ.get("VLX_LAUNCHER_AUTOSTART"):
            self.root.after(1200, self.on_start)

    # -- 窗口
    def _init_window(self) -> None:
        self.root.title("VLX 调测台启动器 · Taozi VLX")
        self.root.geometry("900x680")
        self.root.minsize(760, 560)
        self.root.configure(bg=BG)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _card(self, parent, pad: int = 16) -> tk.Frame:
        frame = tk.Frame(parent, bg=WHITE, highlightbackground=LINE,
                         highlightthickness=1, bd=0)
        inner = tk.Frame(frame, bg=WHITE)
        inner.pack(fill="both", expand=True, padx=pad, pady=pad)
        frame.inner = inner  # type: ignore[attr-defined]
        return frame

    # -- UI 组装
    def _build_ui(self) -> None:
        # 顶部
        header = tk.Frame(self.root, bg=WHITE, height=74)
        header.pack(fill="x")
        header.pack_propagate(False)

        logo = tk.Label(header, text="VLX", bg=BRAND, fg=WHITE,
                        font=("Microsoft YaHei UI", 12, "bold"), width=4, height=2)
        logo.pack(side="left", padx=(20, 12), pady=14)

        titles = tk.Frame(header, bg=WHITE)
        titles.pack(side="left", pady=14)
        tk.Label(titles, text="Taozi VLX 调测台", bg=WHITE, fg=INK,
                 font=FONT_TITLE, anchor="w").pack(anchor="w")
        tk.Label(titles, text="VLX-Seek 1.5-10B · 七种任务接口调试 · 配置端口后一键启动",
                 bg=WHITE, fg=INK3, font=FONT_SM, anchor="w").pack(anchor="w")

        self.pill = tk.Label(header, text="检测中…", bg="#eef1f7", fg=INK2,
                             font=FONT_B, padx=14, pady=5)
        self.pill.pack(side="right", padx=(8, 20))
        self.pill_dot = tk.Label(header, text="●", bg="#eef1f7", fg=INK3, font=("Segoe UI", 9))
        self.pill_dot.pack(side="right")

        tk.Frame(self.root, bg=LINE, height=1).pack(fill="x")

        body = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", expand=True, padx=18, pady=16)

        # --- 服务设置
        card1 = self._card(body)
        card1.pack(fill="x")
        c1 = card1.inner

        tk.Label(c1, text="服务设置", bg=WHITE, fg=INK, font=FONT_B).pack(anchor="w")
        row = tk.Frame(c1, bg=WHITE)
        row.pack(fill="x", pady=(10, 0))

        tk.Label(row, text="端口", bg=WHITE, fg=INK2, font=FONT).pack(side="left")
        self.port_var = tk.StringVar(value=self.cfg.get("port", DEFAULT_PORT))
        self.current_port = valid_port(self.port_var.get()) or int(DEFAULT_PORT)
        # Tk 变量不能跨线程读，交给主线程的 trace 维护一个普通属性
        self.port_var.trace_add("write", self._on_port_change)
        self.port_entry = tk.Entry(row, textvariable=self.port_var, width=8,
                                   font=("Consolas", 12), justify="center",
                                   relief="solid", bd=1, bg="#fbfcff", fg=INK,
                                   highlightthickness=0)
        self.port_entry.pack(side="left", padx=(8, 10), ipady=3)
        tk.Label(row, text=f"1~65535，默认 {DEFAULT_PORT}；监听 {self.cfg.get('host', DEFAULT_HOST)}",
                 bg=WHITE, fg=INK3, font=FONT_SM).pack(side="left")

        self.start_btn = tk.Button(row, text="启动服务", command=self.on_start,
                                   bg=BRAND, fg=WHITE, font=FONT_B, relief="flat",
                                   activebackground=BRAND_DARK, activeforeground=WHITE,
                                   cursor="hand2", padx=18, pady=6)
        self.stop_btn = tk.Button(row, text="停止服务", command=self.on_stop,
                                  bg=WHITE, fg=INK2, font=FONT, relief="solid", bd=1,
                                  activebackground="#f6f8fd", cursor="hand2", padx=14, pady=5)
        self.open_btn = tk.Button(row, text="打开页面", command=self.on_open,
                                  bg=WHITE, fg=INK2, font=FONT, relief="solid", bd=1,
                                  activebackground="#f6f8fd", cursor="hand2", padx=14, pady=5)
        self.open_btn.pack(side="right")
        self.stop_btn.pack(side="right", padx=8)
        self.start_btn.pack(side="right")

        opts = tk.Frame(c1, bg=WHITE)
        opts.pack(fill="x", pady=(10, 0))
        self.auto_open = tk.BooleanVar(value=True)
        tk.Checkbutton(opts, text="就绪后自动打开浏览器", variable=self.auto_open,
                       bg=WHITE, fg=INK2, font=FONT_SM, activebackground=WHITE,
                       selectcolor=WHITE, highlightthickness=0,
                       cursor="hand2").pack(side="left")
        tk.Button(opts, text="打开 config.ini", command=self.on_open_config,
                  bg=WHITE, fg=BRAND, font=FONT_SM, relief="flat", cursor="hand2",
                  activebackground=WHITE).pack(side="left", padx=(14, 0))
        tk.Button(opts, text="打开日志文件", command=self.on_open_log,
                  bg=WHITE, fg=BRAND, font=FONT_SM, relief="flat", cursor="hand2",
                  activebackground=WHITE).pack(side="left", padx=(6, 0))

        # --- 运行状态
        card2 = self._card(body, pad=14)
        card2.pack(fill="x", pady=(12, 0))
        c2 = card2.inner

        head2 = tk.Frame(c2, bg=WHITE)
        head2.pack(fill="x")
        tk.Label(head2, text="运行状态", bg=WHITE, fg=INK, font=FONT_B).pack(side="left")
        self.pid_label = tk.Label(head2, text="", bg=WHITE, fg=INK3, font=FONT_SM)
        self.pid_label.pack(side="right")

        grid = tk.Frame(c2, bg=WHITE)
        grid.pack(fill="x", pady=(8, 0))
        self.stat_labels = {}
        for idx, (key, title) in enumerate(
                [("state", "服务"), ("device", "设备"), ("load", "加载耗时"), ("url", "地址")]):
            tk.Label(grid, text=title, bg=WHITE, fg=INK3, font=FONT_SM).grid(
                row=0, column=idx * 2, sticky="w", padx=(0, 6))
            val = tk.Label(grid, text="—", bg=WHITE, fg=INK, font=FONT)
            val.grid(row=0, column=idx * 2 + 1, sticky="w", padx=(0, 22))
            self.stat_labels[key] = val

        self.msg_label = tk.Label(c2, text="点击「启动服务」拉起模型服务；端口改动会写入 config.ini。",
                                  bg=WHITE, fg=INK3, font=FONT_SM,
                                  anchor="w", justify="left", wraplength=780)
        self.msg_label.pack(fill="x", pady=(6, 0))

        # --- 日志
        card3 = self._card(body, pad=14)
        card3.pack(fill="both", expand=True, pady=(12, 0))
        c3 = card3.inner

        head3 = tk.Frame(c3, bg=WHITE)
        head3.pack(fill="x")
        tk.Label(head3, text="服务日志", bg=WHITE, fg=INK, font=FONT_B).pack(side="left")
        tk.Label(head3, text="（server.log 末尾 150 行，自动刷新）", bg=WHITE, fg=INK3,
                 font=FONT_SM).pack(side="left", padx=(8, 0))

        wrap = tk.Frame(c3, bg="#fbfcff", highlightbackground=LINE, highlightthickness=1)
        wrap.pack(fill="both", expand=True, pady=(10, 0))
        self.log_text = tk.Text(wrap, bg="#fbfcff", fg=INK, font=MONO, relief="flat",
                                bd=0, wrap="none", state="disabled", height=10)
        self.log_text.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=6)
        bar = ttk.Scrollbar(wrap, orient="vertical", command=self.log_text.yview)
        bar.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=bar.set)
        self.log_text.tag_configure("err", foreground=DANGER)
        self.log_text.tag_configure("warn", foreground=WARN)
        self.log_text.tag_configure("ok", foreground=OK)

        # 底部
        footer = tk.Frame(self.root, bg=BG)
        footer.pack(fill="x", padx=20, pady=(0, 12))
        tk.Label(footer, text=f"配置：{CONFIG_FILE}", bg=BG, fg=INK3,
                 font=FONT_SM).pack(side="left")
        tk.Label(footer, text="端口会写入 config.ini，run.bat / debug.bat 共用",
                 bg=BG, fg=INK3, font=FONT_SM).pack(side="right")

    # ------------------------------------------------------------ 交互
    def _on_port_change(self, *_) -> None:
        self.current_port = valid_port(self.port_var.get())

    def on_start(self) -> None:
        if self.busy:
            return
        port = valid_port(self.port_var.get())
        if port is None:
            messagebox.showerror("端口不合法", "端口必须是 1~65535 之间的整数。")
            self.port_entry.focus_set()
            return
        if port < 1024:
            if not messagebox.askyesno("端口偏小", f"{port} 属于特权端口（<1024），"
                                                    "可能被系统占用或需要管理员权限，仍要使用吗？"):
                return
        host = self.cfg.get("host", DEFAULT_HOST)
        try:
            save_config(str(port), host)
        except OSError as exc:
            messagebox.showerror("写入配置失败", f"{CONFIG_FILE}\n{exc}")

        self.busy = True
        ok, msg = self.svc.start(port, host)
        self.busy = False
        self.pending_open = bool(self.auto_open.get()) and ok
        if not ok:
            messagebox.showwarning("无法启动", msg)
            self._sync_buttons()
            return
        self.msg_label.configure(text=msg, fg=OK)
        self._sync_buttons()

    def on_stop(self) -> None:
        if self.busy:
            return
        port = valid_port(self.port_var.get()) or int(self.cfg.get("port", DEFAULT_PORT))
        host = self.cfg.get("host", DEFAULT_HOST)
        if not self.svc.alive() and not pid_on_port(port):
            messagebox.showinfo("无需停止", "当前没有发现运行中的服务。")
            self._sync_buttons()
            return
        if not messagebox.askyesno("停止服务", f"确认停止端口 {port} 上的服务进程？"):
            return
        self.busy = True
        ok, msg = self.svc.stop(port, host)
        self.busy = False
        self.pending_open = False
        if ok:
            self.msg_label.configure(text=msg, fg=INK2)
        else:
            messagebox.showwarning("停止失败", msg)
        self._sync_buttons()

    def on_open(self) -> None:
        port = valid_port(self.port_var.get()) or int(self.cfg.get("port", DEFAULT_PORT))
        host = self.cfg.get("host", DEFAULT_HOST)
        url = f"http://{host}:{port}/"
        if not port_open(host, port):
            if not messagebox.askyesno("服务未响应", f"{url} 暂时连不上，仍要打开吗？\n"
                                                    "（模型加载期间端口会先起来，但页面可能还打不开）"):
                return
        os.startfile(url) if IF_WIN else None  # noqa: B018

    def on_open_log(self) -> None:
        if not LOG_FILE.exists():
            messagebox.showinfo("没有日志", "还没有生成 server.log，先启动一次服务吧。")
            return
        os.startfile(str(LOG_FILE)) if IF_WIN else None  # noqa: B018

    def on_open_config(self) -> None:
        save_config(self.port_var.get().strip() or DEFAULT_PORT,
                    self.cfg.get("host", DEFAULT_HOST))
        os.startfile(str(CONFIG_FILE)) if IF_WIN else None  # noqa: B018

    # ------------------------------------------------------------ 刷新
    def _poll_loop(self) -> None:
        """后台轮询：端口状态 + 日志末尾，UI 线程只读快照。"""
        while not self._stop_evt.is_set():
            try:
                port = self.current_port
                host = self.cfg.get("host", DEFAULT_HOST)
                snap = {
                    "port": port,
                    "alive": self.svc.alive(),
                    "rc": self.svc.exit_code(),
                    "api": http_status(host, port) if port else None,
                    "pid": self.svc.proc.pid if self.svc.alive() else None,
                }
                lines, size = read_log_tail()
                self._snapshot = snap
                self._log_lines, self._log_size = lines, size
            except Exception:  # noqa: BLE001 - 轮询线程不能死
                pass
            time.sleep(1.0)

    def _tick(self) -> None:
        snap = self._snapshot
        if snap:
            self._apply_snapshot(snap)
        size = getattr(self, "_log_size", 0)
        if size != self._log_sig:
            self._log_sig = size
            self._apply_log()
        self.root.after(600, self._tick)

    def _apply_snapshot(self, snap: dict) -> None:
        api = snap.get("api") or {}
        api_status = api.get("status")
        port = snap.get("port") or "—"
        host = self.cfg.get("host", DEFAULT_HOST)
        self.stat_labels["url"].configure(text=f"http://{host}:{port}/")

        if api_status == "ready":
            self._set_pill("模型已就绪", OK_SOFT, "#067647", OK)
            self.stat_labels["state"].configure(text="ready", fg=OK)
            self.stat_labels["device"].configure(text=str(api.get("device") or "—"))
            load = api.get("load_seconds")
            self.stat_labels["load"].configure(text=f"{load}s" if load else "—")
            if self.pending_open:
                self.pending_open = False
                self.on_open()
        elif api_status == "loading":
            self._set_pill("模型加载中…", WARN_SOFT, WARN, WARN)
            self.stat_labels["state"].configure(text="loading", fg=WARN)
            self.stat_labels["device"].configure(text="—")
            self.stat_labels["load"].configure(text="—")
        elif api_status == "error":
            self._set_pill("模型加载失败", DANGER_SOFT, DANGER, DANGER)
            self.stat_labels["state"].configure(text="error", fg=DANGER)
            self.msg_label.configure(text=str(api.get("error") or ""), fg=DANGER)
        elif snap.get("alive"):
            self._set_pill("启动中…", WARN_SOFT, WARN, WARN)
            self.stat_labels["state"].configure(text="starting", fg=WARN)
        else:
            rc = snap.get("rc")
            if rc not in (None, 0):
                self._set_pill("进程已退出", DANGER_SOFT, DANGER, DANGER)
                self.stat_labels["state"].configure(text=f"exited({rc})", fg=DANGER)
            else:
                self._set_pill("未运行", "#eef1f7", INK2, INK3)
                self.stat_labels["state"].configure(text="stopped", fg=INK3)
            for k in ("device", "load"):
                self.stat_labels[k].configure(text="—")

        pid = snap.get("pid")
        self.pid_label.configure(text=f"PID {pid}" if pid else "")
        self._sync_buttons(running=bool(snap.get("alive") or api_status in ("ready", "loading")))

    def _set_pill(self, text: str, bg: str, fg: str, dot: str) -> None:
        if self.pill.cget("text") == text and self.pill.cget("bg") == bg:
            return
        self.pill.configure(text=text, bg=bg, fg=fg)
        self.pill_dot.configure(bg=bg, fg=dot)

    def _apply_log(self) -> None:
        lines = self._log_lines
        widget = self.log_text
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        if not lines:
            widget.insert("end", "（暂无日志，启动服务后会实时显示）")
        else:
            for line in lines:
                low = line.lower()
                tag = ""
                if "error" in low or "traceback" in low or "exception" in low:
                    tag = "err"
                elif "warn" in low:
                    tag = "warn"
                elif "已就绪" in line or "application startup complete" in low:
                    tag = "ok"
                widget.insert("end", line + "\n", tag)
        widget.see("end")
        widget.configure(state="disabled")

    def _sync_buttons(self, running: bool | None = None) -> None:
        if running is None:
            running = self.svc.alive() or bool((self._snapshot.get("api") or {}))
        state = "normal" if running else "normal"
        self.start_btn.configure(state="disabled" if running else state,
                                 bg="#a8b1c4" if running else BRAND,
                                 cursor="arrow" if running else "hand2")
        self.stop_btn.configure(state="normal" if running else "disabled",
                                fg=INK2 if running else "#b6bfcd")
        self.open_btn.configure(state="normal" if running else "disabled",
                                fg=INK2 if running else "#b6bfcd")
        try:
            self.port_entry.configure(state="disabled" if running else "normal")
        except tk.TclError:
            pass

    # ------------------------------------------------------------ 关闭
    def _on_close(self) -> None:
        if self.svc.alive():
            answer = messagebox.askyesnocancel(
                "退出启动器",
                "服务仍在运行。\n\n是：停止服务后退出\n否：保持服务运行，只关窗口",
            )
            if answer is None:
                return
            if answer:
                port = valid_port(self.port_var.get()) or int(self.cfg.get("port", DEFAULT_PORT))
                self.svc.stop(port, self.cfg.get("host", DEFAULT_HOST))
        self._stop_evt.set()
        self.root.destroy()


# ---------------------------------------------------------------- 命令行辅助（验证用）

def run_selftest() -> int:
    out = []

    def log(msg: str) -> None:
        out.append(msg)
        print(msg)

    log(f"frozen={IS_FROZEN}")
    log(f"BASE_DIR={BASE_DIR}")
    log(f"VENV_PY exists={VENV_PY.exists()}")
    log(f"APP exists={APP_FILE.exists()}")

    cfg = load_config()
    log(f"load_config={cfg}")
    saved = (cfg.get("port"), cfg.get("host"))
    save_config("7860", "127.0.0.1")
    log(f"round-trip={load_config()}")
    save_config(str(saved[0]), saved[1])
    log(f"restored={load_config()}")

    for probe in ("7860", "0", "70000", "abc", "80 80"):
        log(f"valid_port({probe!r})={valid_port(probe)}")

    for p in (int(saved[0] or DEFAULT_PORT), int(saved[0] or DEFAULT_PORT) + 1):
        log(f"port_open({p})={port_open('127.0.0.1', p)} pid_on_port={pid_on_port(p)} "
            f"api={ (http_status('127.0.0.1', p) or {}).get('status') }")

    lines, size = read_log_tail()
    log(f"log_bytes={size} tail_lines={len(lines)}")
    if lines:
        log(f"log_last={lines[-1][:120]}")

    (BASE_DIR / "launcher-selftest.log").write_text("\n".join(out), encoding="utf-8")
    return 0


def run_cli_start(port_text: str) -> int:
    port = valid_port(port_text)
    if port is None:
        print(f"非法端口：{port_text}")
        return 2
    host = load_config().get("host", DEFAULT_HOST)
    save_config(str(port), host)
    svc = ServiceController()
    ok, msg = svc.start(port, host)
    print(("OK " if ok else "FAIL ") + msg)
    return 0 if ok else 1


def run_cli_stop(port_text: str) -> int:
    port = valid_port(port_text) or int(load_config().get("port", DEFAULT_PORT))
    ok, msg = ServiceController().stop(port, load_config().get("host", DEFAULT_HOST))
    print(("OK " if ok else "FAIL ") + msg)
    return 0 if ok else 1


def run_snap(path: str) -> int:
    try:
        from PIL import ImageGrab
    except ImportError:
        print("需要 Pillow 才能截图")
        return 3
    root = tk.Tk()
    app = LauncherApp(root)
    root.attributes("-topmost", True)
    root.update()

    def capture() -> None:
        root.update_idletasks()
        # Tk 是 DPI 不感知的，坐标是逻辑像素；ImageGrab 抓的是物理像素，先算缩放比
        full = ImageGrab.grab()
        scale = full.width / max(1, root.winfo_screenwidth())
        x, y = root.winfo_rootx(), root.winfo_rooty()
        w, h = root.winfo_width(), root.winfo_height()
        bbox = (int(x * scale), int(y * scale),
                int((x + w) * scale), int((y + h) * scale))
        ImageGrab.grab(bbox=bbox).save(path)
        print(f"saved {path} scale={scale:.3f} bbox={bbox}")
        root.destroy()

    root.after(2200, capture)
    root.mainloop()
    return 0


def main() -> int:
    args = sys.argv[1:]
    if "--selftest" in args:
        return run_selftest()
    if "--start" in args:
        idx = args.index("--start")
        return run_cli_start(args[idx + 1] if len(args) > idx + 1 else DEFAULT_PORT)
    if "--stop" in args:
        idx = args.index("--stop")
        return run_cli_stop(args[idx + 1] if len(args) > idx + 1 else DEFAULT_PORT)
    if "--snap" in args:
        idx = args.index("--snap")
        return run_snap(args[idx + 1] if len(args) > idx + 1 else "launcher.png")

    root = tk.Tk()
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:  # noqa: BLE001
        pass
    LauncherApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
