#!/usr/bin/env python3
"""A minimal Excel .xlsx helper built on the Python standard library.

This script keeps dependencies low by reading and writing Office Open XML
workbooks directly. It targets simple data sheets with a header row and is
compatible with Python 3.8+.
"""

from __future__ import annotations

import argparse
import os
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple
import xml.etree.ElementTree as ET

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_OFFICE_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_PACKAGE_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
NS_MARKUP_COMPAT = "http://schemas.openxmlformats.org/markup-compatibility/2006"
NS_X14AC = "http://schemas.microsoft.com/office/spreadsheetml/2009/9/ac"
NS_XR = "http://schemas.microsoft.com/office/spreadsheetml/2014/revision"
NS_XR2 = "http://schemas.microsoft.com/office/spreadsheetml/2015/revision2"
NS_XR3 = "http://schemas.microsoft.com/office/spreadsheetml/2016/revision3"

NS = {
    "m": NS_MAIN,
    "r": NS_OFFICE_REL,
    "p": NS_PACKAGE_REL,
}

ET.register_namespace("", NS_MAIN)
ET.register_namespace("r", NS_OFFICE_REL)
ET.register_namespace("mc", NS_MARKUP_COMPAT)
ET.register_namespace("x14ac", NS_X14AC)
ET.register_namespace("xr", NS_XR)
ET.register_namespace("xr2", NS_XR2)
ET.register_namespace("xr3", NS_XR3)

TAG_SHEET_DATA = "{%s}sheetData" % NS_MAIN
TAG_DIMENSION = "{%s}dimension" % NS_MAIN
TAG_ROW = "{%s}row" % NS_MAIN
TAG_CELL = "{%s}c" % NS_MAIN
TAG_VALUE = "{%s}v" % NS_MAIN
TAG_INLINE_STRING = "{%s}is" % NS_MAIN
TAG_TEXT = "{%s}t" % NS_MAIN
TAG_FORMULA = "{%s}f" % NS_MAIN
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"


@dataclass(frozen=True)
class CellValue:
    kind: str
    value: str = ""
    formula: Optional[str] = None

    @property
    def is_blank(self) -> bool:
        return self.kind == "blank"

    def display(self) -> str:
        return self.value


@dataclass(frozen=True)
class CopySummary:
    copied_rows: int
    matched_headers: List[str]
    missing_headers: List[str]
    source_sheet: str
    target_sheet: str
    replace_summaries: List[ReplaceSummary] = field(default_factory=list)

    @property
    def replace_summary(self) -> Optional[ReplaceSummary]:
        return self.replace_summaries[0] if self.replace_summaries else None


@dataclass(frozen=True)
class ReplaceSummary:
    matched_rows: int
    condition_columns: List[str]
    update_columns: List[str]
    sheet_name: str

    @property
    def where_column(self) -> str:
        return " & ".join(self.condition_columns)

    @property
    def set_column(self) -> str:
        return ", ".join(self.update_columns)


@dataclass(frozen=True)
class ReplaceCondition:
    column: str
    equals_value: str


@dataclass(frozen=True)
class ReplaceAction:
    column: str
    value: str


@dataclass(frozen=True)
class ReplaceRule:
    conditions: List[ReplaceCondition]
    updates: List[ReplaceAction]

    @classmethod
    def simple(
        cls,
        where_column: str,
        equals_value: str,
        set_value: str,
        set_column: Optional[str] = None,
    ) -> "ReplaceRule":
        return cls(
            conditions=[ReplaceCondition(column=where_column, equals_value=equals_value)],
            updates=[ReplaceAction(column=set_column or where_column, value=set_value)],
        )


