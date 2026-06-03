import os


def service_settings(default_port: int, app_name: str) -> dict:
    port = int(os.environ.get("PORT", os.environ.get("SERVICE_PORT", default_port)))
    service_host = os.environ.get("SERVICE_HOST", "localhost")

    return {
        "app_name": app_name,
        "service_host": service_host,
        "instance_host": service_host,
        "instance_port": port,
        "eureka_server": os.environ.get(
            "EUREKA_SERVER",
            "http://localhost:8761/eureka",
        ),
        "port": port,
    }
