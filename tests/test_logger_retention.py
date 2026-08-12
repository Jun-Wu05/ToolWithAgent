"""日志保留策略回归测试（#25）。

验收覆盖：
- 主日志与错误日志分别匹配（app_[0-9]*.log 不误匹配 app_errors_*.log）
- 活动文件（正在写入）永不删除
- 删除失败（PermissionError/WinError 32）只告警不抛出
- get_logger 不触发清理（清理只由 initialize_log_retention 在启动时执行）
"""

import os
from unittest.mock import patch

from agent.shared.logger import cleanup_old_logs, get_logger, initialize_log_retention


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
        import agent.shared.logger as log_mod

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
    """get_logger 不触发清理（#25 验收标准 4）。"""

    def test_get_logger_does_not_cleanup(self):
        """新模块首次获取 logger 不触发 cleanup_old_logs。"""
        with patch("agent.shared.logger.cleanup_old_logs") as mock_cleanup:
            get_logger("test_no_cleanup_module_xyz")
            mock_cleanup.assert_not_called()


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
