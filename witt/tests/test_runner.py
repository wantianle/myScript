import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

from core.errors import CommandExecutionError
from core.errors import ScriptExecutionError
from core.models import TaskEntry
from core.runner import ScriptRunner
from utils import parser


class ScriptRunnerTests(unittest.TestCase):
    def test_build_script_execution_error_prefers_domain_error_summary(self) -> None:
        runner = ScriptRunner(
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

    def test_run_find_record_uses_python_finder_for_local_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "tasks.list"
            runner = ScriptRunner(
                cast(
                    Any,
                    SimpleNamespace(
                        paths=SimpleNamespace(scripts_dir="scripts"),
                        docker=SimpleNamespace(docker_scripts="/tmp"),
                        host=SimpleNamespace(
                            data_root="/tmp/local_root",
                            nas_root="/tmp/nas_root",
                        ),
                        logic=SimpleNamespace(
                            mode=1,
                            before=15,
                            after=5,
                            soc="soc1",
                        ),
                        target_date="20260419",
                        vehicle="XZB600001",
                        manifest_path=manifest_path,
                        find_record_output="",
                    ),
                )
            )
            task_entries = [
                TaskEntry.from_manifest_parts(
                    time="2026-04-19 12:00:00",
                    name="demo_tag",
                    paths=["/tmp/local_root/soc1/a.record"],
                )
            ]

            with patch(
                "core.runner.record_finder.find_local_tasks",
                return_value=task_entries,
            ) as find_local_tasks:
                with patch.object(
                    runner,
                    "_run_script_with_terminal_capture",
                ) as run_script_with_terminal_capture:
                    returned_tasks = runner.run_find_record()

            find_local_tasks.assert_called_once_with(
                Path("/tmp/local_root"),
                target_date="20260419",
                before=15,
                after=5,
                soc_filter="soc1",
            )
            run_script_with_terminal_capture.assert_not_called()
            self.assertEqual(returned_tasks, task_entries)
            parsed_tasks = parser.parse_manifest(manifest_path)
            self.assertEqual(len(parsed_tasks), 1)
            self.assertEqual(parsed_tasks[0].name, "demo_tag")

    def test_run_find_record_uses_python_finder_for_nas_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "tasks.list"
            runner = ScriptRunner(
                cast(
                    Any,
                    SimpleNamespace(
                        paths=SimpleNamespace(scripts_dir="scripts"),
                        docker=SimpleNamespace(docker_scripts="/tmp"),
                        host=SimpleNamespace(
                            data_root="/tmp/local_root",
                            nas_root="/tmp/nas_root",
                        ),
                        logic=SimpleNamespace(
                            mode=2,
                            before=15,
                            after=5,
                            soc="",
                        ),
                        target_date="20260419",
                        vehicle="XZB600001",
                        manifest_path=manifest_path,
                        find_record_output="",
                    ),
                )
            )

            with patch(
                "core.runner.record_finder.find_local_tasks",
                return_value=[],
            ) as find_local_tasks:
                with patch(
                    "core.runner.record_finder.dump_manifest",
                    return_value="",
                ):
                    returned_tasks = runner.run_find_record()

            find_local_tasks.assert_called_once_with(
                Path("/tmp/nas_root/20260419/XZB600001"),
                target_date="20260419",
                before=15,
                after=5,
                soc_filter="",
            )
            self.assertEqual(returned_tasks, [])

    def test_run_find_record_uses_python_finder_for_remote_mode(self) -> None:
        runner = ScriptRunner(
            cast(
                Any,
                SimpleNamespace(
                    paths=SimpleNamespace(scripts_dir="scripts"),
                    docker=SimpleNamespace(docker_scripts="/tmp"),
                    remote=SimpleNamespace(
                        user="mini",
                        ip="10.0.0.1",
                        data_root="/remote/root",
                    ),
                    host=SimpleNamespace(
                        data_root="/tmp/local_root",
                        nas_root="/tmp/nas_root",
                    ),
                    logic=SimpleNamespace(
                        mode=3,
                        before=15,
                        after=5,
                        soc="",
                    ),
                    target_date="20260419",
                    vehicle="XZB600001",
                    manifest_path=Path("/tmp/tasks.list"),
                    find_record_output="",
                ),
            )
        )

        task_entries = [
            TaskEntry.from_manifest_parts(
                time="2026-04-19 12:00:00",
                name="demo_tag",
                paths=["/tmp/remote/soc1/a.record"],
            )
        ]

        with patch.object(
            runner,
            "_run_remote_find_paths",
            return_value=["/remote/root/demo_tag_20260419.pb.txt"],
        ) as run_remote_find_paths:
            with patch(
                "core.runner.record_finder.find_tasks_from_path_texts",
                return_value=task_entries,
            ) as find_tasks_from_path_texts:
                returned_tasks = runner.run_find_record()

        run_remote_find_paths.assert_called_once_with()
        find_tasks_from_path_texts.assert_called_once()
        self.assertEqual(returned_tasks, task_entries)

    def test_run_find_record_wraps_remote_connection_error(self) -> None:
        runner = ScriptRunner(
            cast(
                Any,
                SimpleNamespace(
                    paths=SimpleNamespace(scripts_dir="scripts"),
                    docker=SimpleNamespace(docker_scripts="/tmp"),
                    remote=SimpleNamespace(
                        user="mini",
                        ip="10.0.0.1",
                        data_root="/remote/root",
                    ),
                    host=SimpleNamespace(
                        data_root="/tmp/local_root",
                        nas_root="/tmp/nas_root",
                    ),
                    logic=SimpleNamespace(
                        mode=3,
                        before=15,
                        after=5,
                        soc="",
                    ),
                    target_date="20260419",
                    vehicle="XZB600001",
                    manifest_path=Path("/tmp/tasks.list"),
                    find_record_output="",
                ),
            )
        )

        with patch.object(
            runner,
            "_run_remote_find_paths",
            side_effect=CommandExecutionError("SSH 执行失败: timeout"),
        ):
            with self.assertRaises(ScriptExecutionError) as raised:
                runner.run_find_record()

        self.assertEqual(
            raised.exception.summary,
            "无法连接车机或找不到对应record 文件！",
        )

    def test_restore_runtime_environment_uses_python_runtime_sync(self) -> None:
        runner = ScriptRunner(
            cast(
                Any,
                SimpleNamespace(
                    paths=SimpleNamespace(scripts_dir="scripts"),
                    docker=SimpleNamespace(docker_scripts="/tmp"),
                    host=SimpleNamespace(mdrive_root="/tmp/mdrive"),
                    logic=SimpleNamespace(version="/tmp/version.json"),
                    vehicle="XZB600001",
                ),
            )
        )

        with patch(
            "core.runner.runtime_env.restore_runtime_environment",
            return_value=False,
        ) as restore_runtime_environment:
            runner.restore_runtime_environment()

        restore_runtime_environment.assert_called_once_with(
            version_path=Path("/tmp/version.json"),
            vmc_path=Path("/tmp/mdrive/vmc.sh"),
            vehicle_name="XZB600001",
        )

    def test_start_replay_stack_uses_python_replay_stack(self) -> None:
        runner = ScriptRunner(
            cast(
                Any,
                SimpleNamespace(
                    paths=SimpleNamespace(scripts_dir="scripts"),
                    docker=SimpleNamespace(docker_scripts="/tmp"),
                    host=SimpleNamespace(mdrive_root="/tmp/mdrive"),
                ),
            )
        )

        with patch("core.runner.replay_stack.start_standard_replay_stack") as start_standard_replay_stack:
            runner.start_replay_stack()

        start_standard_replay_stack.assert_called_once_with(runner.ctx)

    def test_start_traffic_light_stack_uses_python_replay_stack(self) -> None:
        runner = ScriptRunner(
            cast(
                Any,
                SimpleNamespace(
                    paths=SimpleNamespace(scripts_dir="scripts"),
                    docker=SimpleNamespace(docker_scripts="/tmp"),
                    host=SimpleNamespace(mdrive_root="/tmp/mdrive"),
                ),
            )
        )

        with patch("core.runner.replay_stack.start_traffic_light_stack") as start_traffic_light_stack:
            runner.start_traffic_light_stack()

        start_traffic_light_stack.assert_called_once_with(runner.ctx)


if __name__ == "__main__":
    unittest.main()
