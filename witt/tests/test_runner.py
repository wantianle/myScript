import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import ANY, Mock, patch

from core.errors import CommandExecutionError
from core.errors import FindRecordError
from core.errors import ScriptExecutionError
from core.runner import RuntimeCoordinator


class RuntimeCoordinatorTests(unittest.TestCase):
    def _build_runtime_runner(self) -> RuntimeCoordinator:
        return RuntimeCoordinator(
            cast(
                Any,
                SimpleNamespace(
                    paths=SimpleNamespace(scripts_dir="scripts"),
                    docker=SimpleNamespace(docker_scripts="/tmp"),
                    host=SimpleNamespace(mdrive_root="/tmp/mdrive"),
                    logic=SimpleNamespace(
                        version="/tmp/version.json",
                        vehicle="XZB600001",
                    ),
                ),
            )
        )

    def test_build_script_execution_error_prefers_domain_error_summary(self) -> None:
        runner = RuntimeCoordinator(
            cast(
                Any,
                SimpleNamespace(
                    paths=SimpleNamespace(scripts_dir="scripts"),
                    docker=SimpleNamespace(docker_scripts="/tmp"),
                ),
            )
        )

        script_error = runner._build_script_execution_error(
            "find_record.sh",
            (
                "\x1b[0;31m[ERROR] 无法连接车机或找不到对应record 文件！\x1b[0m\n"
                "\x1b[0;31m[ERROR] /tmp/find_record.sh退出状态码: 1\x1b[0m\n"
                "\x1b[0;31m[ERROR] 命令在第 12 行发生错误: ssh_cmd \"$find_cmd\"\x1b[0m\n"
            ),
        )

        self.assertIsInstance(script_error, ScriptExecutionError)
        self.assertEqual(script_error.summary, "无法连接车机或找不到对应record 文件！")
        self.assertEqual(
            script_error.details,
            [
                "/tmp/find_record.sh退出状态码: 1",
                "命令在第 12 行发生错误: ssh_cmd \"$find_cmd\"",
            ],
        )

    def test_run_find_record_delegates_to_record_query_service(self) -> None:
        runner = RuntimeCoordinator(
            cast(
                Any,
                SimpleNamespace(
                    paths=SimpleNamespace(scripts_dir="scripts"),
                    docker=SimpleNamespace(docker_scripts="/tmp"),
                ),
            )
        )
        task_entries = [cast(Any, object())]

        with patch.object(
            runner.record_query_service,
            "run_query",
            return_value=task_entries,
        ) as run_query:
            returned_tasks = runner.run_find_record()

        run_query.assert_called_once_with()
        self.assertEqual(returned_tasks, task_entries)

    def test_run_find_record_wraps_remote_connection_error(self) -> None:
        runner = RuntimeCoordinator(
            cast(
                Any,
                SimpleNamespace(
                    paths=SimpleNamespace(scripts_dir="scripts"),
                    docker=SimpleNamespace(docker_scripts="/tmp"),
                ),
            )
        )

        with patch.object(
            runner.record_query_service,
            "run_query",
            side_effect=CommandExecutionError("SSH 执行失败: timeout"),
        ):
            with self.assertRaises(ScriptExecutionError) as raised:
                runner.run_find_record()

        self.assertEqual(
            raised.exception.summary,
            "无法连接车机或找不到对应record 文件！",
        )
        self.assertEqual(raised.exception.operation_name, "record_query")

    def test_run_find_record_wraps_domain_query_error(self) -> None:
        runner = RuntimeCoordinator(
            cast(
                Any,
                SimpleNamespace(
                    paths=SimpleNamespace(scripts_dir="scripts"),
                    docker=SimpleNamespace(docker_scripts="/tmp"),
                ),
            )
        )

        with patch.object(
            runner.record_query_service,
            "run_query",
            side_effect=FindRecordError("/tmp/root 找不到对应的 tag 文件！"),
        ):
            with self.assertRaises(ScriptExecutionError) as raised:
                runner.run_find_record()

        self.assertEqual(raised.exception.summary, "/tmp/root 找不到对应的 tag 文件！")
        self.assertEqual(raised.exception.operation_name, "record_query")

    def test_restore_runtime_environment_uses_python_runtime_sync(self) -> None:
        runner = self._build_runtime_runner()
        version_info = Mock()

        with patch(
            "core.runner.runtime_env.load_version_info",
            return_value=version_info,
        ) as load_version_info, patch(
            "core.runner.runtime_env.sync_runtime_environment",
            return_value=False,
        ) as sync_runtime_environment, patch(
            "core.runner.subprocess.run"
        ) as subprocess_run:
            runner.restore_runtime_environment()

        load_version_info.assert_called_once_with(Path("/tmp/version.json"))
        sync_runtime_environment.assert_called_once_with(
            Path("/tmp/mdrive/vmc.sh"),
            version_info,
            "XZB600001",
        )
        subprocess_run.assert_not_called()

    def test_restore_runtime_environment_executes_vmc_when_runtime_changes(self) -> None:
        runner = self._build_runtime_runner()
        completed_process = Mock(returncode=0, stdout="")
        version_info = Mock()

        with patch(
            "core.runner.runtime_env.load_version_info",
            return_value=version_info,
        ) as load_version_info, patch(
            "core.runner.runtime_env.sync_runtime_environment",
            return_value=True,
        ) as sync_runtime_environment, patch(
            "core.runner.subprocess.run",
            return_value=completed_process,
        ) as subprocess_run, patch.dict(
            "core.runner.os.environ",
            {"TEST_ENV": "1"},
            clear=True,
        ):
            runner.restore_runtime_environment()

        load_version_info.assert_called_once_with(Path("/tmp/version.json"))
        sync_runtime_environment.assert_called_once_with(
            Path("/tmp/mdrive/vmc.sh"),
            version_info,
            "XZB600001",
        )
        subprocess_run.assert_called_once_with(
            ["bash", "/tmp/mdrive/vmc.sh"],
            env={"TEST_ENV": "1"},
            text=True,
            stdout=ANY,
            stderr=ANY,
            check=False,
        )

    def test_start_standard_replay_stack_uses_python_replay_stack(self) -> None:
        runner = RuntimeCoordinator(
            cast(
                Any,
                SimpleNamespace(
                    paths=SimpleNamespace(scripts_dir="scripts"),
                    docker=SimpleNamespace(docker_scripts="/tmp"),
                    host=SimpleNamespace(mdrive_root="/tmp/mdrive"),
                ),
            )
        )

        with patch.object(
            runner.replay_stack_manager,
            "start_standard_replay_stack",
        ) as start_standard_replay_stack:
            runner.start_standard_replay_stack()

        start_standard_replay_stack.assert_called_once_with(runner.ctx)

    def test_start_traffic_light_stack_uses_python_replay_stack(self) -> None:
        runner = RuntimeCoordinator(
            cast(
                Any,
                SimpleNamespace(
                    paths=SimpleNamespace(scripts_dir="scripts"),
                    docker=SimpleNamespace(docker_scripts="/tmp"),
                    host=SimpleNamespace(mdrive_root="/tmp/mdrive"),
                ),
            )
        )

        with patch.object(
            runner.replay_stack_manager,
            "start_traffic_light_stack",
        ) as start_traffic_light_stack:
            runner.start_traffic_light_stack()

        start_traffic_light_stack.assert_called_once_with(runner.ctx)


if __name__ == "__main__":
    unittest.main()
