import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from core.session import AppSession, ensure_user_config_path


class SessionConfigTests(unittest.TestCase):
    def test_ensure_user_config_path_copies_default_template_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root_path = Path(tmpdir)
            template_path = root_path / "repo" / "config" / "settings.yaml"
            template_path.parent.mkdir(parents=True, exist_ok=True)
            template_path.write_text("logic:\n  vehicle: XZB600007\n", encoding="utf-8")

            user_config_path = ensure_user_config_path(
                template_path=template_path,
                user_home=root_path / "home",
            )
            self.assertEqual(user_config_path.name, "settings.yaml")
            self.assertEqual(user_config_path.parent.name, ".witt")
            self.assertEqual(
                user_config_path.read_text(encoding="utf-8"),
                "logic:\n  vehicle: XZB600007\n",
            )

    def test_ensure_user_config_path_keeps_existing_user_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root_path = Path(tmpdir)
            template_path = root_path / "repo" / "config" / "settings.yaml"
            template_path.parent.mkdir(parents=True, exist_ok=True)
            template_path.write_text("logic:\n  vehicle: XZB600007\n", encoding="utf-8")

            user_home = root_path / "home"
            existing_config_path = user_home / ".witt" / "settings.yaml"
            existing_config_path.parent.mkdir(parents=True, exist_ok=True)
            existing_config_path.write_text(
                "logic:\n  vehicle: XZT500001\n",
                encoding="utf-8",
            )

            user_config_path = ensure_user_config_path(
                template_path=template_path,
                user_home=user_home,
            )
            self.assertEqual(user_config_path, existing_config_path)
            self.assertEqual(
                user_config_path.read_text(encoding="utf-8"),
                "logic:\n  vehicle: XZT500001\n",
            )

    def test_app_session_exposes_runtime_entry(self) -> None:
        runtime = object()
        with patch("core.session.ensure_user_config_path", return_value=Path("/tmp/settings.yaml")):
            with patch("core.session.TaskContext", return_value=SimpleNamespace(work_dir=Path("/tmp/work"))):
                with patch("core.session.RuntimeCoordinator", return_value=runtime):
                    with patch("core.session.Recorder", return_value=object()):
                        with patch("core.session.MetadataRepository", return_value=object()):
                            with patch("core.session.LibraryCacheRepository", return_value=object()):
                                with patch("core.session.ReplayHistoryRepository", return_value=object()):
                                    with patch("core.session.RecordDownloader", return_value=object()):
                                        with patch("core.session.RecordPlayer", return_value=object()):
                                            session = AppSession()

        self.assertIs(session.runtime, runtime)


if __name__ == "__main__":
    unittest.main()
