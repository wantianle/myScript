#!/usr/bin/env python3

import argparse
import base64
import json
import sys
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Tuple


ROOT = Path(__file__).resolve().parent
VENV_SITE = ROOT / ".venv_mcap" / "lib"
for site_dir in sorted(VENV_SITE.glob("python*/site-packages")):
    site_path = str(site_dir)
    if site_path not in sys.path:
        sys.path.insert(0, site_path)

import numpy as np
from mcap.reader import make_reader
from mcap.writer import CompressionType, Writer


POINT_CLOUD_SCHEMA_NAME = "foxglove.PointCloud"
MINIEYE_POINTCLOUD_SCHEMA = "minieye.sensor.PointCloud"

POINT_CLOUD_JSON_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "timestamp": {"$ref": "#/$defs/Timestamp"},
        "frame_id": {"type": "string"},
        "pose": {"$ref": "#/$defs/Pose"},
        "point_stride": {"type": "integer", "minimum": 0},
        "fields": {
            "type": "array",
            "items": {"$ref": "#/$defs/PackedElementField"},
        },
        "data": {"type": "string", "contentEncoding": "base64"},
    },
    "required": ["timestamp", "frame_id", "pose", "point_stride", "fields", "data"],
    "$defs": {
        "Timestamp": {
            "type": "object",
            "properties": {
                "sec": {"type": "integer", "minimum": 0},
                "nsec": {"type": "integer", "minimum": 0, "maximum": 999999999},
            },
            "required": ["sec", "nsec"],
        },
        "Vector3": {
            "type": "object",
            "properties": {"x": {"type": "number"}, "y": {"type": "number"}, "z": {"type": "number"}},
            "required": ["x", "y", "z"],
        },
        "Quaternion": {
            "type": "object",
            "properties": {
                "x": {"type": "number"},
                "y": {"type": "number"},
                "z": {"type": "number"},
                "w": {"type": "number"},
            },
            "required": ["x", "y", "z", "w"],
        },
        "Pose": {
            "type": "object",
            "properties": {
                "position": {"$ref": "#/$defs/Vector3"},
                "orientation": {"$ref": "#/$defs/Quaternion"},
            },
            "required": ["position", "orientation"],
        },
        "PackedElementField": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "offset": {"type": "integer", "minimum": 0},
                "type": {"type": "integer", "enum": [0, 1, 2, 3, 4, 5, 6, 7, 8]},
            },
            "required": ["name", "offset", "type"],
        },
    },
}

# Foxglove PackedElementField NumericType enum values.
UINT8 = 1
UINT16 = 3
FLOAT32 = 7
FLOAT64 = 8


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert minieye.sensor.PointCloud protobuf channels in MCAP to foxglove.PointCloud."
    )
    parser.add_argument("-i", "--input", required=True, help="Input MCAP path.")
    parser.add_argument("-o", "--output", required=True, help="Output MCAP path.")
    parser.add_argument(
        "--topics",
        help="Comma-separated list of pointcloud topics to convert. Default: all minieye.sensor.PointCloud topics.",
    )
    parser.add_argument(
        "--keep-other-topics",
        action="store_true",
        help="Also copy non-pointcloud topics through to the output file.",
    )
    parser.add_argument(
        "--compression",
        choices=["zstd", "none"],
        default="zstd",
        help="MCAP chunk compression for the output file.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Only convert the first N matching pointcloud messages, for testing.",
    )
    return parser.parse_args()


def read_varint(data: bytes, offset: int) -> Tuple[int, int]:
    value = 0
    shift = 0
    while True:
        if offset >= len(data):
            raise ValueError("unexpected EOF while reading varint")
        b = data[offset]
        offset += 1
        value |= (b & 0x7F) << shift
        if not (b & 0x80):
            return value, offset
        shift += 7
        if shift >= 64:
            raise ValueError("varint too long")


def skip_field(data: bytes, offset: int, wire_type: int) -> int:
    if wire_type == 0:
        _, offset = read_varint(data, offset)
        return offset
    if wire_type == 1:
        return offset + 8
    if wire_type == 2:
        size, offset = read_varint(data, offset)
        return offset + size
    if wire_type == 5:
        return offset + 4
    raise ValueError(f"unsupported wire type: {wire_type}")


def parse_header(data: bytes) -> Dict[str, object]:
    header: Dict[str, object] = {}
    offset = 0
    while offset < len(data):
        key, offset = read_varint(data, offset)
        field_number = key >> 3
        wire_type = key & 0x7
        if field_number in (1, 2, 3) and wire_type == 0:
            value, offset = read_varint(data, offset)
            if field_number == 1:
                header["timestamp"] = value
            elif field_number == 2:
                header["tick"] = value
            else:
                header["seq"] = value
        elif field_number == 4 and wire_type == 2:
            size, offset = read_varint(data, offset)
            header["frame_id"] = data[offset : offset + size].decode("utf-8", errors="replace")
            offset += size
        else:
            offset = skip_field(data, offset, wire_type)
    return header


