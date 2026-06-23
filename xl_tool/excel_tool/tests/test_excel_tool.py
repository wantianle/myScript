import io
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock
from xml.sax.saxutils import escape

from excel_tool import ReplaceAction, ReplaceCondition, ReplaceRule, SimpleWorkbook, copy_matching_fields, run_cli


def column_index_to_letter(index):
    chars = []
    current = index
    while current:
        current, remainder = divmod(current - 1, 26)
        chars.append(chr(65 + remainder))
    return "".join(reversed(chars))


def build_sheet_xml(rows, string_index):
    max_row = len(rows)
    max_col = max((len(row) for row in rows), default=1)
    dimension = "A1" if max_row <= 1 and max_col <= 1 else "A1:%s%d" % (column_index_to_letter(max_col), max_row)
    row_parts = []
    for row_idx, row in enumerate(rows, start=1):
        cell_parts = []
        for col_idx, value in enumerate(row, start=1):
            if value is None or value == "":
                continue
            ref = "%s%d" % (column_index_to_letter(col_idx), row_idx)
            if isinstance(value, (int, float)):
                cell_parts.append('<c r="%s"><v>%s</v></c>' % (ref, value))
            else:
                cell_parts.append('<c r="%s" t="s"><v>%s</v></c>' % (ref, string_index[value]))
        row_parts.append('<row r="%d">%s</row>' % (row_idx, "".join(cell_parts)))
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<dimension ref="%s"/>'
        '<sheetData>%s</sheetData>'
        '</worksheet>'
    ) % (dimension, "".join(row_parts))


def build_shared_strings(strings):
    items = "".join("<si><t>%s</t></si>" % escape(value) for value in strings)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'count="{count}" uniqueCount="{count}">{items}</sst>'
    ).format(count=len(strings), items=items)


def write_workbook(path, sheets):
    unique_strings = []
    seen = set()
    for _, rows in sheets:
        for row in rows:
            for value in row:
                if isinstance(value, str) and value not in seen and value != "":
                    unique_strings.append(value)
                    seen.add(value)
    string_index = {value: idx for idx, value in enumerate(unique_strings)}
    sheet_entries = []
    for idx, (name, rows) in enumerate(sheets, start=1):
        sheet_entries.append((idx, name, build_sheet_xml(rows, string_index)))
    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets>{sheets}</sheets></workbook>'
    ).format(
        sheets="".join(
            '<sheet name="{name}" sheetId="{sheet_id}" r:id="rId{sheet_id}"/>'.format(
                name=escape(name),
                sheet_id=sheet_id,
            )
            for sheet_id, name, _ in sheet_entries
        )
    )
    rels_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '{rels}</Relationships>'
    ).format(
        rels="".join(
            '<Relationship Id="rId{sheet_id}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            'Target="worksheets/sheet{sheet_id}.xml"/>'.format(sheet_id=sheet_id)
            for sheet_id, _, _ in sheet_entries
        )
    )
    content_types_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '{overrides}'
        '<Override PartName="/xl/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        '<Override PartName="/xl/sharedStrings.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
        '</Types>'
    ).format(
        overrides="".join(
            '<Override PartName="/xl/worksheets/sheet{sheet_id}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'.format(
                sheet_id=sheet_id
            )
            for sheet_id, _, _ in sheet_entries
        )
    )
    root_rels_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/>'
        '</Relationships>'
    )
    styles_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>'
        '<fills count="1"><fill><patternFill patternType="none"/></fill></fills>'
        '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs>'
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
        '</styleSheet>'
    )
    with zipfile.ZipFile(path, "w") as workbook:
        workbook.writestr("[Content_Types].xml", content_types_xml)
        workbook.writestr("_rels/.rels", root_rels_xml)
        workbook.writestr("xl/workbook.xml", workbook_xml)
        workbook.writestr("xl/_rels/workbook.xml.rels", rels_xml)
        workbook.writestr("xl/styles.xml", styles_xml)
        workbook.writestr("xl/sharedStrings.xml", build_shared_strings(unique_strings))
        for sheet_id, _, sheet_xml in sheet_entries:
            workbook.writestr("xl/worksheets/sheet%d.xml" % sheet_id, sheet_xml)


