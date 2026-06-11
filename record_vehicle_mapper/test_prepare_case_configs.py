#!/usr/bin/env python3

import json
import subprocess
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest import mock

import prepare_case_configs as prep


class PrepareCaseConfigsTest(unittest.TestCase):
    def test_parse_branch_info_uses_branch_as_git_branch_and_version_hash_as_ref(self):
        info = prep.parse_branch_info(
            {
                "pakage": "mdrive_conf",
                "branch": "release_branch",
                "version": "ECAR_HW4.4.3.1.master_T5_30e1c650_xxx",
            }
        )

        self.assertEqual(info.platform, "ECAR_HW4")
        self.assertEqual(info.git_branch, "release_branch")
        self.assertEqual(info.commit_hash, "30e1c650")
        self.assertEqual(info.git_ref, "30e1c650")

    def test_parse_branch_info_falls_back_to_head_when_hash_missing(self):
        info = prep.parse_branch_info(
            {
                "pakage": "mdrive_conf",
                "branch": "master_T5",
                "version": "ECAR_HW4.4.3.1.master_T5_without_hash",
            }
        )

        self.assertEqual(info.platform, "ECAR_HW4")
        self.assertEqual(info.git_branch, "master_T5")
        self.assertIsNone(info.commit_hash)
        self.assertEqual(info.git_ref, "HEAD")

    def test_parse_branch_info_without_branch_uses_tail_before_hash(self):
        info = prep.parse_branch_info(
            {
                "pakage": "mdrive_conf",
                "version": "ECAR_HW4.4.3.1.release_260310_cca98d38",
            }
        )

        self.assertEqual(info.platform, "ECAR_HW4")
        self.assertEqual(info.git_branch, "release_260310")
        self.assertEqual(info.commit_hash, "cca98d38")
        self.assertEqual(info.git_ref, "cca98d38")

    def test_parse_branch_info_without_branch_and_hash_uses_full_tail(self):
        xinzhou = prep.parse_branch_info(
            {
                "pakage": "mdrive_conf",
                "version": "ECAR_HW4.1.4.2.xinzhou_1230",
            }
        )
        meilin = prep.parse_branch_info(
            {
                "pakage": "mdrive_conf",
                "version": "ECAR_HW4.1.3.18.meilin_1122_conf",
            }
        )

        self.assertEqual(xinzhou.git_branch, "xinzhou_1230")
        self.assertEqual(xinzhou.git_ref, "HEAD")
        self.assertIsNone(xinzhou.commit_hash)
        self.assertEqual(meilin.git_branch, "meilin_1122_conf")
        self.assertEqual(meilin.git_ref, "HEAD")
        self.assertIsNone(meilin.commit_hash)

    def test_extract_vehicle_from_known_path_shapes(self):
        self.assertEqual(
            prep.extract_vehicle_from_version_path(
                Path("/media/nas/00.raw/20260517/XZT500032/run/version.txt"),
                "FALLBACK",
            ),
            "XZT500032",
        )
        self.assertEqual(
            prep.extract_vehicle_from_version_path(
                Path("/media/nas/01.load_test/foo/bar/XZB600013/run/version.json"),
                "FALLBACK",
            ),
            "XZB600013",
        )
        self.assertEqual(
            prep.extract_vehicle_from_version_path(
                Path("/media/nas/04.mdrive3/01.road_test/XZT5000032/2026/run/version.txt"),
                "FALLBACK",
            ),
            "XZT5000032",
        )
        self.assertEqual(
            prep.extract_vehicle_from_version_path(
                Path("/unknown/path/version.txt"),
                "XZB600999",
            ),
            "XZB600999",
        )

    def test_build_tasks_from_vehicle_grouped_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            case_record = tmp_path / "case" / "soc2" / "20260517140727.record.00000.141028"
            version_file = (
                tmp_path
                / "media"
                / "nas"
                / "01.load_test"
                / "bags"
                / "XZT500032"
                / "version.txt"
            )
            case_record.parent.mkdir(parents=True)
            version_file.parent.mkdir(parents=True)
            case_record.touch()
            version_file.write_text("version", encoding="utf-8")
            payload = {
                "vehicles": {
                    "XZB600013": [
                        {
                            "case_record_path": str(case_record),
                            "raw_record_path": str(version_file.parent / "x.record"),
                            "version_path": str(version_file),
                            "version_info": {
                                "pakage": "mdrive_conf",
                                "branch": "master_T5",
                                "version": "ECAR_HW4.4.3.1.any_30e1c650_tail",
                            },
                            "match_status": "matched",
                        }
                    ]
                }
            }

            tasks, errors = prep.build_tasks(payload, prep.DEFAULT_VEHICLE_CONFIG_NAME)

            self.assertEqual(errors, [])
            self.assertEqual(len(tasks), 1)
            task = tasks[0]
            self.assertEqual(task.version_vehicle, "XZT500032")
            self.assertEqual(
                task.repo_config_path,
                "ECAR_HW4/vehicle_name/XZT500032/vehicle_config.pb.txt",
            )
            self.assertEqual(task.config_dir, Path(str(case_record) + ".config"))

    def test_build_tasks_accepts_missing_branch_when_version_tail_is_parseable(self):
        payload = {
            "vehicles": {
                "XZB600013": [
                    {
                        "case_record_path": "/case.record",
                        "version_path": "/version.txt",
                        "version_info": {
                            "pakage": "mdrive_conf",
                            "version": "ECAR_HW4.4.3.1.any_30e1c650_tail",
                        },
                    }
                ]
            }
        }

        tasks, errors = prep.build_tasks(payload, prep.DEFAULT_VEHICLE_CONFIG_NAME)

        self.assertEqual(errors, [])
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].branch_info.git_branch, "any")
        self.assertEqual(tasks[0].branch_info.git_ref, "30e1c650")

    def test_run_git_switch_raises_context_error_on_failure(self):
        error = subprocess.CalledProcessError(
            returncode=1,
            cmd=["git", "switch", "missing_branch"],
            stderr="fatal: invalid reference: missing_branch",
        )

        with mock.patch("prepare_case_configs.subprocess.run", side_effect=error):
            with self.assertRaises(prep.GitSwitchError) as ctx:
                prep.run_git_switch(Path("/repo"), "missing_branch")

        self.assertEqual(ctx.exception.repo, Path("/repo"))
        self.assertEqual(ctx.exception.branch, "missing_branch")
        self.assertIn("invalid reference", ctx.exception.stderr)

    def test_copy_and_write_always_overwrite_existing_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            src = tmp_path / "src.txt"
            dst = tmp_path / "dst.txt"
            src.write_text("new-version", encoding="utf-8")
            dst.write_text("old-version", encoding="utf-8")

            self.assertEqual(prep.copy_file(src, dst), "copied")
            self.assertEqual(dst.read_text(encoding="utf-8"), "new-version")

            self.assertEqual(prep.write_bytes(dst, b"new-config"), "written")
            self.assertEqual(dst.read_bytes(), b"new-config")

    def test_print_failures_includes_stage_case_vehicle_branch_and_error(self):
        failure = prep.Failure(
            stage="execute",
            case_record_path="/case.record",
            vehicle="XZT500032",
            branch="master_T5",
            ref="30e1c650",
            error="missing vehicle_config.pb.txt",
        )
        stderr = StringIO()

        with mock.patch("prepare_case_configs.sys.stderr", stderr):
            prep.print_failures([failure])

        output = stderr.getvalue()
        self.assertIn("stage=execute", output)
        self.assertIn("/case.record", output)
        self.assertIn("XZT500032", output)
        self.assertIn("master_T5", output)
        self.assertIn("30e1c650", output)
        self.assertIn("missing vehicle_config.pb.txt", output)


if __name__ == "__main__":
    unittest.main()