def parse_minieye_pointcloud(data: bytes) -> Dict[str, object]:
    msg: Dict[str, object] = {}
    offset = 0
    while offset < len(data):
        key, offset = read_varint(data, offset)
        field_number = key >> 3
        wire_type = key & 0x7
        if field_number == 1 and wire_type == 2:
            size, offset = read_varint(data, offset)
            msg["header"] = parse_header(data[offset : offset + size])
            offset += size
        elif field_number in (2, 3, 6, 7, 8, 9) and wire_type == 0:
            value, offset = read_varint(data, offset)
            if field_number == 2:
                msg["tick_start"] = value
            elif field_number == 3:
                msg["tick_end"] = value
            elif field_number == 6:
                msg["width"] = value
            elif field_number == 7:
                msg["height"] = value
            elif field_number == 8:
                msg["point_type"] = value
            elif field_number == 9:
                msg["data_addr"] = value
        elif field_number in (4, 5) and wire_type == 0:
            value, offset = read_varint(data, offset)
            if field_number == 4:
                msg["remove_nan"] = bool(value)
            else:
                msg["is_compensate"] = bool(value)
        elif field_number == 10 and wire_type == 2:
            size, offset = read_varint(data, offset)
            msg["data"] = data[offset : offset + size]
            offset += size
        else:
            offset = skip_field(data, offset, wire_type)
    return msg