class ProgressPrinter:
    def __init__(
        self,
        label: str,
        total: int,
        enabled: bool,
        min_total: int = 20,
        min_row_step: int = 10,
    ):
        self.label = label
        self.total = max(total, 0)
        self.enabled = enabled and self.total >= min_total
        self.row_step = max(self.total // 100, min_row_step)
        self._current = 0
        self._last_reported = 0

    def start(self, detail: str = "") -> None:
        if not self.enabled:
            return
        suffix = "，%s" % detail if detail else ""
        print("%s开始: 0/%d%s" % (self.label, self.total, suffix), flush=True)

    def update(self, current: int) -> None:
        if not self.enabled:
            return
        self._current = min(current, self.total)
        percent = 100 if self.total == 0 else int(self._current * 100 / self.total)
        if self._current >= self.total or self._current - self._last_reported >= self.row_step:
            print("%s进度: %d/%d (%d%%)" % (self.label, self._current, self.total, percent), flush=True)
            self._last_reported = self._current

    def finish(self, detail: str = "") -> None:
        if not self.enabled:
            return
        suffix = "，%s" % detail if detail else ""
        if self._current < self.total:
            self.update(self.total)
        print("%s完成: %d/%d%s" % (self.label, self.total, self.total, suffix), flush=True)


def column_letter_to_index(letters: str) -> int:
    result = 0
    for char in letters:
        if not char.isalpha():
            continue
        result = result * 26 + ord(char.upper()) - 64
    return result


def column_index_to_letter(index: int) -> str:
    if index < 1:
        raise ValueError("column index must be >= 1")
    chars: List[str] = []
    current = index
    while current:
        current, remainder = divmod(current - 1, 26)
        chars.append(chr(65 + remainder))
    return "".join(reversed(chars))


def split_cell_reference(reference: str) -> Tuple[int, int]:
    letters = "".join(ch for ch in reference if ch.isalpha())
    numbers = "".join(ch for ch in reference if ch.isdigit())
    if not letters or not numbers:
        raise ValueError("invalid cell reference: %s" % reference)
    return int(numbers), column_letter_to_index(letters)


def build_cell_reference(row_idx: int, column_idx: int) -> str:
    return "%s%d" % (column_index_to_letter(column_idx), row_idx)


def ensure_text_node(parent: ET.Element, value: str) -> None:
    text_node = ET.SubElement(parent, TAG_TEXT)
    if value != value.strip() or "\n" in value:
        text_node.set(XML_SPACE, "preserve")
    text_node.text = value


class SimpleSheet:
    def __init__(self, root: ET.Element, shared_strings: Sequence[str], title: str):
        self.root = root
        self.shared_strings = list(shared_strings)
        self.title = title
        sheet_data = self.root.find("m:sheetData", NS)
        if sheet_data is None:
            sheet_data = ET.SubElement(self.root, TAG_SHEET_DATA)
        self.sheet_data = sheet_data
        self._row_cache: Dict[int, ET.Element] = {}
        self._cell_cache: Dict[int, Dict[int, ET.Element]] = {}
        self._header_cache: Dict[int, Dict[str, int]] = {}
        self._max_row_cache = 0
        self._max_col_cache = 0
        self._bounds_dirty = False
        self._build_caches()

    def _build_caches(self) -> None:
        self._row_cache = {}
        self._cell_cache = {}
        self._header_cache = {}
        self._max_row_cache = 0
        self._max_col_cache = 0
        self._bounds_dirty = False
        for row in self._rows():
            row_idx = int(row.attrib.get("r", "0"))
            self._row_cache[row_idx] = row
            cells: Dict[int, ET.Element] = {}
            for cell in row.findall(TAG_CELL):
                reference = cell.attrib.get("r", "")
                if not reference:
                    continue
                _, col_idx = split_cell_reference(reference)
                cells[col_idx] = cell
                if col_idx > self._max_col_cache:
                    self._max_col_cache = col_idx
            self._cell_cache[row_idx] = cells
            if row_idx > self._max_row_cache:
                self._max_row_cache = row_idx

    def _invalidate_header_cache(self, row_idx: Optional[int] = None) -> None:
        if row_idx is None:
            self._header_cache.clear()
            return
        self._header_cache.pop(row_idx, None)

    def _recalculate_bounds(self) -> None:
        self._max_row_cache = max(self._row_cache) if self._row_cache else 0
        max_col = 0
        for cell_map in self._cell_cache.values():
            if cell_map:
                cell_max_col = max(cell_map)
                if cell_max_col > max_col:
                    max_col = cell_max_col
        self._max_col_cache = max_col
        self._bounds_dirty = False

    def _rows(self) -> List[ET.Element]:
        return self.sheet_data.findall(TAG_ROW)

    def _row_map(self) -> Dict[int, ET.Element]:
        return self._row_cache

    def _cell_map(self, row_elem: ET.Element) -> Dict[int, ET.Element]:
        row_idx = int(row_elem.attrib.get("r", "0"))
        return self._cell_cache.setdefault(row_idx, {})

    @property
    def max_row(self) -> int:
        if self._bounds_dirty:
            self._recalculate_bounds()
        return self._max_row_cache

    @property
    def max_column(self) -> int:
        if self._bounds_dirty:
            self._recalculate_bounds()
        return self._max_col_cache

    def get_cell(self, row_idx: int, column_idx: int) -> CellValue:
        row_elem = self._row_cache.get(row_idx)
        if row_elem is None:
            return CellValue("blank")
        cell_elem = self._cell_map(row_elem).get(column_idx)
        if cell_elem is None:
            return CellValue("blank")
        formula_elem = cell_elem.find(TAG_FORMULA)
        value_elem = cell_elem.find(TAG_VALUE)
        inline_elem = cell_elem.find(TAG_INLINE_STRING)
        cell_type = cell_elem.attrib.get("t")
        if formula_elem is not None:
            return CellValue(
                kind="formula",
                value=value_elem.text if value_elem is not None and value_elem.text else "",
                formula=formula_elem.text or "",
            )
        if cell_type == "s" and value_elem is not None and value_elem.text is not None:
            return CellValue("text", self.shared_strings[int(value_elem.text)])
        if cell_type == "inlineStr" and inline_elem is not None:
            parts = []
            for text_node in inline_elem.findall(".//m:t", NS):
                parts.append(text_node.text or "")
            return CellValue("text", "".join(parts))
        if cell_type == "b" and value_elem is not None:
            return CellValue("bool", value_elem.text or "0")
        if value_elem is not None and value_elem.text is not None:
            return CellValue("number", value_elem.text)
        return CellValue("blank")

    def set_cell(self, row_idx: int, column_idx: int, cell_value: CellValue, update_dimension: bool = True) -> None:
        row_elem = self._ensure_row(row_idx)
        cell_elem = self._ensure_cell(row_elem, row_idx, column_idx)
        cell_map = self._cell_map(row_elem)
        self._clear_cell_payload(cell_elem)
        if cell_value.is_blank or cell_value.value == "":
            row_elem.remove(cell_elem)
            cell_map.pop(column_idx, None)
            self._invalidate_header_cache(row_idx)
            self._bounds_dirty = True
            if not cell_map:
                self.sheet_data.remove(row_elem)
                self._row_cache.pop(row_idx, None)
                self._cell_cache.pop(row_idx, None)
            if update_dimension:
                self.update_dimension()
            return
        if cell_value.kind == "formula":
            formula_elem = ET.SubElement(cell_elem, TAG_FORMULA)
            formula_elem.text = cell_value.formula or ""
            value_elem = ET.SubElement(cell_elem, TAG_VALUE)
            value_elem.text = cell_value.value
        elif cell_value.kind == "number":
            value_elem = ET.SubElement(cell_elem, TAG_VALUE)
            value_elem.text = cell_value.value
        elif cell_value.kind == "bool":
            cell_elem.set("t", "b")
            value_elem = ET.SubElement(cell_elem, TAG_VALUE)
            value_elem.text = "1" if cell_value.value in {"1", "TRUE", "true"} else "0"
        else:
            cell_elem.set("t", "inlineStr")
            inline_elem = ET.SubElement(cell_elem, TAG_INLINE_STRING)
            ensure_text_node(inline_elem, cell_value.value)
        self._invalidate_header_cache(row_idx)
        if row_idx > self._max_row_cache:
            self._max_row_cache = row_idx
        if column_idx > self._max_col_cache:
            self._max_col_cache = column_idx
        if update_dimension:
            self.update_dimension()

    def headers(self, header_row: int = 1) -> Dict[str, int]:
        cached_headers = self._header_cache.get(header_row)
        if cached_headers is not None:
            return dict(cached_headers)
        row_elem = self._row_cache.get(header_row)
        if row_elem is None:
            raise ValueError("header row %d does not exist in sheet %s" % (header_row, self.title))
        headers: Dict[str, int] = {}
        duplicates: List[str] = []
        for column_idx, _ in sorted(self._cell_map(row_elem).items()):
            value = self.get_cell(header_row, column_idx).display().strip()
            if not value:
                continue
            if value in headers:
                duplicates.append(value)
                continue
            headers[value] = column_idx
        if duplicates:
            raise ValueError(
                "sheet %s has duplicate headers: %s" % (self.title, ", ".join(sorted(set(duplicates))))
            )
        self._header_cache[header_row] = dict(headers)
        return headers

    def update_dimension(self) -> None:
        max_row = self.max_row
        max_col = self.max_column
        if max_row < 1 or max_col < 1:
            ref = "A1"
        elif max_row == 1 and max_col == 1:
            ref = "A1"
        else:
            ref = "A1:%s%d" % (column_index_to_letter(max_col), max_row)
        dimension = self.root.find("m:dimension", NS)
        if dimension is None:
            dimension = ET.Element(TAG_DIMENSION)
            self.root.insert(0, dimension)
        dimension.set("ref", ref)

    def row_values(self, row_idx: int) -> List[str]:
        result: List[str] = []
        max_col = self.max_column
        for col_idx in range(1, max_col + 1):
            result.append(self.get_cell(row_idx, col_idx).display())
        return result

    def _ensure_row(self, row_idx: int) -> ET.Element:
        if row_idx in self._row_cache:
            return self._row_cache[row_idx]
        new_row = ET.Element(TAG_ROW, {"r": str(row_idx)})
        inserted = False
        rows = self._rows()
        for position, row_elem in enumerate(rows):
            current_idx = int(row_elem.attrib.get("r", "0"))
            if current_idx > row_idx:
                self.sheet_data.insert(position, new_row)
                inserted = True
                break
        if not inserted:
            self.sheet_data.append(new_row)
        self._row_cache[row_idx] = new_row
        self._cell_cache[row_idx] = {}
        if row_idx > self._max_row_cache:
            self._max_row_cache = row_idx
        return new_row

    def _ensure_cell(self, row_elem: ET.Element, row_idx: int, column_idx: int) -> ET.Element:
        cell_map = self._cell_map(row_elem)
        if column_idx in cell_map:
            return cell_map[column_idx]
        reference = build_cell_reference(row_idx, column_idx)
        new_cell = ET.Element(TAG_CELL, {"r": reference})
        inserted = False
        cells = row_elem.findall(TAG_CELL)
        for position, cell_elem in enumerate(cells):
            existing_ref = cell_elem.attrib.get("r", "")
            _, existing_col = split_cell_reference(existing_ref)
            if existing_col > column_idx:
                row_elem.insert(position, new_cell)
                inserted = True
                break
        if not inserted:
            row_elem.append(new_cell)
        cell_map[column_idx] = new_cell
        return new_cell

    @staticmethod
    def _clear_cell_payload(cell_elem: ET.Element) -> None:
        cell_elem.attrib.pop("t", None)
        for child in list(cell_elem):
            if child.tag in {TAG_FORMULA, TAG_VALUE, TAG_INLINE_STRING}:
                cell_elem.remove(child)


class SimpleWorkbook:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._archive: Dict[str, bytes] = {}
        self._sheet_cache: Dict[str, SimpleSheet] = {}
        self._sheet_name_to_path = self._load_sheet_mapping()

    def _load_sheet_mapping(self) -> Dict[str, str]:
        with zipfile.ZipFile(self.path, "r") as source_zip:
            self._archive = {info.filename: source_zip.read(info.filename) for info in source_zip.infolist()}
        workbook_root = ET.fromstring(self._archive["xl/workbook.xml"])
        rels_root = ET.fromstring(self._archive["xl/_rels/workbook.xml.rels"])
        rel_map = {
            rel.attrib["Id"]: rel.attrib["Target"]
            for rel in rels_root.findall("p:Relationship", NS)
        }
        result: Dict[str, str] = {}
        sheets = workbook_root.find("m:sheets", NS)
        if sheets is None:
            raise ValueError("workbook has no sheets: %s" % self.path)
        for sheet in sheets:
            sheet_name = sheet.attrib["name"]
            rel_id = sheet.attrib["{%s}id" % NS_OFFICE_REL]
            target = rel_map[rel_id]
            if not target.startswith("xl/"):
                target = "xl/" + target.lstrip("/")
            result[sheet_name] = target
        return result

    @property
    def sheet_names(self) -> List[str]:
        return list(self._sheet_name_to_path.keys())

    @property
    def shared_strings(self) -> List[str]:
        if "xl/sharedStrings.xml" not in self._archive:
            return []
        root = ET.fromstring(self._archive["xl/sharedStrings.xml"])
        strings: List[str] = []
        for item in root.findall("m:si", NS):
            parts = []
            for text_node in item.findall(".//m:t", NS):
                parts.append(text_node.text or "")
            strings.append("".join(parts))
        return strings

    def sheet(self, name: Optional[str] = None) -> SimpleSheet:
        sheet_name = name or self.sheet_names[0]
        if sheet_name not in self._sheet_name_to_path:
            raise ValueError("sheet %s not found in %s" % (sheet_name, self.path))
        if sheet_name in self._sheet_cache:
            return self._sheet_cache[sheet_name]
        sheet_path = self._sheet_name_to_path[sheet_name]
        root = ET.fromstring(self._archive[sheet_path])
        sheet = SimpleSheet(root=root, shared_strings=self.shared_strings, title=sheet_name)
        self._sheet_cache[sheet_name] = sheet
        return sheet

    def save(self, output_path: Path) -> None:
        output_path = Path(output_path)
        replacements = {}
        for sheet_name, sheet in self._sheet_cache.items():
            sheet_path = self._sheet_name_to_path[sheet_name]
            replacements[sheet_path] = ET.tostring(
                sheet.root,
                encoding="utf-8",
                xml_declaration=True,
            )
        fd, temp_name = tempfile.mkstemp(
            prefix=output_path.stem + ".",
            suffix=output_path.suffix,
            dir=str(output_path.parent),
        )
        os.close(fd)
        try:
            with zipfile.ZipFile(self.path, "r") as source_zip, zipfile.ZipFile(
                temp_name,
                "w",
            ) as target_zip:
                for info in source_zip.infolist():
                    payload = replacements.get(info.filename, source_zip.read(info.filename))
                    target_zip.writestr(info, payload)
            os.replace(temp_name, output_path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)


def apply_replace_on_sheet(
    sheet: SimpleSheet,
    rule: ReplaceRule,
    header_row: int = 1,
    data_start_row: Optional[int] = None,
    progress: Optional[ProgressPrinter] = None,
) -> ReplaceSummary:
    headers = sheet.headers(header_row)
    for condition in rule.conditions:
        if condition.column not in headers:
            raise ValueError("column %s not found in sheet %s" % (condition.column, sheet.title))
    for action in rule.updates:
        if action.column not in headers:
            raise ValueError("column %s not found in sheet %s" % (action.column, sheet.title))
    condition_indexes = [(condition, headers[condition.column]) for condition in rule.conditions]
    update_indexes = [(action, headers[action.column]) for action in rule.updates]
    start_row = data_start_row or header_row + 1
    total_rows = max(sheet.max_row - start_row + 1, 0)
    if progress is not None:
        progress.start(
            "条件数=%d，更新列数=%d" % (len(rule.conditions), len(rule.updates))
        )
    matched_rows = 0
    for processed_rows, row_idx in enumerate(range(start_row, sheet.max_row + 1), start=1):
        row_matches = True
        for condition, column_idx in condition_indexes:
            current_value = sheet.get_cell(row_idx, column_idx).display()
            if current_value != condition.equals_value:
                row_matches = False
                break
        if row_matches:
            for action, column_idx in update_indexes:
                kind = "blank" if action.value == "" else "text"
                sheet.set_cell(
                    row_idx,
                    column_idx,
                    CellValue(kind=kind, value=action.value),
                    update_dimension=False,
                )
            matched_rows += 1
        if progress is not None and total_rows:
            progress.update(processed_rows)
    if progress is not None:
        progress.finish("匹配行数=%d" % matched_rows)
    return ReplaceSummary(
        matched_rows=matched_rows,
        condition_columns=[condition.column for condition in rule.conditions],
        update_columns=[action.column for action in rule.updates],
        sheet_name=sheet.title,
    )


def apply_replace_rules_on_sheet(
    sheet: SimpleSheet,
    rules: Sequence[ReplaceRule],
    header_row: int = 1,
    data_start_row: Optional[int] = None,
    show_progress: bool = False,
) -> List[ReplaceSummary]:
    total_rows = max(sheet.max_row - (data_start_row or header_row + 1) + 1, 0)
    summaries: List[ReplaceSummary] = []
    for index, rule in enumerate(rules, start=1):
        progress = ProgressPrinter(
            label="替换规则%d/%d" % (index, len(rules)),
            total=total_rows,
            enabled=show_progress,
        )
        summaries.append(
            apply_replace_on_sheet(
                sheet=sheet,
                rule=rule,
                header_row=header_row,
                data_start_row=data_start_row,
                progress=progress,
            )
        )
    return summaries


def copy_matching_fields(
    source_path: Path,
    target_path: Path,
    output_path: Path,
    source_sheet_name: Optional[str] = None,
    target_sheet_name: Optional[str] = None,
    header_row: int = 1,
    data_start_row: Optional[int] = None,
    replace_rules: Optional[Sequence[ReplaceRule]] = None,
    where_column: Optional[str] = None,
    equals_value: Optional[str] = None,
    set_value: Optional[str] = None,
    set_column: Optional[str] = None,
    show_progress: bool = False,
) -> CopySummary:
    source_book = SimpleWorkbook(source_path)
    target_book = SimpleWorkbook(target_path)
    source_sheet = source_book.sheet(source_sheet_name)
    target_sheet = target_book.sheet(target_sheet_name)
    source_headers = source_sheet.headers(header_row)
    target_headers = target_sheet.headers(header_row)
    matched_headers = [header for header in target_headers if header in source_headers]
    missing_headers = [header for header in target_headers if header not in source_headers]
    start_row = data_start_row or header_row + 1
    total_rows = max(source_sheet.max_row - start_row + 1, 0)
    copy_progress = ProgressPrinter(
        label="复制",
        total=total_rows,
        enabled=show_progress,
    )
    copy_progress.start("字段数=%d" % len(matched_headers))
    copied_rows = 0
    for processed_rows, row_idx in enumerate(range(start_row, source_sheet.max_row + 1), start=1):
        row_copied = False
        for header in matched_headers:
            src_col = source_headers[header]
            dst_col = target_headers[header]
            target_sheet.set_cell(
                row_idx,
                dst_col,
                source_sheet.get_cell(row_idx, src_col),
                update_dimension=False,
            )
            row_copied = True
        if row_copied:
            copied_rows += 1
        if total_rows:
            copy_progress.update(processed_rows)
    copy_progress.finish("实际复制行数=%d" % copied_rows)
    rules = list(replace_rules or [])
    if not rules and any(value is not None for value in [where_column, equals_value, set_value, set_column]):
        validate_simple_replace_args(where_column, equals_value, set_value)
        rules = [
            ReplaceRule.simple(
                where_column=where_column or "",
                equals_value=equals_value or "",
                set_column=set_column,
                set_value=set_value or "",
            )
        ]
    replace_summaries = []
    if rules:
        replace_summaries = apply_replace_rules_on_sheet(
            sheet=target_sheet,
            rules=rules,
            header_row=header_row,
            data_start_row=data_start_row,
            show_progress=show_progress,
        )
    target_sheet.update_dimension()
    if show_progress:
        print("正在写出结果文件...", flush=True)
    target_book.save(output_path)
    if show_progress:
        print("结果文件写出完成。", flush=True)
    return CopySummary(
        copied_rows=copied_rows,
        matched_headers=matched_headers,
        missing_headers=missing_headers,
        source_sheet=source_sheet.title,
        target_sheet=target_sheet.title,
        replace_summaries=replace_summaries,
    )


def build_default_output_path(source_path: Path, timestamp: Optional[str] = None) -> Path:
    stamp = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    return source_path.with_name("%s_结果_%s%s" % (source_path.stem, stamp, source_path.suffix))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Copy same-row values by header name, then optionally replace matched rows."
    )
    parser.add_argument("source", nargs="?", help="Source .xlsx path")
    parser.add_argument("target", nargs="?", help="Target template .xlsx path")
    parser.add_argument(
        "-o",
        "--out",
        help="Output file path. Default: target filename + _filled",
    )
    parser.add_argument("--src-sheet", help="Source sheet name. Default: first sheet")
    parser.add_argument("--dst-sheet", help="Target sheet name. Default: first sheet")
    parser.add_argument("--header-row", type=int, default=1, help="Header row index, default 1")
    parser.add_argument(
        "--start-row",
        type=int,
        help="Data start row index. Default: header row + 1",
    )
    parser.add_argument("-w", "--where", help="After copying, filter rows by this column")
    parser.add_argument("-e", "--equals", help="Only rows with this exact value are matched")
    parser.add_argument("-s", "--set", dest="set_column", help="Column to change. Default: same as --where")
    parser.add_argument("-v", "--value", dest="set_value", help="Replacement value")
    parser.add_argument(
        "-r",
        "--rule",
        action="append",
        default=[],
        help="Extra replace rule. Format: 筛选列|筛选值|新值, 筛选列|筛选值|修改列|新值, or 条件列=值&条件列2=值2=>更新列=值&更新列2=值2",
    )
    parser.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="Ask questions instead of requiring all args on the command line",
    )
    return parser


