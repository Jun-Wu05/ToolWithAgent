"""v2/dev.py 启动器纯函数单测：环境组装、端口探测与 bootstrap 判定，不启动真实子进程。"""
import importlib.util
import os
import socket
from pathlib import Path

# 按路径导入 v2/dev.py（它不属于 toolwithagent_v2 包，不能用普通 import）。
DEV_PATH = Path(__file__).resolve().parents[2] / "dev.py"
_spec = importlib.util.spec_from_file_location("v2_dev_launcher", DEV_PATH)
dev = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dev)


def os_pathsep() -> str:
    return os.pathsep


def test_build_environment_fills_defaults_and_merges_pythonpath(tmp_path, monkeypatch):
    for name in ("V2_DATA_DIR", "V2_MODE", "V2_WORKER_CONCURRENCY", "PYTHONPATH"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PYTHONPATH", "outside" + os_pathsep() + str(tmp_path))
    env = dev.build_environment(tmp_path)
    assert env["V2_DATA_DIR"] == str(tmp_path / "tmp" / "v2-data")
    assert env["V2_MODE"] == "development"
    assert env["V2_WORKER_CONCURRENCY"] == "1"
    entries = env["PYTHONPATH"].split(os_pathsep())
    # 用户已有 PYTHONPATH 保留在前，仓库根与 v2/backend 追加且不重复。
    assert entries[:2] == ["outside", str(tmp_path)]
    assert entries.count(str(tmp_path)) == 1
    assert str(tmp_path / "v2" / "backend") in entries


def test_build_environment_respects_explicit_user_values(tmp_path, monkeypatch):
    monkeypatch.setenv("V2_DATA_DIR", r"D:\elsewhere")
    monkeypatch.setenv("V2_MODE", "production")
    env = dev.build_environment(tmp_path)
    assert env["V2_DATA_DIR"] == r"D:\elsewhere"
    assert env["V2_MODE"] == "production"


def test_port_available_reports_bound_port_as_busy():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as holder:
        holder.bind((dev.HOST, 0))
        holder.listen(1)
        port = holder.getsockname()[1]
        assert not dev.port_available(dev.HOST, port)
    assert dev.port_available(dev.HOST, port)


def test_pip_marker_tracks_pyproject_digest(tmp_path):
    backend = tmp_path / "v2" / "backend"
    backend.mkdir(parents=True)
    pyproject = backend / "pyproject.toml"
    pyproject.write_text("dependencies = []\n", encoding="utf-8")
    first = dev.pip_marker_content(tmp_path)
    assert first == dev.pip_marker_content(tmp_path)
    pyproject.write_text('dependencies = ["uvicorn"]\n', encoding="utf-8")
    assert dev.pip_marker_content(tmp_path) != first


def test_venv_python_follows_platform_layout(tmp_path, monkeypatch):
    monkeypatch.setattr(dev.os, "name", "nt", raising=False)
    assert dev.venv_python(tmp_path).as_posix().endswith("tmp/venv/Scripts/python.exe")
    monkeypatch.setattr(dev.os, "name", "posix", raising=False)
    assert dev.venv_python(tmp_path).as_posix().endswith("tmp/venv/bin/python")
