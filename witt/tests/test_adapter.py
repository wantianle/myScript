import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from core.adapter.docker import DockerAdapter
from core.adapter.ssh import SSHAdapter
from core.errors import CommandExecutionError, PathMappingError


class DockerAdapterTests(unittest.TestCase):
    def _build_adapter(self, host_mount: Path) -> DockerAdapter:
        ctx = SimpleNamespace(
            docker=SimpleNamespace(
                container="demo_container",
                setup_env="/env/setup.sh",
                host_mount=str(host_mount),
                docker_mount="/docker_mount",
            )
        )
        return DockerAdapter(ctx)

    def test_map_path_maps_host_path_into_docker_mount(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            host_mount = Path(tmpdir) / "media"
            record_path = host_mount / "task" / "demo.record"
            record_path.parent.mkdir(parents=True, exist_ok=True)
            record_path.touch()
            adapter = self._build_adapter(host_mount)

            docker_path = adapter.map_path(record_path)

        self.assertEqual(docker_path, "/docker_mount/task/demo.record")

    def test_map_path_raises_when_path_is_outside_mount(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root_path = Path(tmpdir)
            host_mount = root_path / "media"
            outside_path = root_path / "other" / "demo.record"
            host_mount.mkdir(parents=True, exist_ok=True)
            outside_path.parent.mkdir(parents=True, exist_ok=True)
            outside_path.touch()
            adapter = self._build_adapter(host_mount)

            with self.assertRaises(PathMappingError):
                adapter.map_path(outside_path)

    def test_execute_uses_argv_style_docker_exec(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = self._build_adapter(Path(tmpdir))

        with patch(
            "core.adapter.docker.subprocess.run",
            return_value=SimpleNamespace(stdout="ok"),
        ) as subprocess_run:
            stdout = adapter.execute("echo 'hello'")

        self.assertEqual(stdout, "ok")
        subprocess_run.assert_called_once_with(
            [
                "docker",
                "exec",
                "demo_container",
                "/bin/bash",
                "-lc",
                "export LANG=C.UTF-8 && export LC_ALL=C.UTF-8 && source /env/setup.sh && echo 'hello'",
            ],
            capture_output=True,
            text=True,
            check=True,
        )

    def test_execute_wraps_docker_command_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = self._build_adapter(Path(tmpdir))

        with patch(
            "core.adapter.docker.subprocess.run",
            side_effect=subprocess.CalledProcessError(
                1,
                ["docker"],
                stderr="boom",
            ),
        ):
            with self.assertRaises(CommandExecutionError) as raised:
                adapter.execute("echo hello")

        self.assertEqual(str(raised.exception), "Docker 执行失败: boom")

    def test_fetch_file_copies_local_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root_path = Path(tmpdir)
            adapter = self._build_adapter(root_path)
            source_path = root_path / "source.txt"
            dest_path = root_path / "dest.txt"
            source_path.write_text("demo", encoding="utf-8")

            adapter.fetch_file(str(source_path), dest_path)

            self.assertEqual(dest_path.read_text(encoding="utf-8"), "demo")

    def test_remove_deletes_local_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root_path = Path(tmpdir)
            adapter = self._build_adapter(root_path)
            target_path = root_path / "demo.txt"
            target_path.write_text("demo", encoding="utf-8")

            adapter.remove(str(target_path))

            self.assertFalse(target_path.exists())


class SSHAdapterTests(unittest.TestCase):
    def _build_adapter(self) -> SSHAdapter:
        ctx = SimpleNamespace(
            remote=SimpleNamespace(
                user="nvidia",
                ip="192.168.10.2",
            ),
            docker=SimpleNamespace(
                setup_env="/env/setup.sh",
            ),
        )
        return SSHAdapter(ctx)

    def test_execute_builds_expected_remote_command(self) -> None:
        adapter = self._build_adapter()

        with patch.object(adapter, "_call", return_value="ok") as call:
            stdout = adapter.execute("echo hello")

        self.assertEqual(stdout, "ok")
        ssh_cmd = call.call_args[0][0]
        self.assertEqual(ssh_cmd[0], "ssh")
        self.assertEqual(ssh_cmd[-2], "nvidia@192.168.10.2")
        self.assertIn("export GLOG_log_dir=/tmp", ssh_cmd[-1])
        self.assertIn("export MDRIVE_ROOT_DIR='/mdrive'", ssh_cmd[-1])
        self.assertIn("export MDRIVE_DEP_DIR='/mdrive/mdrive_dep'", ssh_cmd[-1])
        self.assertIn("source /env/setup.sh && echo hello", ssh_cmd[-1])
        self.assertEqual(call.call_args[0][1], "SSH 执行失败")

    def test_fetch_file_quotes_remote_path(self) -> None:
        adapter = self._build_adapter()

        with patch.object(adapter, "_call", return_value="") as call:
            adapter.fetch_file("/tmp/a b.record", Path("/tmp/out.record"))

        scp_cmd = call.call_args[0][0]
        self.assertEqual(scp_cmd[0], "scp")
        self.assertIn("nvidia@192.168.10.2:'/tmp/a b.record'", scp_cmd)
        self.assertEqual(call.call_args[0][1], "SCP 同步失败")

    def test_remove_quotes_path_before_execute(self) -> None:
        adapter = self._build_adapter()

        with patch.object(adapter, "execute", return_value="") as execute:
            adapter.remove("/tmp/a b.record")

        execute.assert_called_once_with("rm -f '/tmp/a b.record'")

if __name__ == "__main__":
    unittest.main()
