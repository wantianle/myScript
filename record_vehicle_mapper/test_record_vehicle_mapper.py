#!/usr/bin/env python3

import json
import re
import tempfile
import unittest
from pathlib import Path

import record_vehicle_mapper as mapper


class RecordVehicleMapperTest(unittest.TestCase):
    def test_build_report_with_matched_missing_and_ambiguous_records(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            case_root = tmp_path / "cases"
            raw_root = tmp_path / "raw"
            road_test_root = tmp_path / "road_test"

            case_soc2 = case_root / "case_a" / "soc2"
            case_soc2.mkdir(parents=True)
            matched_case = case_soc2 / "20260517140727.record.00000.141028"
            missing_case = case_soc2 / "20260517140728.record.00000.141029"
            ambiguous_case = case_soc2 / "20260518140729.record.00000.141030"
            road_test_case = case_soc2 / "20260228140727.record.00003.141028"
            split_case = case_soc2 / "20260519140729.record.00000.141030.split"
            next_day_case = case_soc2 / "20260510235959.record.00000.235959"
            same_day_priority_case = (
                case_soc2 / "20260513120000.record.00000.120001"
            )
            matched_case.touch()
            missing_case.touch()
            ambiguous_case.touch()
            road_test_case.touch()
            split_case.touch()
            next_day_case.touch()
            same_day_priority_case.touch()
            (case_soc2 / "20260519140729.record.00000.141030.tmp").touch()
            (case_soc2 / "20260519140729.record.00000.141030.split.tmp").touch()
            (case_soc2 / "prefix20260519140729.record.00000.141030").touch()
            (case_soc2 / "20260519140729.record.00000.141030.dir").mkdir()
            (case_soc2 / "20260520140729.record.00000.141030").mkdir()

            excluded_soc2 = case_root / "odom数据包" / "soc2"
            excluded_soc2.mkdir(parents=True)
            (excluded_soc2 / "20260517140731.record.00000.141032").touch()

            ignored_soc1 = case_root / "case_a" / "soc1"
            ignored_soc1.mkdir(parents=True)
            (ignored_soc1 / "20260517140730.record.00000.141031").touch()

            matched_raw_dir = raw_root / "20260517" / "XZB600013" / "bag_a"
            matched_raw_dir.mkdir(parents=True)
            (matched_raw_dir / matched_case.name).touch()
            (matched_raw_dir / "version.json").write_text(
                json.dumps(
                    {
                        "other": "ignore me",
                        "conf": "foo bar",
                        "mdrive_conf": "feature/mdrive_conf_test",
                    }
                ),
                encoding="utf-8",
            )

            ambiguous_raw_dir_a = raw_root / "20260517" / "XZB600014" / "bag_b"
            ambiguous_raw_dir_b = raw_root / "20260518" / "XZB600015" / "bag_c"
            ambiguous_raw_dir_c = raw_root / "20260518" / "XZB600016" / "bag_d"
            road_test_duplicate_dir = (
                road_test_root / "XZB600018" / "2026" / "duplicate"
            )
            ambiguous_raw_dir_a.mkdir(parents=True)
            ambiguous_raw_dir_b.mkdir(parents=True)
            ambiguous_raw_dir_c.mkdir(parents=True)
            road_test_duplicate_dir.mkdir(parents=True)
            (ambiguous_raw_dir_a / ambiguous_case.name).touch()
            (ambiguous_raw_dir_b / ambiguous_case.name).touch()
            (ambiguous_raw_dir_c / ambiguous_case.name).touch()
            (road_test_duplicate_dir / matched_case.name).touch()
            (ambiguous_raw_dir_a / "version.txt").write_text(
                "vehicle-build-a", encoding="utf-8"
            )

            road_test_raw_dir = road_test_root / "XZB600017" / "2026" / "run_a"
            road_test_raw_dir.mkdir(parents=True)
            (road_test_raw_dir / road_test_case.name).touch()
            (road_test_raw_dir / "version.txt").write_text(
                "abc def\nmdrive_conf release/road_test_conf 20260228\n",
                encoding="utf-8",
            )

            split_raw_dir = raw_root / "20260519" / "XZB600019" / "bag_split"
            split_raw_dir.mkdir(parents=True)
            (split_raw_dir / split_case.name).touch()
            (split_raw_dir / "version.txt").write_text(
                "mdrive_conf split_branch", encoding="utf-8"
            )

            next_day_raw_dir = raw_root / "20260511" / "XZB600020" / "bag_next_day"
            next_day_raw_dir.mkdir(parents=True)
            (next_day_raw_dir / next_day_case.name).touch()
            (next_day_raw_dir / "version.txt").write_text(
                "mdrive_conf next_day_branch", encoding="utf-8"
            )

            next_day_road_test_dir = road_test_root / "XZB600021" / "2026" / "fallback"
            next_day_road_test_dir.mkdir(parents=True)
            (next_day_road_test_dir / next_day_case.name).touch()

            same_day_priority_dir = raw_root / "20260513" / "XZB600022" / "same_day"
            next_day_duplicate_dir = raw_root / "20260514" / "XZB600023" / "next_day"
            same_day_priority_dir.mkdir(parents=True)
            next_day_duplicate_dir.mkdir(parents=True)
            (same_day_priority_dir / same_day_priority_case.name).touch()
            (next_day_duplicate_dir / same_day_priority_case.name).touch()
            (same_day_priority_dir / "version.txt").write_text(
                "mdrive_conf same_day_branch", encoding="utf-8"
            )

            scan_errors = []
            record_re = re.compile(mapper.DEFAULT_RECORD_REGEX)
            case_records = mapper.scan_case_records(
                case_root,
                "soc2",
                record_re,
                False,
                scan_errors,
                {"odom数据包"},
            )
            target_names_by_date, undated_names = mapper.group_record_names_by_date(
                {path.name for path in case_records}
            )
            raw_index_same_day = mapper.scan_raw_records(
                raw_root, target_names_by_date, False, scan_errors
            )
            next_day_targets_by_record_date = mapper.filter_unmatched_records_by_date(
                target_names_by_date, raw_index_same_day
            )
            next_day_targets_by_search_date = mapper.shift_record_names_to_next_day(
                next_day_targets_by_record_date
            )
            raw_index_next_day = mapper.scan_raw_records(
                raw_root, next_day_targets_by_search_date, False, scan_errors
            )
            raw_index = mapper.merge_raw_indexes(
                raw_index_same_day, raw_index_next_day
            )
            road_test_targets_by_date = mapper.filter_unmatched_records_by_date(
                target_names_by_date, raw_index
            )
            road_test_index = mapper.scan_road_test_records(
                road_test_root, road_test_targets_by_date, False, scan_errors
            )
            merged_index = mapper.merge_raw_indexes(raw_index, road_test_index)
            report = mapper.build_report(
                case_root,
                raw_root,
                road_test_root,
                "soc2",
                mapper.DEFAULT_RECORD_REGEX,
                case_records,
                merged_index,
                list(mapper.DEFAULT_VERSION_FILENAMES),
                True,
                scan_errors,
                sorted(set(target_names_by_date) | set(next_day_targets_by_search_date)),
                len(undated_names),
                ["odom数据包"],
            )

            self.assertEqual(report["summary"]["case_record_count"], 7)
            self.assertEqual(report["exclude_dirs"], ["odom数据包"])
            self.assertEqual(report["summary"]["matched_count"], 5)
            self.assertEqual(report["summary"]["raw_not_found_count"], 1)
            self.assertEqual(report["summary"]["ambiguous_count"], 1)
            self.assertEqual(report["summary"]["raw_search_date_count"], 8)
            self.assertEqual(report["summary"]["undated_record_count"], 0)

            self.assertNotIn("records", report)
            matched = report["vehicles"]["XZB600013"][0]
            self.assertEqual(matched["match_status"], "matched")
            self.assertEqual(matched["case_record_path"], str(matched_case.absolute()))
            self.assertEqual(
                matched["raw_record_path"],
                str((matched_raw_dir / matched_case.name).absolute()),
            )
            self.assertEqual(
                matched["version_info"],
                {
                    "pakage": "mdrive_conf",
                    "version": "feature/mdrive_conf_test",
                },
            )

            self.assertEqual(
                report["NotFound"], [{"case_record_path": str(missing_case.absolute())}]
            )

            self.assertEqual(
                report["vehicles"]["XZB600015"][0]["match_status"], "ambiguous"
            )
            self.assertEqual(
                report["vehicles"]["XZB600016"][0]["match_status"], "ambiguous"
            )

            road_test = report["vehicles"]["XZB600017"][0]
            self.assertEqual(road_test["match_status"], "matched")
            self.assertEqual(
                road_test["version_info"],
                {
                    "pakage": "mdrive_conf",
                    "branch": "20260228",
                    "version": "release/road_test_conf",
                },
            )

            split = report["vehicles"]["XZB600019"][0]
            self.assertEqual(split["match_status"], "matched")
            next_day = report["vehicles"]["XZB600020"][0]
            self.assertEqual(next_day["match_status"], "matched")
            self.assertEqual(
                next_day["raw_record_path"],
                str((next_day_raw_dir / next_day_case.name).absolute()),
            )
            same_day_priority = report["vehicles"]["XZB600022"][0]
            self.assertEqual(same_day_priority["match_status"], "matched")
            self.assertEqual(
                same_day_priority["raw_record_path"],
                str((same_day_priority_dir / same_day_priority_case.name).absolute()),
            )
            self.assertNotIn("XZB600023", report["vehicles"])
            vehicle_entries_text = json.dumps(report["vehicles"], ensure_ascii=False)
            self.assertNotIn("20260519140729.record.00000.141030.tmp", vehicle_entries_text)
            self.assertNotIn(
                "20260519140729.record.00000.141030.split.tmp", vehicle_entries_text
            )
            self.assertNotIn(
                "prefix20260519140729.record.00000.141030", vehicle_entries_text
            )

    def test_parse_mdrive_conf_info_from_common_formats(self):
        self.assertEqual(
            mapper.parse_mdrive_conf_info("mdrive_conf branch_a extra_a"),
            {"pakage": "mdrive_conf", "branch": "extra_a", "version": "branch_a"},
        )
        self.assertEqual(
            mapper.parse_mdrive_conf_info(
                json.dumps({"mdrive_conf": "branch_b"})
            ),
            {"pakage": "mdrive_conf", "version": "branch_b"},
        )
        self.assertEqual(
            mapper.parse_mdrive_conf_info(
                json.dumps({"mdrive_conf branch_c extra_c": ""})
            ),
            {"pakage": "mdrive_conf", "branch": "extra_c", "version": "branch_c"},
        )

    def test_next_date_text_handles_month_boundary(self):
        self.assertEqual(mapper.next_date_text("20260228"), "20260301")
        self.assertEqual(mapper.next_date_text("20261231"), "20270101")


if __name__ == "__main__":
    unittest.main()