def discover_xlsx_files(base_dir: Path) -> List[Path]:
    return sorted(
        path
        for path in base_dir.iterdir()
        if path.is_file() and path.suffix.lower() == ".xlsx" and not path.name.startswith(".~")
    )


def is_generated_output(path: Path) -> bool:
    markers = ["_结果_", "_filled", "_quick", "_interactive", "_replaced", "_updated"]
    return any(marker in path.stem for marker in markers)


def guess_default_paths(base_dir: Path) -> Tuple[Optional[Path], Optional[Path]]:
    files = discover_xlsx_files(base_dir)
    if not files:
        return None, None
    primary_files = [path for path in files if not is_generated_output(path)]
    candidates = primary_files or files
    target = next((path for path in candidates if "模板" in path.stem), None)
    source = next((path for path in candidates if path != target and "模板" not in path.stem), None)
    if source is None and files:
        source = candidates[0]
    if target is None:
        target = next((path for path in candidates if path != source), None)
    return source, target


def prompt_text(label: str, default: Optional[str] = None, required: bool = False) -> str:
    while True:
        suffix = " [%s]" % default if default else ""
        value = input("%s%s: " % (label, suffix)).strip()
        if value:
            return value
        if default is not None:
            return default
        if not required:
            return ""
        print("不能为空，请重新输入。")


