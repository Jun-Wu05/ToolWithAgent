"""日志保留策略回归测试（#25，#176 修订总数语义与挂载点）。

验收覆盖：
- 主日志与错误日志分别匹配（app_[0-9]*.log 不误匹配 app_errors_*.log）
- 活动文件（正在写入）永不删除，且计入保留总额度（稳态每类 = keep_count）
- 删除失败（PermissionError/WinError 32）只告警不抛出
- 每进程首个 logger 创建日志文件时自动清理；同进程后续 get_logger 不重复清理
"""

import logging
import os
from unittest.mock import patch

import agent.shared.logger as log_mod
from agent.shared.logger import (
    cleanup_old_logs,
    get_logger,
    initialize_log_retention,
    setup_logger,
)


def _create_log(path, modified_at: int) -> None:
    path.write_text(path.name, encoding="utf-8")
    os.utime(path, (modified_at, modified_at))


class TestMainAndErrorLogSeparation:
    """主日志与错误日志分别保留（#25 验收标准 1）。"""

    def test_main_and_error_logs_are_retained_independently(self, tmp_path):
        """清理主日志时不得把错误日志混入同一个保留集合。"""
        main_logs = [tmp_path / f"app_20260811_12000{i}.log" for i in range(4)]
        error_logs = [
            tmp_path / f"app_errors_20260811_12000{i}.log" for i in range(4)
        ]

        for index, path in enumerate(main_logs):
            _create_log(path, modified_at=100 + index)
        for index, path in enumerate(error_logs):
            _create_log(path, modified_at=200 + index)

        cleanup_old_logs(tmp_path, prefix="app", keep_count=2)

        assert [path.exists() for path in main_logs] == [False, False, True, True]
        assert all(path.exists() for path in error_logs)

    def test_error_logs_cleaned_independently(self, tmp_path):
        """错误日志也能单独清理（prefix="app_errors"）。"""
        error_logs = [
            tmp_path / f"app_errors_20260811_12000{i}.log" for i in range(4)
        ]
        main_logs = [tmp_path / f"app_20260811_12000{i}.log" for i in range(4)]

        for index, path in enumerate(error_logs):
            _create_log(path, modified_at=100 + index)
        for index, path in enumerate(main_logs):
            _create_log(path, modified_at=200 + index)

        cleanup_old_logs(tmp_path, prefix="app_errors", keep_count=2)

        assert [path.exists() for path in error_logs] == [False, False, True, True]
        assert all(path.exists() for path in main_logs)


class TestActiveFileProtection:
    """活动文件（正在写入）永不删除（#25 验收标准 2）。"""

    def test_active_log_file_not_deleted(self, tmp_path):
        """当前正在写入的主日志文件不进入删除集合。"""
        active = tmp_path / "app_20260811_999999.log"
        _create_log(active, modified_at=50)  # 最旧，但没有活跃文件保护会被删
        old_logs = [tmp_path / f"app_20260811_10000{i}.log" for i in range(3)]
        for index, path in enumerate(old_logs):
            _create_log(path, modified_at=200 + index)

        # 模拟 active 文件正在被使用
        original_shared = log_mod._shared_log_file
        log_mod._shared_log_file = active
        try:
            cleanup_old_logs(tmp_path, prefix="app", keep_count=2)
            assert active.exists(), "活动主日志文件不应被删除"
        finally:
            log_mod._shared_log_file = original_shared

    def test_total_including_active_equals_keep_count(self, tmp_path):
        """总数语义（#176）：活动文件计入额度，活动 + 3 份旧文件 → 剩 2 份含活动文件。"""
        active = tmp_path / "app_20260811_999999.log"
        _create_log(active, modified_at=400)  # 最新
        old_logs = [tmp_path / f"app_20260811_10000{i}.log" for i in range(3)]
        for index, path in enumerate(old_logs):
            _create_log(path, modified_at=100 + index)

        original_shared = log_mod._shared_log_file
        log_mod._shared_log_file = active
        try:
            cleanup_old_logs(tmp_path, prefix="app", keep_count=2)
        finally:
            log_mod._shared_log_file = original_shared

        remaining = [p for p in [active, *old_logs] if p.exists()]
        assert remaining == [active, old_logs[-1]], "应保留活动文件 + 最新一份旧文件"


