import tempfile
import unittest
from pathlib import Path

from core.context import TaskContext
from core.models import AppConfig


class AppConfigTests(unittest.TestCase):
    def test_from_dict_builds_nested_config_objects(self) -> None:
        app_config = AppConfig.from_dict(
            {
                "remote": {
                    "user": "nvidia",
                    "ip": "192.168.10.2",
                    "data_root": "/remote/data",
                },
                "host": {
                    "mdrive_root": "/host/mdrive",
                    "nas_root": "/host/nas",
                    "data_root": "/host/data",
                    "dest_root": "/host/dest",
                },
                "docker": {
                    "container": "demo_container",
                    "host_mount": "/media",
                    "docker_mount": "/media",
                    "docker_scripts": "/scripts",
                    "setup_env": "/env/setup.sh",
                },
                "logic": {
                    "vehicle": "XZB600013",
                    "target_date": "20260415",
                    "mode": "1",
                    "version": "",
                    "soc": "soc",
                    "before": "15",
                    "after": 5,
                    "blacklist": ["foo", "bar"],
                },
                "paths": {
                    "scripts_dir": "./scripts",
                },
            }
        )

        self.assertEqual(app_config.host.dest_root, "/host/dest")
        self.assertEqual(app_config.remote.user, "nvidia")
        self.assertEqual(app_config.docker.container, "demo_container")
        self.assertEqual(app_config.logic.before, 15)
        self.assertEqual(app_config.logic.blacklist, ["foo", "bar"])
        self.assertEqual(app_config.paths.scripts_dir, "./scripts")


class TaskContextTests(unittest.TestCase):
    def test_context_exposes_typed_config_and_env_vars(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root_path = Path(tmpdir)
            config_path = root_path / "settings.yaml"
            config_path.write_text(
                "\n".join(
                    [
                        "remote:",
                        '  user: "nvidia"',
                        '  ip: "192.168.10.2"',
                        '  data_root: "/remote/data"',
                        "host:",
                        '  mdrive_root: "/host/mdrive"',
                        '  nas_root: "/host/nas"',
                        '  data_root: "/host/data"',
                        '  dest_root: "/host/dest"',
                        "docker:",
                        '  container: "demo_container"',
                        '  host_mount: "/media"',
                        '  docker_mount: "/media"',
                        '  docker_scripts: "/scripts"',
                        '  setup_env: "/env/setup.sh"',
                        "logic:",
                        '  vehicle: "XZB600013"',
                        '  target_date: "20260415"',
                        "  mode: 1",
                        '  version: ""',
                        '  soc: "soc"',
                        "  before: 15",
                        "  after: 5",
                        "  blacklist:",
                        "paths:",
                        '  scripts_dir: "./scripts"',
                    ]
                ),
                encoding="utf-8",
            )

            task_context = TaskContext(config_path)

            self.assertEqual(task_context.host.dest_root, "/host/dest")
            self.assertEqual(task_context.remote.ip, "192.168.10.2")
            self.assertEqual(task_context.docker.setup_env, "/env/setup.sh")
            self.assertEqual(task_context.paths.scripts_dir, "./scripts")
            self.assertEqual(task_context.vehicle, "XZB600013")
            self.assertEqual(task_context.logic.after, 5)
            self.assertEqual(
                str(task_context.work_dir),
                "/host/dest/{0}/{1}".format(task_context.target_date[:8], task_context.vehicle),
            )

            env_vars = task_context.get_env_vars()

        self.assertEqual(env_vars["VEHICLE"], "XZB600013")
        self.assertEqual(env_vars["DEST_ROOT"], "/host/dest")
        self.assertEqual(env_vars["MODE"], "1")
        self.assertEqual(env_vars["AFTER"], "5")
        self.assertEqual(env_vars["CONTAINER"], "demo_container")
        self.assertEqual(env_vars["REMOTE_IP"], "192.168.10.2")


if __name__ == "__main__":
    unittest.main()
