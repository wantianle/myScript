# -*- coding: utf-8 -*-
"""数据集清单加载与选择。

读取 YAML/JSON 清单文件，校验每个条目后返回 DatasetEntry 列表。
同时支持从清单顶层读取 packages 定义。
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from bench_smoke.models import DatasetEntry, ManifestError, PackageSpec


def _read_raw(path: str) -> Dict[str, Any]:
    """读取并解析清单文件，返回顶层 dict。"""
    if not os.path.isfile(path):
        raise ManifestError(f"Manifest file not found: {path}")

    ext = os.path.splitext(path)[1].lower()
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()

    if ext in (".yaml", ".yml"):
        try:
            import yaml
        except ImportError as exc:
            raise ManifestError(
                f"YAML manifest requires PyYAML, but import failed: {exc}. "
                "Install 'pyyaml' (pip install pyyaml) or use a JSON manifest."
            ) from exc
        data = yaml.safe_load(text)
    elif ext == ".json":
        data = json.loads(text)
    else:
        raise ManifestError(
            f"Unsupported manifest format: {ext}.  Use .yaml, .yml, or .json."
        )

    if not isinstance(data, dict):
        raise ManifestError(
            f"Manifest must be a dict, got: {type(data).__name__}"
        )
    return data


def load_manifest(path: str) -> List[DatasetEntry]:
    """解析并校验清单中的数据集条目。

    Raises:
        ManifestError: 文件不存在、格式无效或条目校验失败时抛出。
    """
    data = _read_raw(path)

    if "datasets" not in data:
        raise ManifestError("Manifest must contain a top-level 'datasets' list")

    raw_entries = data["datasets"]
    if not isinstance(raw_entries, list):
        raise ManifestError(
            f"'datasets' must be a list, got: {type(raw_entries).__name__}"
        )

    entries = [dict(item) for item in raw_entries]
    if not entries:
        raise ManifestError(f"Manifest {path} contains no dataset entries")

    _validate_entries(entries, path)

    try:
        return [DatasetEntry(**e) for e in entries]
    except TypeError as exc:
        raise ManifestError(f"Malformed manifest entry: {exc}") from exc


def load_manifest_packages(path: str) -> Optional[List[PackageSpec]]:
    """从清单顶层读取 packages 定义，不存在时返回 None。

    支持两种格式:
      - 字符串: "mdrive=1.2.3"
      - 字典:  {"package": "mdrive", "version": "1.2.3"}
    """
    data = _read_raw(path)
    raw_pkgs = data.get("packages")
    if raw_pkgs is None:
        return None

    if not isinstance(raw_pkgs, list):
        raise ManifestError(
            f"'packages' must be a list, got: {type(raw_pkgs).__name__}"
        )

    specs: List[PackageSpec] = []
    for idx, item in enumerate(raw_pkgs):
        if isinstance(item, str):
            if "=" not in item:
                raise ManifestError(
                    f"Package #{idx + 1}: expected NAME=VERSION format, got '{item}'"
                )
            pkg, ver = item.split("=", 1)
            specs.append(PackageSpec(package=pkg.strip(), version=ver.strip()))
        elif isinstance(item, dict):
            pkg = str(item.get("package", ""))
            ver = str(item.get("version", ""))
            if not pkg or not ver:
                raise ManifestError(
                    f"Package #{idx + 1}: 'package' and 'version' are required"
                )
            deps = item.get("install_with_deps", True)
            if isinstance(deps, str):
                deps = deps.lower() in ("1", "true", "yes")
            specs.append(PackageSpec(package=pkg, version=ver, install_with_deps=bool(deps)))
        else:
            raise ManifestError(
                f"Package #{idx + 1}: must be a string or dict, got {type(item).__name__}"
            )

    return specs if specs else None


def select_datasets(
    entries: List[DatasetEntry],
    dataset_ids: List[str],
) -> List[DatasetEntry]:
    """从数据集中筛选出指定 ID 的条目。

    dataset_ids 为空时返回 manifest 全部数据集。
    结果按 manifest 原顺序排列，重复 ID 自动去重。

    Raises:
        ManifestError: 请求的 ID 不存在时抛出。
    """
    if not dataset_ids:
        return list(entries)

    index: Dict[str, DatasetEntry] = {e.dataset_id: e for e in entries}
    allowed = set(dataset_ids)
    missing = [did for did in allowed if did not in index]
    if missing:
        raise ManifestError(
            f"Requested dataset IDs not found in manifest: {', '.join(missing)}"
        )
    return [e for e in entries if e.dataset_id in allowed]


# 内部辅助函数

_REQUIRED_FIELDS = {"dataset_id", "issue_description", "feishu_url", "source_path"}


def _validate_entries(entries: List[Dict[str, Any]], path: str) -> None:
    if not entries:
        raise ManifestError(f"Manifest {path} contains no dataset entries")

    seen_ids: set = set()

    for idx, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ManifestError(
                f"Manifest entry #{idx + 1} must be a dict, got {type(entry).__name__}"
            )

        missing = _REQUIRED_FIELDS - set(entry.keys())
        if missing:
            raise ManifestError(
                f"Manifest entry #{idx + 1} is missing required field(s): "
                f"{', '.join(sorted(missing))}"
            )

        did = str(entry["dataset_id"]).strip()
        if not did:
            raise ManifestError(f"Manifest entry #{idx + 1} has an empty dataset_id")
        if did in seen_ids:
            raise ManifestError(
                f"Duplicate dataset_id '{did}' in manifest (entry #{idx + 1})"
            )
        seen_ids.add(did)
        entry["dataset_id"] = did

        sp = str(entry["source_path"])
        if not os.path.isabs(sp):
            raise ManifestError(
                f"Manifest entry '{did}': source_path must be absolute, got '{sp}'"
            )
        entry["source_path"] = sp

        tags = entry.get("tags")
        if tags is None:
            entry["tags"] = []
        elif not isinstance(tags, list):
            raise ManifestError(
                f"Manifest entry '{did}': tags must be a list, got {type(tags).__name__}"
            )
        else:
            entry["tags"] = [str(t) for t in tags]
