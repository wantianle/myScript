#!/usr/bin/env python3
"""
sshc: resolve a XiaoZhu vehicle name to an SSH port mapping and connect.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROD_BASE_URL = "https://xiaozhu.minieye.cc"
TEST_BASE_URL = "https://xz-test.minieye.cc"
TEST_DISPLAY_URL = "https://xz-test.minieye.cc/navigation"
DEFAULT_LOGIN_PATH = "/xz-server/v1/session"
DEFAULT_VEHICLES_PATH = "/xz-server/v1/fleet/vehicles"
DEFAULT_PORT_MAPPINGS_PATH = "/xz-server/httpproxy/frp-manage-server/port-mappings"
DEFAULT_SSH_USER = "nvidia"
DEFAULT_SSH_HOST = "ad.minieye.tech"
DEFAULT_TARGET_PORT = 22
DEFAULT_KEYFILE = "~/.ssh/id_ed25519"
CONFIG_PATH = Path.home() / ".sshc_config"
HTTP_TIMEOUT = 15.0
VEHICLE_PAGE_SIZE = 20
COMPLETION_PAGE_SIZE = 50
PORT_WAIT_SECONDS = 10.0
PORT_INITIAL_DELAY_SECONDS = 5.0
PORT_POLL_INTERVAL = 2.0
PORT_CONNECT_TIMEOUT_SECONDS = 2.0
DEFAULT_SSH_OPTS = [
    "-o",
    "StrictHostKeyChecking=no",
    "-o",
    "UserKnownHostsFile=/dev/null",
    "-o",
    "ServerAliveInterval=30",
    "-o",
    "ServerAliveCountMax=3",
]


# ── ANSI colour helpers ──────────────────────────────────────────────
_RESET = "\033[0m"
_BOLD = "\033[1m"
_RED = "\033[31m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_BLUE = "\033[34m"
_CYAN = "\033[36m"

_USE_COLOR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def _maybe(text: str, code: str) -> str:
    return f"{code}{text}{_RESET}" if _USE_COLOR else text


def bold(text: str) -> str:
    return _maybe(text, _BOLD)


def green(text: str) -> str:
    return _maybe(text, _GREEN)


def red(text: str) -> str:
    return _maybe(text, _RED)


def yellow(text: str) -> str:
    return _maybe(text, _YELLOW)


def cyan(text: str) -> str:
    return _maybe(text, _CYAN)


def blue(text: str) -> str:
    return _maybe(text, _BLUE)


def _colour_status(value: str | None) -> str:
    if not value:
        return "-"
    v = value.strip().lower()
    if v == "active":
        return green(value)
    if v in ("inactive", "fail", "failed"):
        return red(value)
    if v == "pending":
        return yellow(value)
    return value


def _colour_env(name: str) -> str:
    if name == "prod":
        return green(name)
    if name == "test":
        return blue(name)
    return name


# ────────────────────────────────────────────────────────────────────


class SshcError(RuntimeError):
    """A user-facing error."""


@dataclass(frozen=True)
class HttpResult:
    status: int
    text: str
    data: Any
    url: str
    headers: dict[str, str]


@dataclass(frozen=True)
class Settings:
    prod_username: str
    prod_password_md5: str
    test_username: str
    test_password_md5: str
    keyfile: Path


@dataclass(frozen=True)
class Environment:
    name: str
    base_url: str
    display_url: str
    ssh_host: str


ENVIRONMENTS = [
    Environment("prod", PROD_BASE_URL, PROD_BASE_URL, DEFAULT_SSH_HOST),
    Environment("test", TEST_BASE_URL, TEST_DISPLAY_URL, DEFAULT_SSH_HOST),
]


@dataclass(frozen=True)
class VehicleLookup:
    env: Environment
    client: HttpClient
    vehicle: dict[str, Any]
    device_id: str
    c4_online: bool
    mapping: PortMapping | None


@dataclass(frozen=True)
class PortMapping:
    device_port: int | None
    server_ip: str | None
    server_port: int | None
    protocol: str | None
    status: str | None
    frpc_connected: bool | None

    @property
    def needs_recreate(self) -> bool:
        return (self.status or "").strip().lower() in {"inactive", "fail", "failed"}

    @property
    def is_ready(self) -> bool:
        return (
            (self.status or "").strip().lower() == "active"
            and self.frpc_connected is True
            and self.server_port is not None
        )


class HttpClient:
    def __init__(self, base_url: str, timeout: float, *, debug: bool = False) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.debug = debug
        self.token: str | None = None
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor()
        )

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        raise_for_status: bool = True,
    ) -> HttpResult:
        url = self._build_url(path, params)
        body = None
        headers = self._headers(method, json_body is not None)
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if json_body is not None:
            body = json.dumps(
                json_body,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")

        request = urllib.request.Request(
            url,
            data=body,
            headers=headers,
            method=method.upper(),
        )
        self._debug_request(method, url, headers, json_body)
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                result = self._read_response(response, url)
                self._debug_response(result)
                return result
        except urllib.error.HTTPError as exc:
            result = self._read_response(exc, url)
            self._debug_response(result)
            if raise_for_status:
                raise SshcError(
                    f"HTTP {method.upper()} {url} failed: "
                    f"{result.status} {result.text[:300]}"
                ) from exc
            return result
        except urllib.error.URLError as exc:
            raise SshcError(f"HTTP {method.upper()} {url} failed: {exc}") from exc

    def _headers(self, method: str, has_json_body: bool) -> dict[str, str]:
        headers = {
            "Accept": "application/json, text/plain, */*",
            "x-xz-client": "XZ_OP_WEB",
        }
        if has_json_body:
            headers["Content-Type"] = "application/json"
        return headers

    def _debug_request(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        json_body: Any,
    ) -> None:
        if not self.debug:
            return
        print(f"[debug] HTTP request: {method.upper()} {url}", file=sys.stderr)
        print_json("request headers", headers, file=sys.stderr)
        if json_body is not None:
            print_json("request json", json_body, file=sys.stderr)

    def _debug_response(self, result: HttpResult) -> None:
        if not self.debug:
            return
        response_headers = {
            key: value
            for key, value in result.headers.items()
            if key.lower() in {"content-type", "date", "server", "x-request-id"}
        }
        print(
            f"[debug] HTTP response: {result.status} {result.url}",
            file=sys.stderr,
        )
        if response_headers:
            print_json("response headers", response_headers, file=sys.stderr)
        if result.data is not None:
            print_json("response json", result.data, file=sys.stderr)
            return
        if result.text:
            print(f"response text: {result.text[:1000]}", file=sys.stderr)

    def _build_url(self, path: str, params: dict[str, Any] | None) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            url = path
        else:
            url = f"{self.base_url}/{path.lstrip('/')}"
        clean_params = {
            key: value
            for key, value in (params or {}).items()
            if value is not None
        }
        if clean_params:
            separator = "&" if urllib.parse.urlsplit(url).query else "?"
            url = f"{url}{separator}{urllib.parse.urlencode(clean_params)}"
        return url

    @staticmethod
    def _read_response(response: Any, url: str) -> HttpResult:
        raw = response.read()
        text = raw.decode("utf-8", errors="replace")
        try:
            data = json.loads(text) if text else None
        except json.JSONDecodeError:
            data = None
        return HttpResult(
            status=getattr(response, "status", response.getcode()),
            text=text,
            data=data,
            url=url,
            headers=dict(response.headers.items()),
        )


def main(argv: list[str] | None = None) -> int:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    if raw_args and raw_args[0] in {"config", "cfg"}:
        config_parser = build_config_parser()
        config_args = config_parser.parse_args(raw_args[1:])
        try:
            configure(config_args)
            return 0
        except SshcError as exc:
            print(f"{yellow('[WARNING]')} {exc}", file=sys.stderr)
            return 1
        except KeyboardInterrupt:
            print(f"\n{yellow('[WARNING]')} interrupted", file=sys.stderr)
            return 130

    parser = build_parser()
    args = parser.parse_args(raw_args)

    try:
        settings = load_settings()
        if args.complete_vehicles is not None:
            complete_vehicles(args.complete_vehicles, settings)
        elif args.action in ("add", "a"):
            if args.port is None:
                parser.error("add requires a port number (1-65535)")
            cmd_add(args.vehicle, args.port, settings, debug=args.debug)
        else:
            if not args.vehicle:
                parser.error("the following arguments are required: vehicle")
            return run(args, settings)
        return 0
    except SshcError as exc:
        print(f"{yellow('[WARNING]')} {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print(f"\n{yellow('[WARNING]')} interrupted", file=sys.stderr)
        return 130


def parse_tcp_port(value: str) -> int:
    port = int(value)
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be 1-65535")
    return port


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sshc",
        usage=(
            "sshc [-h] [-v] vehicle\n"
            "       sshc [-h] vehicle add <port>\n"
            "       sshc config [-h] [--prod-username USERNAME] "
            "[--prod-password PASSWORD] [--test-username USERNAME] "
            "[--test-password PASSWORD] [-k KEYFILE]"
        ),
        description="Login to XiaoZhu, prepare the vehicle SSH mapping, copy your key, and SSH in.",
    )
    parser.add_argument("vehicle", nargs="?", help="vehicle name, for example xzt500021")
    parser.add_argument("action", nargs="?", default=None, help=argparse.SUPPRESS)
    parser.add_argument("port", nargs="?", type=parse_tcp_port, default=None, help=argparse.SUPPRESS)
    parser.add_argument(
        "-v",
        "--versions",
        action="store_true",
        help="show C4 status, versions, and existing port mappings, then exit",
    )
    parser.add_argument("--debug", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--complete-vehicles", help=argparse.SUPPRESS)
    return parser


def build_config_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sshc config",
        description=f"View or update {CONFIG_PATH}.",
    )
    parser.add_argument("-u", "--username", help="prod XiaoZhu username")
    parser.add_argument(
        "-p",
        "--password",
        help="prod XiaoZhu password; sshc stores its MD5 value",
    )
    parser.add_argument("--prod-username", help="prod XiaoZhu username")
    parser.add_argument(
        "--prod-password",
        help="prod XiaoZhu password; sshc stores its MD5 value",
    )
    parser.add_argument("--test-username", help="test XiaoZhu username")
    parser.add_argument(
        "--test-password",
        help="test XiaoZhu password; sshc stores its MD5 value",
    )
    parser.add_argument(
        "-k",
        "--keyfile",
        help=f"private key path, default: {DEFAULT_KEYFILE}",
    )
    return parser


def load_settings() -> Settings:
    config = read_config()
    return Settings(
        prod_username=str(config["prod_username"]).strip(),
        prod_password_md5=str(config["prod_password_md5"]).strip(),
        test_username=str(config["test_username"]).strip(),
        test_password_md5=str(config["test_password_md5"]).strip(),
        keyfile=Path(str(config["keyfile"])).expanduser(),
    )


def configure(args: argparse.Namespace) -> None:
    config = read_config()
    changed = False

    prod_username = args.prod_username
    prod_password = args.prod_password
    if args.username is not None:
        prod_username = args.username
    if args.password is not None:
        prod_password = args.password

    if prod_username is not None:
        config["prod_username"] = prod_username.strip()
        changed = True
    if prod_password is not None:
        config["prod_password_md5"] = md5_password(prod_password)
        changed = True
    if args.test_username is not None:
        config["test_username"] = args.test_username.strip()
        changed = True
    if args.test_password is not None:
        config["test_password_md5"] = md5_password(args.test_password)
        changed = True
    if args.keyfile is not None:
        config["keyfile"] = args.keyfile.strip()
        changed = True

    if changed:
        write_config(config)
        print(f"updated config: {CONFIG_PATH}")

    print_config(config)


def read_config() -> dict[str, str]:
    if not CONFIG_PATH.exists():
        config = default_config()
        write_config(config)
        return config

    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SshcError(f"invalid config json: {CONFIG_PATH}") from exc
    if not isinstance(data, dict):
        raise SshcError(f"config json must be an object: {CONFIG_PATH}")

    config = default_config()
    for key in config:
        if key in data:
            config[key] = str(data[key])
    if "username" in data and not config["prod_username"]:
        config["prod_username"] = str(data["username"])
    if "password_md5" in data and not config["prod_password_md5"]:
        config["prod_password_md5"] = str(data["password_md5"])
    return config


def write_config(config: dict[str, str]) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    try:
        CONFIG_PATH.chmod(0o600)
    except OSError:
        pass


def default_config() -> dict[str, str]:
    return {
        "prod_username": "",
        "prod_password_md5": "",
        "test_username": "",
        "test_password_md5": "",
        "keyfile": DEFAULT_KEYFILE,
    }


def print_config(config: dict[str, str]) -> None:
    print(f"config: {CONFIG_PATH}")
    print(f"prod_username: {config['prod_username'] or '-'}")
    print(f"prod_password_md5: {config['prod_password_md5'] or '-'}")
    print(f"test_username: {config['test_username'] or '-'}")
    print(f"test_password_md5: {config['test_password_md5'] or '-'}")
    print(f"keyfile: {config['keyfile'] or '-'}")


def md5_password(password: str) -> str:
    return hashlib.md5(password.encode("utf-8")).hexdigest()


def has_any_environment_config(settings: Settings) -> bool:
    return bool(
        (settings.prod_username and settings.prod_password_md5)
        or (settings.test_username and settings.test_password_md5)
    )


def environment_credentials(
    settings: Settings,
    env: Environment,
) -> tuple[str, str]:
    if env.name == "prod":
        return settings.prod_username, settings.prod_password_md5
    if env.name == "test":
        return settings.test_username, settings.test_password_md5
    return "", ""


def run(args: argparse.Namespace, settings: Settings) -> int:
    if not has_any_environment_config(settings):
        raise SshcError(
            'missing XiaoZhu config; run: sshc config --prod-username "username" '
            '--prod-password "password"'
        )

    print("[INFO] 登录并查询车辆状态...", flush=True)
    lookup = resolve_vehicle_lookup(
        args.vehicle,
        settings,
        debug=args.debug,
        require_online=not args.versions,
    )
    client = lookup.client
    vehicle = lookup.vehicle
    if args.debug:
        print_json("vehicle", vehicle)

    device_id = lookup.device_id
    if args.versions:
        show_vehicle_info(client, args.vehicle, vehicle, device_id)
        if not lookup.c4_online:
            print(f"{yellow('[WARNING]')} {args.vehicle} c4 is offline")
        return 0

    if not lookup.c4_online:
        raise SshcError(f"{args.vehicle} c4 is offline")

    print(f"[INFO] 检查 {DEFAULT_TARGET_PORT} 端口映射...", flush=True)
    mapping = ensure_port_mapping(
        client=client,
        device_id=device_id,
        target_port=DEFAULT_TARGET_PORT,
    )
    if mapping is None or mapping.server_port is None:
        raise SshcError("cannot resolve public SSH server port")

    print(
        f"      {DEFAULT_TARGET_PORT} -> {format_host_port(mapping.server_ip or lookup.env.ssh_host, mapping.server_port)} "
        f"(status={_colour_status(mapping.status)}, "
        f"frpc_connected={format_scalar(mapping.frpc_connected)})"
    )

    print("[INFO] 分发本机公钥，按提示输入车端密码...", flush=True)
    ensure_local_key(settings.keyfile)
    copy_ssh_key(
        keyfile=settings.keyfile,
        ssh_user=DEFAULT_SSH_USER,
        ssh_host=mapping.server_ip or lookup.env.ssh_host,
        server_port=mapping.server_port,
        ssh_opts=DEFAULT_SSH_OPTS,
    )

    target = f"{DEFAULT_SSH_USER}@{mapping.server_ip or lookup.env.ssh_host}"
    ssh_command = [
        "ssh",
        *DEFAULT_SSH_OPTS,
        "-i",
        str(settings.keyfile),
        "-p",
        str(mapping.server_port),
        target,
    ]

    print("[INFO] SSH 登录...", flush=True)
    print(green(shell_join(ssh_command)))
    return subprocess.run(ssh_command).returncode


def cmd_add(vehicle_name: str, port: int, settings: Settings, *, debug: bool = False) -> None:
    """sshc <vehicle> add <port> — ensure the device port mapping exists and is active."""
    if not has_any_environment_config(settings):
        raise SshcError(
            'missing XiaoZhu config; run: sshc config --prod-username "username" '
            '--prod-password "password"'
        )

    print("[INFO] 登录并查询车辆状态...", flush=True)
    lookup = resolve_vehicle_lookup(
        vehicle_name,
        settings,
        debug=debug,
        require_online=True,
    )

    if not lookup.c4_online:
        raise SshcError(f"{vehicle_name} c4 is offline")

    print(f"[INFO] 检查 {port} 端口映射...", flush=True)
    mapping = ensure_port_mapping(
        client=lookup.client,
        device_id=lookup.device_id,
        target_port=port,
    )
    if mapping is None or mapping.server_port is None:
        raise SshcError("cannot resolve public server port")

    print(
        f"      {port} -> {format_host_port(mapping.server_ip or lookup.env.ssh_host, mapping.server_port)} "
        f"(status={_colour_status(mapping.status)}, "
        f"frpc_connected={format_scalar(mapping.frpc_connected)})"
    )


def complete_vehicles(prefix: str, settings: Settings) -> None:
    if not has_any_environment_config(settings):
        print(f"{yellow('[WARNING]')} missing XiaoZhu config", file=sys.stderr)
        return

    query = vehicle_completion_query(prefix)
    if not query:
        return

    names: list[str] = []
    for env in ENVIRONMENTS:
        username, password_md5 = environment_credentials(settings, env)
        if not username or not password_md5:
            continue
        client = HttpClient(env.base_url, HTTP_TIMEOUT)
        try:
            token = login(client, DEFAULT_LOGIN_PATH, username, password_md5)
            client.token = token
            names.extend(complete_vehicle_names(client, prefix, query))
        except SshcError as exc:
            print(f"{yellow('[WARNING]')} {_colour_env(env.name)}: {exc}", file=sys.stderr)
            continue

    if not names:
        print(f"{yellow('[WARNING]')} no online vehicle candidates for {prefix}", file=sys.stderr)
        return

    for name in sorted(set(names)):
        print(name)


def resolve_vehicle_lookup(
    vehicle_name: str,
    settings: Settings,
    *,
    debug: bool,
    require_online: bool,
) -> VehicleLookup:
    lookups: list[VehicleLookup] = []
    found_names: list[str] = []

    for env in ENVIRONMENTS:
        username, password_md5 = environment_credentials(settings, env)
        if not username or not password_md5:
            print(f"      {_colour_env(env.name)}: skipped, missing config")
            continue

        client = HttpClient(env.base_url, HTTP_TIMEOUT, debug=debug)
        try:
            token = login(client, DEFAULT_LOGIN_PATH, username, password_md5)
            client.token = token
            vehicle = find_vehicle(client, vehicle_name)
            device_id = extract_device_id(vehicle)
            c4_online = extract_c4_online_or_false(vehicle)
            found_names.append(env.name)
            mapping = None
            if c4_online or not require_online:
                mapping = find_device_port_mapping(
                    list_port_mappings(client, device_id),
                    DEFAULT_TARGET_PORT,
                )
        except SshcError as exc:
            print(f"      {_colour_env(env.name)}: {exc}")
            continue

        print(f"      {_colour_env(env.name)}: c4Online={format_scalar(c4_online)}, 22={format_mapping_summary(mapping)}")
        lookups.append(
            VehicleLookup(
                env=env,
                client=client,
                vehicle=vehicle,
                device_id=device_id,
                c4_online=c4_online,
                mapping=mapping,
            )
        )

    if not lookups:
        if found_names:
            raise SshcError(f"{vehicle_name} c4 is offline")
        raise SshcError(f"vehicle not found: {vehicle_name}")

    if require_online:
        online_lookups = [lookup for lookup in lookups if lookup.c4_online]
        if not online_lookups:
            raise SshcError(f"{vehicle_name} c4 is offline")
        selected = select_vehicle_lookup(online_lookups)
    else:
        selected = select_vehicle_lookup(lookups)

    print(f"      selected: {_colour_env(selected.env.name)} {selected.env.display_url}")
    return selected


def select_vehicle_lookup(lookups: list[VehicleLookup]) -> VehicleLookup:
    prod = find_lookup(lookups, "prod")
    test = find_lookup(lookups, "test")
    if prod and test:
        if not prod.mapping and test.mapping and test.mapping.is_ready:
            return test
        return prod
    return lookups[0]


def find_lookup(
    lookups: list[VehicleLookup],
    env_name: str,
) -> VehicleLookup | None:
    for lookup in lookups:
        if lookup.env.name == env_name:
            return lookup
    return None


def format_mapping_summary(mapping: PortMapping | None) -> str:
    if not mapping:
        return red("missing")
    return (
        f"{_colour_status(mapping.status)}，"
        f"frpc_connected={format_scalar(mapping.frpc_connected)}"
    )


def format_host_port(host: str, port: int | None) -> str:
    if port is None:
        return host
    return f"{host}:{port}"


def login(client: HttpClient, path: str, username: str, password_md5: str) -> str:
    payload = {
        "identityType": "USERNAME",
        "identityValue": username,
        "passwordType": "PASSWORD_MD5",
        "passwordValue": password_md5,
    }
    result = client.request(
        "POST",
        path,
        json_body=payload,
        raise_for_status=False,
    )
    if not (200 <= result.status < 300):
        raise SshcError(
            f"login failed: {result.status} {result.text[:200].strip()}"
        )
    try:
        token = result.data["data"]["token"]["value"]
    except (KeyError, TypeError):
        token = None
    if not token:
        raise SshcError("login succeeded but data.token.value was not found")
    return token


def find_vehicle(client: HttpClient, vehicle_name: str) -> dict[str, Any]:
    result = client.request(
        "GET",
        DEFAULT_VEHICLES_PATH,
        params={"current": 1, "pageSize": VEHICLE_PAGE_SIZE, "name": vehicle_name},
    )
    vehicles = extract_vehicle_list(result.data)
    if not vehicles:
        raise SshcError(f"vehicle not found: {vehicle_name}")

    normalized = vehicle_name.casefold()
    candidates = vehicles
    exact = [item for item in candidates if str(item.get("name", "")).casefold() == normalized]
    if len(exact) == 1:
        return exact[0]

    names = [str(item.get("name", "")) for item in candidates[:10]]
    raise SshcError(
        f"vehicle exact match not found: {vehicle_name}; "
        f"candidates: {', '.join(names)}"
    )


def complete_vehicle_names(
    client: HttpClient,
    prefix: str,
    query: str,
) -> list[str]:
    result = client.request(
        "GET",
        DEFAULT_VEHICLES_PATH,
        params={"current": 1, "pageSize": COMPLETION_PAGE_SIZE, "name": query},
    )
    suffix = vehicle_completion_suffix(prefix)
    names: list[str] = []
    for item in extract_vehicle_list(result.data):
        if not item.get("c4Online"):
            continue
        name = str(item.get("name", ""))
        if suffix and not name.endswith(suffix):
            continue
        if name:
            names.append(name)
    return sorted(set(names))


def vehicle_completion_query(prefix: str) -> str:
    text = prefix.strip()
    if not text:
        return ""
    if text.isdigit():
        return text.zfill(5)
    return text


def vehicle_completion_suffix(prefix: str) -> str | None:
    text = prefix.strip()
    if not text.isdigit():
        return None
    if len(text) < 5:
        return text.zfill(5)
    return text


def extract_device_id(vehicle: dict[str, Any]) -> str:
    device_id = vehicle.get("id")
    if not device_id:
        raise SshcError("vehicle record does not contain id")
    return str(device_id)



def extract_c4_online_or_false(vehicle: dict[str, Any]) -> bool:
    value = vehicle.get("c4Online")
    if value is None:
        return False
    return bool(value)


def show_vehicle_info(
    client: HttpClient,
    vehicle_name: str,
    vehicle: dict[str, Any],
    device_id: str,
) -> None:
    name = vehicle.get("name") or vehicle_name
    print("[INFO] 车辆信息:", flush=True)
    print(f"vehicle: {name}")

    print("versions:")
    versions = vehicle.get("versions") or {}
    if versions:
        for key, value in versions.items():
            print(f"  {key}: {value}")
    else:
        print("  (none)")

    print("port mappings:")
    mappings = list_port_mappings(client, device_id)
    if not mappings:
        print("  (none)")
        return
    for mapping in mappings:
        endpoint = "-"
        if mapping.server_ip and mapping.server_port:
            endpoint = f"{mapping.server_ip}:{mapping.server_port}"
        elif mapping.server_port:
            endpoint = f"{DEFAULT_SSH_HOST}:{mapping.server_port}"
        print(
            "  "
            f"{format_scalar(mapping.device_port)}/{mapping.protocol or '-'} "
            f"-> {endpoint} "
            f"status={_colour_status(mapping.status)} "
            f"frpc_connected={format_scalar(mapping.frpc_connected)}"
        )
        if mapping.device_port == DEFAULT_TARGET_PORT and mapping.server_port:
            ssh_host = mapping.server_ip or DEFAULT_SSH_HOST
            print(
                f"    ssh: {cyan(f'ssh {DEFAULT_SSH_USER}@{ssh_host} -p {mapping.server_port}')}"
            )
        if mapping.device_port in {9000, 8765} and mapping.server_port and (mapping.status or "").strip().lower() == "active":
            ws_host = mapping.server_ip or DEFAULT_SSH_HOST
            print(
                f"    websocket: {cyan(f'ws://{ws_host}:{mapping.server_port}')}"
            )


def ensure_port_mapping(
    *,
    client: HttpClient,
    device_id: str,
    target_port: int,
) -> PortMapping | None:
    mappings = list_port_mappings(client, device_id)
    mapping = find_device_port_mapping(mappings, target_port)

    if mapping and mapping.is_ready and port_is_connectable(mapping):
        return mapping

    if mapping and mapping.needs_recreate:
        print(f"      发现 {_colour_status(mapping.status)} 映射，删除后重建")
        delete_port_mapping(client, device_id, target_port)
        create_port_mapping(client, device_id, target_port)
    elif mapping:
        print(
            f"      端口映射正在初始化 "
            f"(status={_colour_status(mapping.status)}, "
            f"frpc_connected={format_scalar(mapping.frpc_connected)})"
        )
    else:
        print(f"      未发现 {target_port} 端口映射，准备创建")
        create_port_mapping(client, device_id, target_port)

    mapping = wait_for_connectable_mapping(client, device_id, target_port)
    if mapping and mapping.is_ready:
        return mapping
    status = mapping.status if mapping else "missing"
    connected = format_scalar(mapping.frpc_connected) if mapping else "-"
    raise SshcError(
        f"port mapping connection timed out after {PORT_WAIT_SECONDS:.0f}s "
        f"(status={status}, frpc_connected={connected})"
    )


def list_port_mappings(
    client: HttpClient,
    device_id: str,
) -> list[PortMapping]:
    result = client.request(
        "GET",
        DEFAULT_PORT_MAPPINGS_PATH,
        params={"device_id": device_id},
        raise_for_status=False,
    )
    if not (200 <= result.status < 300):
        raise SshcError(f"failed to list port mappings: {result.status} {result.url}")
    return [
        normalize_mapping(item)
        for item in extract_port_mapping_list(result.data)
    ]


def normalize_mapping(item: Any) -> PortMapping:
    return PortMapping(
        device_port=item.get("device_port"),
        server_ip=item.get("server_ip"),
        server_port=item.get("server_port"),
        protocol=item.get("protocol"),
        status=item.get("status"),
        frpc_connected=item.get("frpc_connected"),
    )


def find_device_port_mapping(
    mappings: list[PortMapping],
    target_port: int,
) -> PortMapping | None:
    for mapping in mappings:
        if mapping.device_port == target_port:
            return mapping
    return None


def delete_port_mapping(
    client: HttpClient,
    device_id: str,
    target_port: int,
) -> None:
    payload = {
        "device_id": device_id,
        "device_port": target_port,
    }
    result = client.request(
        "DELETE",
        DEFAULT_PORT_MAPPINGS_PATH,
        json_body=payload,
        raise_for_status=False,
    )
    if not (200 <= result.status < 300):
        raise SshcError(f"failed to delete port mapping: {result.status}")


def create_port_mapping(
    client: HttpClient,
    device_id: str,
    target_port: int,
) -> None:
    payload = {
        "device_port": target_port,
        "protocol": "tcp",
        "device_id": device_id,
    }
    result = client.request("POST", DEFAULT_PORT_MAPPINGS_PATH, json_body=payload, raise_for_status=False)
    if not (200 <= result.status < 300):
        raise SshcError(f"failed to create port mapping: {result.status}")


def wait_for_connectable_mapping(
    client: HttpClient,
    device_id: str,
    target_port: int,
) -> PortMapping | None:
    deadline = time.monotonic() + PORT_WAIT_SECONDS
    recreated = False
    wait_until_next_check(deadline, PORT_INITIAL_DELAY_SECONDS)
    while True:
        mappings = list_port_mappings(client, device_id)
        mapping = find_device_port_mapping(mappings, target_port)
        if mapping and mapping.needs_recreate:
            if recreated:
                return mapping
            print(f"      映射状态为 {_colour_status(mapping.status)}，删除后重建")
            delete_port_mapping(client, device_id, target_port)
            create_port_mapping(client, device_id, target_port)
            recreated = True
            deadline = time.monotonic() + PORT_WAIT_SECONDS
            wait_until_next_check(deadline, PORT_INITIAL_DELAY_SECONDS)
            continue
        elif mapping and mapping.is_ready and port_is_connectable(mapping):
            return mapping
        if time.monotonic() >= deadline:
            return mapping
        time.sleep(PORT_POLL_INTERVAL)


def wait_until_next_check(deadline: float, seconds: float) -> None:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return
    delay = min(seconds, remaining)
    print(f"      等待映射端口初始化 {delay:.0f}s...", flush=True)
    time.sleep(delay)


def port_is_connectable(mapping: PortMapping) -> bool:
    host = mapping.server_ip or DEFAULT_SSH_HOST
    if mapping.server_port is None:
        return False
    try:
        with socket.create_connection(
            (host, mapping.server_port),
            timeout=PORT_CONNECT_TIMEOUT_SECONDS,
        ):
            return True
    except OSError:
        return False


def ensure_local_key(keyfile: Path) -> None:
    private_key = keyfile.expanduser()
    public_key = public_key_path(private_key)
    ssh_dir = private_key.parent
    ssh_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        ssh_dir.chmod(0o700)
    except OSError:
        pass
    if private_key.exists():
        if not public_key.exists():
            write_public_key(private_key, public_key)
        return
    if public_key.exists():
        raise SshcError(f"public key exists but private key was not found: {private_key}")
    command = ["ssh-keygen", "-t", "ed25519", "-f", str(private_key), "-N", ""]
    result = subprocess.run(command)
    if result.returncode != 0:
        raise SshcError("ssh-keygen failed")


def write_public_key(private_key: Path, public_key: Path) -> None:
    result = subprocess.run(
        ["ssh-keygen", "-y", "-f", str(private_key)],
        stdout=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        raise SshcError("ssh-keygen failed to derive public key")
    public_key.write_text(result.stdout, encoding="utf-8")
    try:
        public_key.chmod(0o644)
    except OSError:
        return


def copy_ssh_key(
    *,
    keyfile: Path,
    ssh_user: str,
    ssh_host: str,
    server_port: int,
    ssh_opts: list[str],
) -> None:
    target = f"{ssh_user}@{ssh_host}"
    command = [
        "ssh-copy-id",
        *ssh_opts,
        "-p",
        str(server_port),
        "-i",
        str(public_key_path(keyfile.expanduser())),
        target,
    ]
    result = subprocess.run(command)
    if result.returncode != 0:
        raise SshcError("ssh-copy-id failed")


def public_key_path(private_key: Path) -> Path:
    return Path(f"{private_key}.pub")


def extract_vehicle_list(data: Any) -> list[Any]:
    try:
        items = data["data"]["list"]
    except (KeyError, TypeError):
        items = None
    if items is None:
        raise SshcError("vehicle list response does not contain data.list")
    return items


def extract_port_mapping_list(data: Any) -> list[Any]:
    try:
        body = data["data"]
    except (KeyError, TypeError):
        body = None
    if not isinstance(body, dict) or "mappings" not in body:
        raise SshcError("port mapping list response does not contain data.mappings")
    items = body["mappings"]
    if items is None:
        return []
    return items


def format_scalar(value: Any) -> str:
    if isinstance(value, bool):
        s = str(value).lower()
        return green(s) if value else red(s)
    if value is None:
        return "-"
    return str(value)


def print_json(label: str, data: Any, *, file: Any = None) -> None:
    target = file or sys.stdout
    print(f"{label}:", file=target)
    print(json.dumps(data, ensure_ascii=False, indent=2), file=target)


def shell_join(command: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in command)


if __name__ == "__main__":
    raise SystemExit(main())
