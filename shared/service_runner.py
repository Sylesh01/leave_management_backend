import os
import socket
from pathlib import Path

PORT_FILE = Path("/tmp/service.port")


def resolve_listen_port(configured_port: int) -> int:
    if configured_port != 0:
        return configured_port

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("", 0))
        return sock.getsockname()[1]


def resolve_instance_host(fallback: str) -> str:
    if os.environ.get("EUREKA_INSTANCE_HOST"):
        return os.environ["EUREKA_INSTANCE_HOST"]

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        pass

    return os.environ.get("HOSTNAME") or fallback


def write_port_file(port: int) -> None:
    PORT_FILE.write_text(str(port))


def read_port_file() -> int:
    return int(PORT_FILE.read_text().strip())


def prepare_service_port(settings: dict) -> None:
    port = resolve_listen_port(settings["port"])
    settings["port"] = port
    settings["instance_port"] = port
    settings["instance_host"] = resolve_instance_host(
        settings.get("service_host", settings["instance_host"])
    )
    write_port_file(port)
