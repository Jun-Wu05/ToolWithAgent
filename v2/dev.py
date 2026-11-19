"""V2 开发环境一键启动器：单终端拉起 API、Worker 与前端。

用法（worktree 根目录）::

    python v2/dev.py            # 幂等 bootstrap 后拉起三进程，Ctrl+C 一键全停
    python v2/dev.py --reinstall  # 强制重跑 pip install（依赖变更后）

仅使用标准库。环境契约与 v2/README.md 手动三终端方式一致：
V2_DATA_DIR/V2_MODE/V2_WORKER_CONCURRENCY + PYTHONPATH=<repo>;<repo>/v2/backend
（后端进程顶层 import 仓库根级 application/agent/contracts，pip install -e 只装 toolwithagent_v2）。
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

HOST = "127.0.0.1"
API_PORT = 8100
WEB_PORT = 5173
HEALTH_PATH = "/health/live"
HEALTH_TIMEOUT_SECONDS = 30.0
INSTALL_MARKER = ".v2-dev-installed"


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def venv_python(repo: Path) -> Path:
    inner = "Scripts/python.exe" if os.name == "nt" else "bin/python"
    return repo / "tmp" / "venv" / inner


def build_environment(repo: Path) -> dict[str, str]:
    """组装三进程共享环境；已显式设置的用户变量不覆盖。"""
    env = os.environ.copy()
    env.setdefault("V2_DATA_DIR", str(repo / "tmp" / "v2-data"))
    env.setdefault("V2_MODE", "development")
    env.setdefault("V2_WORKER_CONCURRENCY", "1")
    merged: list[str] = []
    for part in (env.get("PYTHONPATH", ""), str(repo), str(repo / "v2" / "backend")):
        for item in part.split(os.pathsep):
            if item and item not in merged:
                merged.append(item)
    env["PYTHONPATH"] = os.pathsep.join(merged)
    return env


def port_available(host: str, port: int) -> bool:
    # 不设 SO_REUSEADDR：Windows 下它允许对监听中端口二次绑定，探测会误报可用。
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((host, port))
        except OSError:
            return False
        return True


def run_prefixed(prefix: str, argv: list[str], *, cwd: Path, env: dict[str, str]) -> int:
    """阻塞执行 bootstrap 子进程，输出加 [prefix] 前缀。"""
    print(f"[{prefix}] $ {' '.join(argv)}", flush=True)
    completed = subprocess.run(argv, cwd=str(cwd), env=env, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True, errors="replace")
    for line in completed.stdout.splitlines():
        print(f"[{prefix}] {line}", flush=True)
    return completed.returncode


def pip_marker_content(repo: Path) -> str:
    """marker 记录 pyproject 摘要，依赖声明变化时自动触发重装。"""
    pyproject = (repo / "v2" / "backend" / "pyproject.toml").read_bytes()
    return hashlib.sha256(pyproject).hexdigest() + "\n"


def ensure_bootstrap(repo: Path, env: dict[str, str], *, reinstall: bool = False) -> Path:
    """幂等准备 venv、后端依赖与前端 node_modules；返回 venv python 路径。"""
    python = venv_python(repo)
    marker = python.parent / INSTALL_MARKER
    if not python.exists():
        print("[dev] 创建虚拟环境 tmp/venv …", flush=True)
        code = run_prefixed("dev", [sys.executable, "-m", "venv", str(repo / "tmp" / "venv")],
                            cwd=repo, env=env)
        if code != 0 or not python.exists():
            raise SystemExit("[dev] 虚拟环境创建失败，请检查 python -m venv。")
    if reinstall or not marker.exists() or marker.read_text(encoding="utf-8") != pip_marker_content(repo):
        print("[dev] 安装后端依赖（pip install -e v2/backend[test]）…", flush=True)
        code = run_prefixed("dev", [str(python), "-m", "pip", "install", "-q", "-e", "v2/backend[test]"],
                            cwd=repo, env=env)
        if code != 0:
            raise SystemExit("[dev] 后端依赖安装失败，可重试 python v2/dev.py --reinstall。")
        marker.write_text(pip_marker_content(repo), encoding="utf-8")
    if not (repo / "v2" / "frontend" / "node_modules").exists():
        npm = shutil.which("npm")
        if npm is None:
            raise SystemExit("[dev] 未找到 npm，请先安装 Node.js 后重跑。")
        print("[dev] 安装前端依赖（npm install）…", flush=True)
        code = run_prefixed("dev", [npm, "install"], cwd=repo / "v2" / "frontend", env=env)
        if code != 0:
            raise SystemExit("[dev] 前端依赖安装失败，请检查 Node.js 环境后重试。")
    return python


def spawn(prefix: str, argv: list[str], *, cwd: Path, env: dict[str, str]) -> subprocess.Popen:
    """启动长驻子进程：合并输出交给前缀读线程，POSIX 独立进程组便于整组终止。"""
    process = subprocess.Popen(argv, cwd=str(cwd), env=env, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True, bufsize=1, errors="replace",
                               start_new_session=os.name != "nt")

    def pump() -> None:
        assert process.stdout is not None
        for line in iter(process.stdout.readline, ""):
            print(f"[{prefix}] {line.rstrip()}", flush=True)

    threading.Thread(target=pump, daemon=True, name=f"reader-{prefix}").start()
    return process


def terminate_tree(process: subprocess.Popen) -> None:
    """终止整个进程树；Windows 用 taskkill /T /F（npm→node→vite→esbuild 多层）。"""
    if process.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=10, check=False)
        except subprocess.TimeoutExpired:
            process.kill()
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except OSError:
            process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def wait_for_health(host: str, port: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    url = f"http://{host}:{port}{HEALTH_PATH}"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return True
        except OSError:
            pass
        time.sleep(0.5)
    return False


def stop_all(processes: list[tuple[str, subprocess.Popen]]) -> None:
    for _, process in processes:
        terminate_tree(process)


def main() -> int:
    parser = argparse.ArgumentParser(description="V2 一键开发启动器（API + Worker + 前端）")
    parser.add_argument("--reinstall", action="store_true", help="强制重跑后端 pip install")
    args = parser.parse_args()

    repo = repo_root()
    for name, port in (("API", API_PORT), ("前端", WEB_PORT)):
        if not port_available(HOST, port):
            print(f"[dev] 端口 {port}（{name}）已被占用，请先关闭旧进程再启动。", flush=True)
            return 1
    env = build_environment(repo)
    python = ensure_bootstrap(repo, env, reinstall=args.reinstall)
    npm = shutil.which("npm")
    if npm is None:
        print("[dev] 未找到 npm，请先安装 Node.js 后重跑。", flush=True)
        return 1

    processes: list[tuple[str, subprocess.Popen]] = []
    try:
        processes.append(("api", spawn("api", [str(python), "-m", "uvicorn", "toolwithagent_v2.main:app",
                                              "--host", HOST, "--port", str(API_PORT)], cwd=repo, env=env)))
        if not wait_for_health(HOST, API_PORT, HEALTH_TIMEOUT_SECONDS):
            print(f"[dev] API 在 {HEALTH_TIMEOUT_SECONDS:.0f}s 内未就绪（/health/live），已停止全部进程，请查看上方 [api] 日志。", flush=True)
            return 1
        print(f"[dev] API 就绪 http://{HOST}:{API_PORT} ，启动 Worker 与前端 …", flush=True)
        processes.append(("worker", spawn("worker", [str(python), "-m", "toolwithagent_v2.runtime.worker"],
                                          cwd=repo, env=env)))
        processes.append(("web", spawn("web", [npm, "run", "dev", "--", "--strictPort"],
                                       cwd=repo / "v2" / "frontend", env=env)))
        print(f"[dev] 全部就绪：前端 http://{HOST}:{WEB_PORT} ，API http://{HOST}:{API_PORT} 。Ctrl+C 一键停止。", flush=True)
        while True:
            time.sleep(0.5)
            for name, process in processes:
                if process.poll() is not None:
                    print(f"[dev] {name} 进程已退出（code={process.returncode}），停止其余进程。", flush=True)
                    return 1
    except KeyboardInterrupt:
        print("[dev] 收到 Ctrl+C，停止全部进程 …", flush=True)
        return 0
    finally:
        stop_all(processes)


if __name__ == "__main__":
    raise SystemExit(main())