def prompt_yes_no(label: str, default: bool = False) -> bool:
    hint = "Y/n" if default else "y/N"
    while True:
        value = input("%s [%s]: " % (label, hint)).strip().lower()
        if not value:
            return default
        if value in {"y", "yes"}:
            return True
        if value in {"n", "no"}:
            return False
        print("请输入 y 或 n。")


def prompt_existing_file(label: str, default: Optional[Path] = None) -> Path:
    while True:
        default_text = str(default) if default else None
        raw = prompt_text(label, default=default_text, required=True)
        path = Path(raw).expanduser()
        if path.is_file():
            return path
        print("文件不存在: %s" % path)


def prompt_sheet_name(path: Path, label: str, preset: Optional[str] = None) -> Optional[str]:
    if preset:
        return preset
    workbook = SimpleWorkbook(path)
    sheets = workbook.sheet_names
    if not sheets:
        return None
    if len(sheets) == 1:
        return sheets[0]
    print("%s可用工作表: %s" % (label, "、".join(sheets)))
    return prompt_text(label + "工作表", default=sheets[0], required=True)


def validate_replace_args(where: Optional[str], equals: Optional[str], value: Optional[str]) -> None:
    if not any(item is not None for item in [where, equals, value]):
        return
    missing = []
    if where is None:
        missing.append("--where / -w")
    if equals is None:
        missing.append("--equals / -e")
    if value is None:
        missing.append("--value / -v")
    if missing:
        raise ValueError("replace args missing: %s" % ", ".join(missing))