class ExcelToolTest(unittest.TestCase):
    def test_copy_matching_fields_copies_same_row_values(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source = temp_path / "source.xlsx"
            target = temp_path / "target.xlsx"
            output = temp_path / "output.xlsx"
            write_workbook(
                source,
                [
                    (
                        "数据",
                        [
                            ["项目选择", "项目编码", "项目名称", "项目经理.姓名"],
                            ["P1", "C1", "N1", "张三"],
                            ["P2", "C2", "N2", "李四"],
                        ],
                    )
                ],
            )
            write_workbook(
                target,
                [
                    (
                        "模板",
                        [
                            ["项目编码", "项目名称", "项目经理.姓名", "缺失列"],
                        ],
                    )
                ],
            )
            summary = copy_matching_fields(source, target, output)
            self.assertEqual(summary.copied_rows, 2)
            self.assertEqual(summary.missing_headers, ["缺失列"])
            workbook = SimpleWorkbook(output)
            sheet = workbook.sheet()
            self.assertEqual(sheet.row_values(2)[:4], ["C1", "N1", "张三", ""])
            self.assertEqual(sheet.row_values(3)[:4], ["C2", "N2", "李四", ""])

    def test_copy_matching_fields_can_replace_target_column(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source = temp_path / "source.xlsx"
            target = temp_path / "target.xlsx"
            output = temp_path / "output.xlsx"
            write_workbook(
                source,
                [
                    (
                        "数据",
                        [
                            ["姓名", "部门"],
                            ["a", "原部门1"],
                            ["b", "原部门2"],
                            ["a", "原部门3"],
                        ],
                    )
                ],
            )
            write_workbook(
                target,
                [
                    (
                        "模板",
                        [
                            ["姓名", "部门"],
                        ],
                    )
                ],
            )
            summary = copy_matching_fields(
                source_path=source,
                target_path=target,
                output_path=output,
                where_column="姓名",
                equals_value="a",
                set_column="部门",
                set_value="待确认",
            )
            self.assertIsNotNone(summary.replace_summary)
            self.assertEqual(summary.replace_summary.matched_rows, 2)
            workbook = SimpleWorkbook(output)
            sheet = workbook.sheet()
            self.assertEqual(sheet.row_values(2)[:2], ["a", "待确认"])
            self.assertEqual(sheet.row_values(3)[:2], ["b", "原部门2"])
            self.assertEqual(sheet.row_values(4)[:2], ["a", "待确认"])

    def test_copy_matching_fields_can_replace_in_same_run(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source = temp_path / "source.xlsx"
            target = temp_path / "target.xlsx"
            output = temp_path / "output.xlsx"
            write_workbook(
                source,
                [
                    (
                        "数据",
                        [
                            ["项目编码", "项目经理.姓名", "应集约", "实际集约"],
                            ["C1", "张三", "是", "是"],
                            ["C2", "李四", "否", "否"],
                        ],
                    )
                ],
            )
            write_workbook(
                target,
                [
                    (
                        "模板",
                        [
                            ["项目编码", "项目经理.姓名", "应集约", "实际集约"],
                        ],
                    )
                ],
            )
            summary = copy_matching_fields(
                source_path=source,
                target_path=target,
                output_path=output,
                where_column="应集约",
                equals_value="是",
                set_column="实际集约",
                set_value="否",
            )
            self.assertIsNotNone(summary.replace_summary)
            self.assertEqual(summary.replace_summary.matched_rows, 1)
            workbook = SimpleWorkbook(output)
            sheet = workbook.sheet()
            self.assertEqual(sheet.row_values(2)[:4], ["C1", "张三", "是", "否"])
            self.assertEqual(sheet.row_values(3)[:4], ["C2", "李四", "否", "否"])

    def test_copy_matching_fields_can_apply_multiple_rules(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source = temp_path / "source.xlsx"
            target = temp_path / "target.xlsx"
            output = temp_path / "output.xlsx"
            write_workbook(
                source,
                [
                    (
                        "数据",
                        [
                            ["姓名", "部门", "状态"],
                            ["a", "原部门1", "启用"],
                            ["b", "原部门2", "停用"],
                            ["a", "原部门3", "停用"],
                        ],
                    )
                ],
            )
            write_workbook(
                target,
                [
                    (
                        "模板",
                        [
                            ["姓名", "部门", "状态"],
                        ],
                    )
                ],
            )
            summary = copy_matching_fields(
                source_path=source,
                target_path=target,
                output_path=output,
                replace_rules=[
                    ReplaceRule.simple(where_column="姓名", equals_value="a", set_column="部门", set_value="待确认"),
                    ReplaceRule.simple(where_column="状态", equals_value="停用", set_column="姓名", set_value="离职"),
                ],
            )
            self.assertEqual(len(summary.replace_summaries), 2)
            self.assertEqual(summary.replace_summaries[0].matched_rows, 2)
            self.assertEqual(summary.replace_summaries[1].matched_rows, 2)
            workbook = SimpleWorkbook(output)
            sheet = workbook.sheet()
            self.assertEqual(sheet.row_values(2)[:3], ["a", "待确认", "启用"])
            self.assertEqual(sheet.row_values(3)[:3], ["离职", "原部门2", "停用"])
            self.assertEqual(sheet.row_values(4)[:3], ["离职", "待确认", "停用"])

    def test_copy_matching_fields_can_match_multiple_conditions_and_update_multiple_columns(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source = temp_path / "source.xlsx"
            target = temp_path / "target.xlsx"
            output = temp_path / "output.xlsx"
            write_workbook(
                source,
                [
                    (
                        "数据",
                        [
                            ["地区", "客服专员", "客服专员工号", "项目名"],
                            ["广东", "林琳", "111111", "项目A"],
                            ["广东", "张三", "222222", "项目B"],
                            ["广东", "林琳", "333333", "项目C"],
                            ["广西", "林琳", "444444", "项目D"],
                        ],
                    )
                ],
            )
            write_workbook(
                target,
                [
                    (
                        "模板",
                        [
                            ["地区", "客服专员", "客服专员工号", "项目名"],
                        ],
                    )
                ],
            )
            summary = copy_matching_fields(
                source_path=source,
                target_path=target,
                output_path=output,
                replace_rules=[
                    ReplaceRule(
                        conditions=[
                            ReplaceCondition(column="地区", equals_value="广东"),
                            ReplaceCondition(column="客服专员", equals_value="林琳"),
                        ],
                        updates=[
                            ReplaceAction(column="客服专员", value="李晓莹"),
                            ReplaceAction(column="客服专员工号", value="123456"),
                        ],
                    )
                ],
            )
            self.assertEqual(len(summary.replace_summaries), 1)
            self.assertEqual(summary.replace_summaries[0].matched_rows, 2)
            workbook = SimpleWorkbook(output)
            sheet = workbook.sheet()
            self.assertEqual(sheet.row_values(2)[:4], ["广东", "李晓莹", "123456", "项目A"])
            self.assertEqual(sheet.row_values(3)[:4], ["广东", "张三", "222222", "项目B"])
            self.assertEqual(sheet.row_values(4)[:4], ["广东", "李晓莹", "123456", "项目C"])
            self.assertEqual(sheet.row_values(5)[:4], ["广西", "林琳", "444444", "项目D"])

    def test_copy_matching_fields_can_show_progress(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source = temp_path / "source.xlsx"
            target = temp_path / "target.xlsx"
            output = temp_path / "output.xlsx"
            source_rows = [["姓名", "部门"]]
            for index in range(1, 31):
                source_rows.append(["姓名%d" % index, "部门%d" % index])
            write_workbook(source, [("数据", source_rows)])
            write_workbook(target, [("模板", [["姓名", "部门"]])])
            stream = io.StringIO()
            with redirect_stdout(stream):
                summary = copy_matching_fields(
                    source_path=source,
                    target_path=target,
                    output_path=output,
                    show_progress=True,
                )
            self.assertEqual(summary.copied_rows, 30)
            output_text = stream.getvalue()
            self.assertIn("复制进度", output_text)
            self.assertIn("正在写出结果文件", output_text)
            self.assertIn("结果文件写出完成", output_text)

    def test_run_cli_supports_multiple_rule_args(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source = temp_path / "source.xlsx"
            target = temp_path / "target.xlsx"
            output = temp_path / "out.xlsx"
            write_workbook(
                source,
                [
                    (
                        "数据",
                        [
                            ["姓名", "部门", "状态"],
                            ["a", "原部门1", "启用"],
                            ["b", "原部门2", "停用"],
                        ],
                    )
                ],
            )
            write_workbook(
                target,
                [
                    (
                        "模板",
                        [
                            ["姓名", "部门", "状态"],
                        ],
                    )
                ],
            )
            exit_code = run_cli(
                [
                    str(source),
                    str(target),
                    "-o",
                    str(output),
                    "-r",
                    "姓名|a|部门|待确认",
                    "-r",
                    "状态|停用|姓名|离职",
                ]
            )
            self.assertEqual(exit_code, 0)
            workbook = SimpleWorkbook(output)
            sheet = workbook.sheet()
            self.assertEqual(sheet.row_values(2)[:3], ["a", "待确认", "启用"])
            self.assertEqual(sheet.row_values(3)[:3], ["离职", "原部门2", "停用"])

    def test_run_cli_supports_advanced_rule_expression(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source = temp_path / "source.xlsx"
            target = temp_path / "target.xlsx"
            output = temp_path / "out.xlsx"
            write_workbook(
                source,
                [
                    (
                        "数据",
                        [
                            ["地区", "客服专员", "客服专员工号", "项目名"],
                            ["广东", "林琳", "111111", "项目A"],
                            ["广东", "张三", "222222", "项目B"],
                            ["广东", "林琳", "333333", "项目C"],
                        ],
                    )
                ],
            )
            write_workbook(
                target,
                [
                    (
                        "模板",
                        [
                            ["地区", "客服专员", "客服专员工号", "项目名"],
                        ],
                    )
                ],
            )
            exit_code = run_cli(
                [
                    str(source),
                    str(target),
                    "-o",
                    str(output),
                    "-r",
                    "地区=广东&客服专员=林琳=>客服专员=李晓莹&客服专员工号=123456",
                ]
            )
            self.assertEqual(exit_code, 0)
            workbook = SimpleWorkbook(output)
            sheet = workbook.sheet()
            self.assertEqual(sheet.row_values(2)[:4], ["广东", "李晓莹", "123456", "项目A"])
            self.assertEqual(sheet.row_values(3)[:4], ["广东", "张三", "222222", "项目B"])
            self.assertEqual(sheet.row_values(4)[:4], ["广东", "李晓莹", "123456", "项目C"])

    def test_run_cli_interactive_mode(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source = temp_path / "source.xlsx"
            target = temp_path / "target.xlsx"
            output = temp_path / "target_filled.xlsx"
            write_workbook(
                source,
                [
                    (
                        "数据",
                        [
                            ["姓名", "部门"],
                            ["a", "原部门1"],
                            ["b", "原部门2"],
                        ],
                    )
                ],
            )
            write_workbook(
                target,
                [
                    (
                        "模板",
                        [
                            ["姓名", "部门"],
                        ],
                    )
                ],
            )
            answers = [
                str(source),
                str(target),
                str(output),
                "y",
                "姓名",
                "a",
                "n",
                "部门",
                "待确认",
                "n",
                "n",
            ]
            with mock.patch("builtins.input", side_effect=answers):
                exit_code = run_cli([])
            self.assertEqual(exit_code, 0)
            workbook = SimpleWorkbook(output)
            sheet = workbook.sheet()
            self.assertEqual(sheet.row_values(2)[:2], ["a", "待确认"])
            self.assertEqual(sheet.row_values(3)[:2], ["b", "原部门2"])

    def test_run_cli_interactive_mode_can_add_multiple_rules(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source = temp_path / "source.xlsx"
            target = temp_path / "target.xlsx"
            output = temp_path / "target_filled.xlsx"
            write_workbook(
                source,
                [
                    (
                        "数据",
                        [
                            ["姓名", "部门", "状态"],
                            ["a", "原部门1", "启用"],
                            ["b", "原部门2", "停用"],
                        ],
                    )
                ],
            )
            write_workbook(
                target,
                [
                    (
                        "模板",
                        [
                            ["姓名", "部门", "状态"],
                        ],
                    )
                ],
            )
            answers = [
                str(source),
                str(target),
                str(output),
                "y",
                "姓名",
                "a",
                "n",
                "部门",
                "待确认",
                "n",
                "y",
                "状态",
                "停用",
                "n",
                "姓名",
                "离职",
                "n",
                "n",
            ]
            with mock.patch("builtins.input", side_effect=answers):
                exit_code = run_cli([])
            self.assertEqual(exit_code, 0)
            workbook = SimpleWorkbook(output)
            sheet = workbook.sheet()
            self.assertEqual(sheet.row_values(2)[:3], ["a", "待确认", "启用"])
            self.assertEqual(sheet.row_values(3)[:3], ["离职", "原部门2", "停用"])


if __name__ == "__main__":
    unittest.main()
