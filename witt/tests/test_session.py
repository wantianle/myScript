import tempfile
import unittest
from pathlib import Path

from core.session import ensure_user_config_path


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


if __name__ == "__main__":
    unittest.main()