def validate_simple_replace_args(where: Optional[str], equals: Optional[str], value: Optional[str]) -> None:
    validate_replace_args(where, equals, value)


def parse_rule_text(raw_rule: str) -> ReplaceRule:
    if "=>" in raw_rule:
        left_text, right_text = [part.strip() for part in raw_rule.split("=>", 1)]
        conditions = parse_rule_side(left_text, "condition")
        updates = parse_rule_side(right_text, "update")
        return ReplaceRule(
            conditions=[
                ReplaceCondition(column=column, equals_value=value)
                for column, value in conditions
            ],
            updates=[
                ReplaceAction(column=column, value=value)
                for column, value in updates
            ],
        )
    parts = [part.strip() for part in raw_rule.split("|")]
    if len(parts) == 3:
        where_column, equals_value, set_value = parts
        set_column = None
    elif len(parts) == 4:
        where_column, equals_value, set_column, set_value = parts
        set_column = set_column or None
    else:
        raise ValueError("rule format invalid: %s" % raw_rule)
    if not where_column or not equals_value:
        raise ValueError("rule format invalid: %s" % raw_rule)
    return ReplaceRule.simple(
        where_column=where_column,
        equals_value=equals_value,
        set_column=set_column,
        set_value=set_value,
    )


def parse_rule_side(raw_text: str, side_name: str) -> List[Tuple[str, str]]:
    entries: List[Tuple[str, str]] = []
    for part in raw_text.split("&"):
        item = part.strip()
        if not item or "=" not in item:
            raise ValueError("rule %s format invalid: %s" % (side_name, raw_text))
        column, value = [value_part.strip() for value_part in item.split("=", 1)]
        if not column:
            raise ValueError("rule %s format invalid: %s" % (side_name, raw_text))
        entries.append((column, value))
    if not entries:
        raise ValueError("rule %s format invalid: %s" % (side_name, raw_text))
    return entries


