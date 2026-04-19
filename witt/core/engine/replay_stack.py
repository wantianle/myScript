import os
import re
import subprocess
from pathlib import Path
from typing import List

from core.errors import ReplayStackError

_BASE_DIR = Path(__file__).resolve().parents[2]
_CONFIG_DIR = _BASE_DIR / "config"
_MULTIVIZ_CONFIG_NAME = "customized_20260403.multiviz.yaml"
_LOCAL_MULTIVIZ_CONFIG_PATH = _CONFIG_DIR / _MULTIVIZ_CONFIG_NAME
_CONTAINER_MULTIVIZ_CONFIG_PATH = "/mdrive/{0}".format(_MULTIVIZ_CONFIG_NAME)
_CAMERA_CONFIG_NAME = "h26x_to_nv12.pb.txt"
_LOCAL_CAMERA_CONFIG_PATH = _CONFIG_DIR / _CAMERA_CONFIG_NAME
_CONTAINER_CAMERA_CONFIG_PATH = (
    "/mdrive/mdrive_conf/modules/perception_trafficlights/{0}".format(
        _CAMERA_CONFIG_NAME
    )
)


class ReplayStackManager:
    """负责启动标准回播和红绿灯回灌所需的运行模块。"""

    def start_standard_replay_stack(self, ctx) -> None:
        """启动标准回播栈。"""
        container = ctx.docker.container
        self._allow_failure(["xhost", "+local:docker"])
        self._copy_file_to_container(
            _LOCAL_MULTIVIZ_CONFIG_PATH,
            container,
            _CONTAINER_MULTIVIZ_CONFIG_PATH,
        )
        self._run_detached_command(
            [
                "docker",
                "exec",
                "-d",
                container,
                "bash",
                "-c",
                (
                    "sudo -E bash /mdrive/mdrive/scripts/cmd.sh && "
                    "sudo supervisorctl start Dreamview && "
                    "sudo supervisorctl start Debug_Driver-LiDAR"
                ),
            ],
            "启动标准回播模块失败",
        )
        multiviz_cmd = [
            "docker",
            "exec",
            "-d",
        ]
        if self._container_has_xauthority(container):
            multiviz_cmd.extend(
                [
                    "-e",
                    "DISPLAY={0}".format(os.environ.get("DISPLAY", ":0")),
                    "-e",
                    "XAUTHORITY=/tmp/.Xauthority",
                ]
            )
        multiviz_cmd.extend(
            [
                container,
                "/mdrive/mdrive/bin/mdrive_multiviz",
                "-d",
                _CONTAINER_MULTIVIZ_CONFIG_PATH,
            ]
        )
        self._run_detached_command(multiviz_cmd, "启动 mdrive_multiviz 失败")
        self._open_browser("http://localhost:8888")

    def start_traffic_light_stack(self, ctx) -> None:
        """启动红绿灯回灌栈。"""
        container = ctx.docker.container
        traffic_light_config_path = (
            Path(ctx.host.mdrive_root)
            / "mdrive_conf"
            / "modules"
            / "perception_trafficlights"
            / "perception_traffic_light.pb.txt"
        )
        self._copy_file_to_container(
            _LOCAL_CAMERA_CONFIG_PATH,
            container,
            _CONTAINER_CAMERA_CONFIG_PATH,
        )
        (Path(ctx.host.mdrive_root) / "data" / "test").mkdir(parents=True, exist_ok=True)
        self._enable_save_debug_images(traffic_light_config_path)
        self._run_detached_command(
            [
                "docker",
                "exec",
                "-d",
                container,
                "bash",
                "-c",
                (
                    "sudo supervisorctl start Perception-LiDAR && "
                    "sudo supervisorctl start Debug_Driver-Camera && "
                    "sudo supervisorctl start Perception-TrafficLight"
                ),
            ],
            "启动红绿灯回灌模块失败",
        )

    def _allow_failure(self, cmd: List[str]) -> None:
        subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )

    def _copy_file_to_container(
        self,
        local_path: Path,
        container: str,
        container_path: str,
    ) -> None:
        if not local_path.is_file():
            return
        self._run_command(
            ["docker", "cp", str(local_path), "{0}:{1}".format(container, container_path)],
            "同步配置文件失败",
        )

    def _container_has_xauthority(self, container: str) -> bool:
        completed_process = subprocess.run(
            ["docker", "exec", container, "ls", "/tmp/.Xauthority"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return completed_process.returncode == 0

    def _run_detached_command(self, cmd: List[str], error_summary: str) -> None:
        self._run_command(cmd, error_summary)

    def _open_browser(self, url: str) -> None:
        try:
            subprocess.Popen(
                ["xdg-open", url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            return

    def _enable_save_debug_images(self, config_path: Path) -> None:
        if not config_path.is_file():
            raise ReplayStackError("文件不存在: {0}".format(config_path))
        config_text = config_path.read_text(encoding="utf-8")
        updated_text, _ = re.subn(
            r"(?m)^([ \t]*)save_debug_img:[ \t]*false\b",
            r"\1save_debug_img: true",
            config_text,
        )
        config_path.write_text(updated_text, encoding="utf-8")

    def _run_command(self, cmd: List[str], error_summary: str) -> str:
        try:
            completed_process = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
            )
            return completed_process.stdout
        except subprocess.CalledProcessError as e:
            detail = e.stderr.strip() or e.stdout.strip()
            details = [detail] if detail else []
            raise ReplayStackError(
                "{0}".format(error_summary)
                if not details
                else "{0}: {1}".format(error_summary, details[0])
            ) from e
