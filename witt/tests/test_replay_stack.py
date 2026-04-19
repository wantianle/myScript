import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

from core.engine import replay_stack


class ReplayStackTests(unittest.TestCase):
    def test_start_standard_replay_stack_dispatches_expected_steps(self) -> None:
        ctx = cast(
            Any,
            SimpleNamespace(
                docker=SimpleNamespace(container="demo_container"),
            ),
        )

        with patch("core.engine.replay_stack._allow_failure") as allow_failure:
            with patch("core.engine.replay_stack._copy_file_to_container") as copy_file:
                with patch("core.engine.replay_stack._run_detached_command") as run_detached_command:
                    with patch(
                        "core.engine.replay_stack._container_has_xauthority",
                        return_value=True,
                    ):
                        with patch("core.engine.replay_stack._open_browser") as open_browser:
                            replay_stack.start_standard_replay_stack(ctx)

        allow_failure.assert_called_once_with(["xhost", "+local:docker"])
        copy_file.assert_called_once()
        self.assertEqual(run_detached_command.call_count, 2)
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

            with patch("core.engine.replay_stack._copy_file_to_container") as copy_file:
                with patch("core.engine.replay_stack._run_detached_command") as run_detached_command:
                    replay_stack.start_traffic_light_stack(ctx)

            updated_config = traffic_light_config_path.read_text(encoding="utf-8")
            data_test_path = mdrive_root / "data" / "test"
            self.assertTrue(data_test_path.exists())

        copy_file.assert_called_once()
        run_detached_command.assert_called_once()
        self.assertIn("save_debug_img: true", updated_config)


if __name__ == "__main__":
    unittest.main()