def collect_replace_rules(args: argparse.Namespace) -> List[ReplaceRule]:
    if hasattr(args, "replace_rules") and args.replace_rules is not None:
        return list(args.replace_rules)
    rules: List[ReplaceRule] = []
    for raw_rule in getattr(args, "rule", []):
        rules.append(parse_rule_text(raw_rule))
    if any(item is not None for item in [args.where, args.equals, args.set_column, args.set_value]):
        validate_simple_replace_args(args.where, args.equals, args.set_value)
        rules.append(
            ReplaceRule.simple(
                where_column=args.where or "",
                equals_value=args.equals or "",
                set_column=args.set_column,
                set_value=args.set_value or "",
            )
        )
    return rules


def prompt_replace_rules() -> List[ReplaceRule]:
    if not prompt_yes_no("复制完成后要不要继续替换", default=False):
        return []
    rules: List[ReplaceRule] = []
    while True:
        conditions: List[ReplaceCondition] = []
        updates: List[ReplaceAction] = []
        while True:
            where = prompt_text("筛选条件列", required=True)
            equals = prompt_text("这个条件列等于什么值", required=True)
            conditions.append(ReplaceCondition(column=where, equals_value=equals))
            if not prompt_yes_no("这一条规则还要继续加筛选条件吗", default=False):
                break
        while True:
            set_column = prompt_text("要改哪一列", required=True)
            value = prompt_text("这一列改成什么值", required=True)
            updates.append(ReplaceAction(column=set_column, value=value))
            if not prompt_yes_no("这一条规则还要继续加更新列吗", default=False):
                break
        rules.append(
            ReplaceRule(
                conditions=conditions,
                updates=updates,
            )
        )
        if not prompt_yes_no("还要继续新增一条替换规则吗", default=False):
            break
    return rules