def ns_to_stamp(timestamp_ns: int) -> Dict[str, int]:
    return {"sec": timestamp_ns // 1_000_000_000, "nsec": timestamp_ns % 1_000_000_000}


def zero_pose() -> dict:
    return {
        "position": {"x": 0.0, "y": 0.0, "z": 0.0},
        "orientation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0},
    }


def normalize_to_ns(timestamp: int, fallback_ns: int) -> int:
    if timestamp <= 0:
        return fallback_ns
    # Observed in record_20260527_190340.mcap:
    # header.timestamp = 1779879820263941 while log_time = 1779879820265292000.
    # That header field is microseconds since epoch, not nanoseconds.
    if timestamp < 10_000_000_000_000_000:
        return timestamp * 1000
    return timestamp


def point_layout_for_type(point_type: int, topic: str) -> Tuple[np.dtype, List[dict], int]:
    if point_type == 1:
        dtype = np.dtype(
            [
                ("x", "<f4"),
                ("y", "<f4"),
                ("z", "<f4"),
                ("intensity", "<f4"),
            ],
            align=False,
        )
        fields = [
            {"name": "x", "offset": 0, "type": FLOAT32},
            {"name": "y", "offset": 4, "type": FLOAT32},
            {"name": "z", "offset": 8, "type": FLOAT32},
            {"name": "intensity", "offset": 12, "type": FLOAT32},
        ]
        return dtype, fields, dtype.itemsize

    if point_type == 2:
        # The re-recorded minieye.sensor.PointCloud payload in record_20260527_190340.mcap
        # is 20 bytes per point on all pointcloud topics:
        # x(float32), y(float32), z(float32), intensity(uint8), ring(uint16),
        # lidar_id(uint8), timestamp(float32).
        dtype = np.dtype(
            [
                ("x", "<f4"),
                ("y", "<f4"),
                ("z", "<f4"),
                ("intensity", "<u1"),
                ("ring", "<u2"),
                ("lidar_id", "<u1"),
                ("timestamp", "<f4"),
            ],
            align=False,
        )
        fields = [
            {"name": "x", "offset": 0, "type": FLOAT32},
            {"name": "y", "offset": 4, "type": FLOAT32},
            {"name": "z", "offset": 8, "type": FLOAT32},
            {"name": "intensity", "offset": 12, "type": UINT8},
            {"name": "ring", "offset": 13, "type": UINT16},
            {"name": "lidar_id", "offset": 15, "type": UINT8},
            {"name": "timestamp", "offset": 16, "type": FLOAT32},
        ]
        return dtype, fields, dtype.itemsize

    raise ValueError(f"unsupported point_type={point_type} on topic {topic}")


def minieye_to_foxglove_payload(topic: str, payload: bytes, fallback_log_time_ns: int) -> Tuple[int, bytes]:
    parsed = parse_minieye_pointcloud(payload)
    header = parsed.get("header", {})
    if not isinstance(header, dict):
        header = {}

    raw_timestamp = int(header.get("timestamp", 0) or 0)
    timestamp_ns = normalize_to_ns(raw_timestamp, fallback_log_time_ns)
    frame_id = str(header.get("frame_id", "") or "")
    point_type = int(parsed.get("point_type", 0) or 0)
    width = int(parsed.get("width", 0) or 0)
    height = int(parsed.get("height", 1) or 1)
    raw = parsed.get("data", b"")
    if not isinstance(raw, (bytes, bytearray)):
        raise ValueError(f"invalid data payload for topic {topic}")

    dtype, fields, point_stride = point_layout_for_type(point_type, topic)
    point_count = width * height
    expected_size = point_count * point_stride
    if expected_size == 0:
        point_count = len(raw) // point_stride
        expected_size = point_count * point_stride
    if len(raw) != expected_size:
        raise ValueError(
            f"{topic} payload size mismatch: len(data)={len(raw)}, expected={expected_size}, "
            f"width={width}, height={height}, point_type={point_type}, stride={point_stride}"
        )

    array = np.frombuffer(raw, dtype=dtype, count=point_count)
    foxglove_data = array.tobytes()
    message = {
        "timestamp": ns_to_stamp(timestamp_ns),
        "frame_id": frame_id,
        "pose": zero_pose(),
        "point_stride": point_stride,
        "fields": fields,
        "data": base64.b64encode(foxglove_data).decode("ascii"),
    }
    encoded = json.dumps(message, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return timestamp_ns, encoded


def selected_topics_arg(topics: Optional[str]) -> Optional[set[str]]:
    if not topics:
        return None
    return {item.strip() for item in topics.split(",") if item.strip()}


def iter_channel_map(summary) -> Dict[int, object]:
    return dict(summary.channels.items())


def main() -> int:
    args = parse_args()
    input_path = Path(args.input).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    selected_topics = selected_topics_arg(args.topics)
    compression = CompressionType.ZSTD if args.compression == "zstd" else CompressionType.NONE

    with input_path.open("rb") as src:
        reader = make_reader(src)
        summary = reader.get_summary()
        channel_map = iter_channel_map(summary)
        schema_map = dict(summary.schemas.items())

        with output_path.open("wb") as dst:
            writer = Writer(dst, compression=compression)
            writer.start(profile="foxglove")
            foxglove_schema_id = writer.register_schema(
                name=POINT_CLOUD_SCHEMA_NAME,
                encoding="jsonschema",
                data=json.dumps(POINT_CLOUD_JSON_SCHEMA, separators=(",", ":")).encode("utf-8"),
            )

            copied_channels: Dict[int, int] = {}
            foxglove_channels: Dict[str, int] = {}
            converted = 0

            for schema, channel, message in reader.iter_messages():
                source_schema_name = schema.name if schema else ""
                is_minieye_pc = source_schema_name == MINIEYE_POINTCLOUD_SCHEMA and channel.message_encoding == "protobuf"
                wants_topic = selected_topics is None or channel.topic in selected_topics

                if is_minieye_pc and wants_topic:
                    if channel.topic not in foxglove_channels:
                        foxglove_channels[channel.topic] = writer.register_channel(
                            topic=channel.topic,
                            message_encoding="json",
                            schema_id=foxglove_schema_id,
                            metadata={"source_schema": MINIEYE_POINTCLOUD_SCHEMA},
                        )
                    log_time, data = minieye_to_foxglove_payload(
                        channel.topic, message.data, message.log_time
                    )
                    writer.add_message(
                        channel_id=foxglove_channels[channel.topic],
                        log_time=log_time,
                        publish_time=log_time,
                        data=data,
                        sequence=message.sequence,
                    )
                    converted += 1
                    if args.limit is not None and converted >= args.limit:
                        break
                    if converted % 50 == 0:
                        print(f"converted {converted} pointcloud messages", file=sys.stderr)
                    continue

                if not args.keep_other_topics:
                    continue

                out_channel_id = copied_channels.get(channel.id)
                if out_channel_id is None:
                    out_schema_id = 0
                    if channel.schema_id:
                        source_schema = schema_map[channel.schema_id]
                        out_schema_id = writer.register_schema(
                            name=source_schema.name,
                            encoding=source_schema.encoding,
                            data=source_schema.data,
                        )
                    out_channel_id = writer.register_channel(
                        topic=channel.topic,
                        message_encoding=channel.message_encoding,
                        schema_id=out_schema_id,
                        metadata=channel.metadata,
                    )
                    copied_channels[channel.id] = out_channel_id
                writer.add_message(
                    channel_id=out_channel_id,
                    log_time=message.log_time,
                    publish_time=message.publish_time,
                    data=message.data,
                    sequence=message.sequence,
                )

            writer.finish()

    print(f"converted {converted} pointcloud messages to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
