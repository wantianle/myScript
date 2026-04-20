import tempfile
import unittest
from pathlib import Path

from core.engine import runtime_env
from core.errors import RuntimeEnvironmentError


class RuntimeEnvTests(unittest.TestCase):
    def test_load_version_info_supports_json_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            version_path = Path(tmpdir) / "version.json"
            version_path.write_text(
                (
                    "{"
                    '"mdrive":"1.2.3",'
                    '"mdrive_conf":"E171.2.3",'
                    '"mdrive_model":"4.5.6",'
                    '"mdrive_map":"7.8.9",'
                    '"mdrive_map_localization":"10.11.12"'
                    "}"
                ),
                encoding="utf-8",
            )

            version_info = runtime_env.load_version_info(version_path)

        self.assertEqual(version_info.mdrive_ver, "1.2.3")
        self.assertEqual(version_info.conf_ver, "E171.2.3")
        self.assertEqual(version_info.model_ver, "4.5.6")
        self.assertEqual(version_info.map_ver, "7.8.9")
        self.assertEqual(version_info.localization_ver, "10.11.12")
        self.assertEqual(version_info.vehicle_model, "E171")

    def test_load_version_info_supports_txt_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            version_path = Path(tmpdir) / "version.txt"
            version_path.write_text(
                "\n".join(
                    [
                        "mdrive 1.2.3",
                        "mdrive_conf E171.2.3",
                        "mdrive_model 4.5.6",
                        "mdrive_map 7.8.9",
                        "mdrive_map_localization 10.11.12",
                    ]
                ),
                encoding="utf-8",
            )

            version_info = runtime_env.load_version_info(version_path)

        self.assertEqual(version_info.mdrive_ver, "1.2.3")
        self.assertEqual(version_info.conf_ver, "E171.2.3")
        self.assertEqual(version_info.vehicle_model, "E171")

    def test_load_version_info_raises_when_required_fields_are_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            version_path = Path(tmpdir) / "version.json"
            version_path.write_text(
                '{"mdrive":"","mdrive_conf":""}',
                encoding="utf-8",
            )

            with self.assertRaises(RuntimeEnvironmentError):
                runtime_env.load_version_info(version_path)

    def test_sync_runtime_environment_updates_vmc_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            vmc_path = Path(tmpdir) / "vmc.sh"
            vmc_path.write_text(
                "\n".join(
                    [
                        'MDRIVE_VEHICLE_MODEL="OLD"',
                        'MDRIVE_VEHICLE_NAME="OLD_CAR"',
                        "MDRIVE_VERSION=old",
                        "MDRIVE_CONF_VERSION=old_conf",
                        "MDRIVE_MODEL_VERSION=old_model",
                        "MDRIVE_MAP_VERSION=old_map",
                    ]
                ),
                encoding="utf-8",
            )

            version_info = runtime_env.RuntimeVersionInfo(
                mdrive_ver="1.2.3",
                conf_ver="E171.2.3",
                model_ver="4.5.6",
                map_ver="7.8.9",
                localization_ver="10.11.12",
                vehicle_model="E171",
            )

            changed = runtime_env.sync_runtime_environment(
                vmc_path,
                version_info,
                vehicle_name="XZB600001",
            )

            vmc_text = vmc_path.read_text(encoding="utf-8")

        self.assertTrue(changed)
        self.assertIn('MDRIVE_VEHICLE_MODEL="E171"', vmc_text)
        self.assertIn('MDRIVE_VEHICLE_NAME="XZB600001"', vmc_text)
        self.assertIn("MDRIVE_VERSION=1.2.3", vmc_text)
        self.assertIn("MDRIVE_CONF_VERSION=E171.2.3", vmc_text)
        self.assertIn("MDRIVE_MODEL_VERSION=4.5.6", vmc_text)
        self.assertIn("MDRIVE_MAP_VERSION=7.8.9", vmc_text)

    def test_sync_runtime_environment_returns_false_when_vmc_is_already_aligned(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            vmc_path = Path(tmpdir) / "vmc.sh"
            vmc_path.write_text(
                "\n".join(
                    [
                        'MDRIVE_VEHICLE_MODEL="E171"',
                        'MDRIVE_VEHICLE_NAME="XZB600001"',
                        "MDRIVE_VERSION=1.2.3",
                        "MDRIVE_CONF_VERSION=E171.2.3",
                        "MDRIVE_MODEL_VERSION=4.5.6",
                        "MDRIVE_MAP_VERSION=7.8.9",
                    ]
                ),
                encoding="utf-8",
            )

            version_info = runtime_env.RuntimeVersionInfo(
                mdrive_ver="1.2.3",
                conf_ver="E171.2.3",
                model_ver="4.5.6",
                map_ver="7.8.9",
                localization_ver="10.11.12",
                vehicle_model="E171",
            )

            changed = runtime_env.sync_runtime_environment(
                vmc_path,
                version_info,
                vehicle_name="XZB600001",
            )

        self.assertFalse(changed)


if __name__ == "__main__":
    unittest.main()