def choose_sheet_name(
    path: Path,
    label: str,
    preset: Optional[str] = None,
    preferred: Optional[str] = None,
) -> Optional[str]:
    if preset:
        return preset
    workbook = SimpleWorkbook(path)
    sheets = workbook.sheet_names
    if not sheets:
        return None
    if len(sheets) == 1:
        return sheets[0]
    if preferred and preferred in sheets:
        return preferred
    return prompt_sheet_name(path, label, preset)


def build_interactive_args(args: argparse.Namespace) -> argparse.Namespace:
    source_default, target_default = guess_default_paths(Path.cwd())
    source_path = Path(args.source).expanduser() if args.source else prompt_existing_file("源文件", source_default)
    target_path = Path(args.target).expanduser() if args.target else prompt_existing_file("目标模板文件", target_default)
    source_sheet = choose_sheet_name(source_path, "源文件", args.src_sheet)
    target_sheet = choose_sheet_name(target_path, "目标文件", args.dst_sheet, preferred=source_sheet)
    output_default = str(Path(args.out).expanduser()) if args.out else str(build_default_output_path(target_path))
    output_path = Path(prompt_text("输出文件", default=output_default, required=True)).expanduser()
    replace_rules = collect_replace_rules(args)
    if not replace_rules:
        replace_rules = prompt_replace_rules()
    return argparse.Namespace(
        source=str(source_path),
        target=str(target_path),
        out=str(output_path),
        src_sheet=source_sheet,
        dst_sheet=target_sheet,
        header_row=args.header_row,
        start_row=args.start_row,
        where=None,
        equals=None,
        set_column=None,
        set_value=None,
        rule=[],
        replace_rules=replace_rules,
        interactive=True,
    )


