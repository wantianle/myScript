import json
import re
from dataclasses import dataclass
from pathlib import Path

from core.errors import RuntimeEnvironmentError

_QUOTED_VMC_KEYS = (
    "MDRIVE_VEHICLE_MODEL",
    "MDRIVE_VEHICLE_NAME",
)


@dataclass
class RuntimeVersionInfo:
    mdrive_ver: str
    conf_ver: str
    model_ver: str
    map_ver: str
    localization_ver: str
    vehicle_model: str


def load_version_info(version_path: Path) -> RuntimeVersionInfo:
    """从 version.json 或 version.txt 中解析运行环境版本信息。"""
    if not version_path.is_file():
        raise RuntimeEnvironmentError("文件不存在: {0}".format(version_path))
    if version_path.suffix.lower() == ".txt":
        raw_values = _load_version_text(version_path)
    else:
        raw_values = _load_version_json(version_path)
    mdrive_ver = raw_values.get("mdrive", "")
    conf_ver = raw_values.get("mdrive_conf", "")
    if not mdrive_ver or not conf_ver:
        raise RuntimeEnvironmentError("未能从文件中解析出 mdrive 或 mdrive_conf 版本")
    return RuntimeVersionInfo(
        mdrive_ver=str(mdrive_ver),
        conf_ver=str(conf_ver),
        model_ver=str(raw_values.get("mdrive_model", "")),
        map_ver=str(raw_values.get("mdrive_map", "")),
        localization_ver=str(raw_values.get("mdrive_map_localization", "")),
        vehicle_model=str(conf_ver).split(".", 1)[0],
    )


def sync_runtime_environment(
    vmc_path: Path,
    version_info: RuntimeVersionInfo,
    vehicle_name: str,
) -> bool:
    """按解析结果更新 vmc.sh 中的运行环境版本定义。"""
    if not vmc_path.is_file():
        raise RuntimeEnvironmentError("文件不存在: {0}".format(vmc_path))
    vmc_text = vmc_path.read_text(encoding="utf-8")
    current_values = {
        "MDRIVE_VEHICLE_MODEL": _extract_vmc_value(vmc_text, "MDRIVE_VEHICLE_MODEL"),
        "MDRIVE_VEHICLE_NAME": _extract_vmc_value(vmc_text, "MDRIVE_VEHICLE_NAME"),
        "MDRIVE_VERSION": _extract_vmc_value(vmc_text, "MDRIVE_VERSION"),
        "MDRIVE_CONF_VERSION": _extract_vmc_value(vmc_text, "MDRIVE_CONF_VERSION"),
        "MDRIVE_MODEL_VERSION": _extract_vmc_value(vmc_text, "MDRIVE_MODEL_VERSION"),
        "MDRIVE_MAP_VERSION": _extract_vmc_value(vmc_text, "MDRIVE_MAP_VERSION"),
    }
    target_values = {
        "MDRIVE_VEHICLE_MODEL": version_info.vehicle_model,
        "MDRIVE_VEHICLE_NAME": vehicle_name,
        "MDRIVE_VERSION": version_info.mdrive_ver,
        "MDRIVE_CONF_VERSION": version_info.conf_ver,
        "MDRIVE_MODEL_VERSION": version_info.model_ver,
        "MDRIVE_MAP_VERSION": version_info.map_ver,
    }
    if current_values == target_values:
        return False
    updated_text = vmc_text
    for key_name, value_text in target_values.items():
        replacement = _format_vmc_assignment(key_name, value_text)
        updated_text = re.sub(
            r"^{0}=.*$".format(key_name),
            replacement,
            updated_text,
            flags=re.MULTILINE,
        )
    vmc_path.write_text(updated_text, encoding="utf-8")
    return True


def _load_version_json(version_path: Path) -> dict:
    try:
        return json.loads(version_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise RuntimeEnvironmentError(
            "读取 version 文件失败: {0}".format(version_path)
        ) from e


def _load_version_text(version_path: Path) -> dict:
    raw_values = {}
    try:
        for line in version_path.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) >= 2:
                raw_values[parts[0]] = parts[1]
    except OSError as e:
        raise RuntimeEnvironmentError(
            "读取 version 文件失败: {0}".format(version_path)
        ) from e
    return raw_values


def _extract_vmc_value(vmc_text: str, key_name: str) -> str:
    matched_value = re.search(
        r"^{0}=(.*)$".format(key_name),
        vmc_text,
        flags=re.MULTILINE,
    )
    if matched_value is None:
        raise RuntimeEnvironmentError("vmc.sh 缺少必要字段: {0}".format(key_name))
    return matched_value.group(1).strip().strip('"')


def _format_vmc_assignment(key_name: str, value_text: str) -> str:
    if key_name in _QUOTED_VMC_KEYS:
        return '{0}="{1}"'.format(key_name, value_text)
    return "{0}={1}".format(key_name, value_text)