class TestDeleteFailureGraceful:
    """删除失败只告警不抛出（#25 验收标准 3 / WinError 32 回归）。"""

    def test_permission_error_does_not_raise(self, tmp_path):
        """unlink 抛 PermissionError 时 cleanup_old_logs 只告警不中断。"""
        logs = [tmp_path / f"app_20260811_10000{i}.log" for i in range(4)]
        for index, path in enumerate(logs):
            _create_log(path, modified_at=100 + index)

        # mock Path.unlink 抛 PermissionError（模拟 WinError 32）
        original_unlink = type(logs[0]).unlink

        def raising_unlink(self, *args, **kwargs):
            raise PermissionError(32, "文件被占用")

        with patch("pathlib.Path.unlink", raising_unlink):
            # 不应抛出异常
            cleanup_old_logs(tmp_path, prefix="app", keep_count=2)

        # 文件仍在（删除失败了），但函数正常返回
        assert all(path.exists() for path in logs)


class TestGetLoggerNoCleanup:
    """同进程后续 get_logger 不重复清理（#176 修订语义）。"""

    def test_get_logger_does_not_cleanup(self):
        """pytest 进程内共享日志文件已建立，新模块获取 logger 不再触发清理。"""
        with patch("agent.shared.logger.cleanup_old_logs") as mock_cleanup:
            get_logger("test_no_cleanup_module_xyz")
            mock_cleanup.assert_not_called()

    def test_first_logger_creation_triggers_retention(self):
        """模拟新进程：首个 logger 创建共享日志文件时自动执行保留清理。"""
        name = "test_first_retention_process_xyz"
        saved = (
            log_mod._loggers,
            log_mod._shared_log_file,
            log_mod._shared_error_file,
        )
        log_mod._loggers = {}
        log_mod._shared_log_file = None
        log_mod._shared_error_file = None
        try:
            with patch(
                "agent.shared.logger.cleanup_old_logs"
            ) as mock_cleanup:
                setup_logger(name)
                assert mock_cleanup.call_count == 2, "应清理主日志与错误日志两类"
        finally:
            # 关闭新 logger 的文件句柄并恢复进程全局，避免污染真实日志状态
            fresh = logging.getLogger(name)
            for handler in list(fresh.handlers):
                handler.close()
                fresh.removeHandler(handler)
            # 删除本次模拟产生的孤儿日志文件（真实 agent/logs 下）
            for orphan in (
                log_mod._shared_log_file,
                log_mod._shared_error_file,
            ):
                if orphan is not None:
                    orphan.unlink(missing_ok=True)
            log_mod._loggers, log_mod._shared_log_file, log_mod._shared_error_file = saved


class TestInitializeLogRetention:
    """initialize_log_retention 幂等清理（#25 验收标准 4）。"""

    def test_initialize_cleans_both_main_and_error(self, tmp_path):
        """initialize_log_retention 分别清理主日志和错误日志。"""
        main_logs = [tmp_path / f"app_20260811_10000{i}.log" for i in range(5)]
        error_logs = [tmp_path / f"app_errors_20260811_10000{i}.log" for i in range(5)]
        for index, path in enumerate(main_logs):
            _create_log(path, modified_at=100 + index)
        for index, path in enumerate(error_logs):
            _create_log(path, modified_at=200 + index)

        initialize_log_retention(log_dir=tmp_path, keep_count=2)

        main_remaining = [p for p in main_logs if p.exists()]
        error_remaining = [p for p in error_logs if p.exists()]
        assert len(main_remaining) == 2
        assert len(error_remaining) == 2