def print_summary(output_path: Path, summary: CopySummary) -> None:
    print("输出文件: %s" % output_path)
    print("源工作表: %s" % summary.source_sheet)
    print("目标工作表: %s" % summary.target_sheet)
    print("复制行数: %d" % summary.copied_rows)
    print("匹配字段数: %d" % len(summary.matched_headers))
    if summary.missing_headers:
        print("模板中未找到来源字段: %s" % "、".join(summary.missing_headers))
    if summary.replace_summaries:
        print("替换规则数: %d" % len(summary.replace_summaries))
        for index, replace_summary in enumerate(summary.replace_summaries, start=1):
            print(
                "规则%d: 条件列 %s, 更新列 %s, 匹配行数 %d"
                % (
                    index,
                    replace_summary.where_column,
                    replace_summary.set_column,
                    replace_summary.matched_rows,
                )
            )


def run_cli(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.interactive or not args.source or not args.target:
            args = build_interactive_args(args)
        replace_rules = collect_replace_rules(args)
        output_path = Path(args.out) if args.out else build_default_output_path(Path(args.target))
        summary = copy_matching_fields(
            source_path=Path(args.source),
            target_path=Path(args.target),
            output_path=output_path,
            source_sheet_name=args.src_sheet,
            target_sheet_name=args.dst_sheet,
            header_row=args.header_row,
            data_start_row=args.start_row,
            replace_rules=replace_rules,
            show_progress=True,
        )
        print_summary(output_path, summary)
        return 0
    except Exception as exc:
        print("执行失败: %s" % exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(run_cli())
