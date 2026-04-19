import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from core.errors import ScriptExecutionError
from core.runner import ScriptRunner


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


if __name__ == "__main__":
    unittest.main()
