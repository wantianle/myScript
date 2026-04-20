import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

from core.engine import replay_stack


class ReplayStackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.replay_stack_manager = replay_stack.ReplayStackManager()

    def test_start_standard_replay_stack_dispatches_expected_steps(self) -> None:
        ctx = cast(
            Any,
            SimpleNamespace(
                docker=SimpleNamespace(container="demo_container"),
            ),
        )

        with patch.object(self.replay_stack_manager, "_allow_failure") as allow_failure:
            with patch.object(self.replay_stack_manager, "_copy_file_to_container") as copy_file:
                with patch.object(self.replay_stack_manager, "_run_detached_command") as run_detached_command:
                    with patch(
                        "core.engine.replay_stack.ReplayStackManager._container_has_xauthority",
                        return_value=True,
                    ):
                        with patch.object(self.replay_stack_manager, "_open_browser") as open_browser:
                            self.replay_stack_manager.start_standard_replay_stack(ctx)

        allow_failure.assert_called_once_with(["xhost", "+local:docker"])
        copy_file.assert_called_once()
        self.assertEqual(run_detached_command.call_count, 2)
        standard_stack_cmd = run_detached_command.call_args_list[0].args[0][6]
        self.assertIn("MDRIVE_VEHICLE_MODEL", standard_stack_cmd)
        self.assertIn("MDRIVE_VEHICLE_NAME", standard_stack_cmd)
        self.assertIn("/mdrive/vmc.sh", standard_stack_cmd)
        open_browser.assert_called_once_with("http://localhost:8888")

    def test_start_traffic_light_stack_updates_local_config_and_dispatches_steps(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            mdrive_root = Path(tmpdir)
            traffic_light_config_path = (
                mdrive_root
                / "mdrive_conf"
                / "modules"
                / "perception_trafficlights"
                / "perception_traffic_light.pb.txt"
            )
            traffic_light_config_path.parent.mkdir(parents=True, exist_ok=True)
            traffic_light_config_path.write_text(
                "save_debug_img: false\n",
                encoding="utf-8",
            )
            ctx = cast(
                Any,
                SimpleNamespace(
                    docker=SimpleNamespace(container="demo_container"),
                    host=SimpleNamespace(mdrive_root=str(mdrive_root)),
                ),
            )

            with patch.object(self.replay_stack_manager, "_copy_file_to_container") as copy_file:
                with patch.object(self.replay_stack_manager, "_run_detached_command") as run_detached_command:
                    self.replay_stack_manager.start_traffic_light_stack(ctx)

            updated_config = traffic_light_config_path.read_text(encoding="utf-8")
            data_test_path = mdrive_root / "data" / "test"
            self.assertTrue(data_test_path.exists())

        copy_file.assert_called_once()
        run_detached_command.assert_called_once()
        self.assertIn("save_debug_img: true", updated_config)


if __name__ == "__main__":
    unittest.main()
