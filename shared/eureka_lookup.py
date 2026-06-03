import py_eureka_client.eureka_client as eureka
from fastapi import HTTPException
from threading import Lock

_counters: dict[str, int] = {}
_lock = Lock()


def _instance_port(instance) -> int:
    try:
        return instance.port.port
    except AttributeError:
        return instance.port


def _pick_instance(service_name: str, instances: list):
    with _lock:
        counter = _counters.get(service_name, 0)
        instance = instances[counter % len(instances)]
        _counters[service_name] = counter + 1
    return instance


async def get_service_url(
    eureka_server: str,
    service_name: str,
    *,
    required: bool = True,
) -> str | None:
    app_obj = await eureka.get_application(eureka_server, service_name)

    if app_obj is None or not app_obj.up_instances:
        if not required:
            return None
        if app_obj is None:
            raise HTTPException(
                status_code=503,
                detail=f"{service_name} not found in Eureka",
            )
        raise HTTPException(
            status_code=503,
            detail=f"No active instances for {service_name}",
        )

    instance = _pick_instance(service_name, app_obj.up_instances)
    port = _instance_port(instance)
    return f"http://{instance.hostName}:{port}"
