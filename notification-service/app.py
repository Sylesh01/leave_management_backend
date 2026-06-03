import json
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pika
from pika.exceptions import AMQPConnectionError

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from shared.rabbitmq_config import (
    NOTIFICATION_QUEUE,
    declare_audit_queue,
    declare_notification_topology,
    get_audit_queue_name,
    get_connection_params,
    rabbitmq_enabled,
)
from shared.service_config import service_settings
from shared.service_runner import prepare_service_port

from fastapi import FastAPI
from pydantic import BaseModel
import py_eureka_client.eureka_client as eureka
import uvicorn

SETTINGS = service_settings(default_port=8004, app_name="NOTIFICATION-SERVICE")

prepare_service_port(SETTINGS)

app = FastAPI(title="Notification Service")

consumer_thread = None
consumer_stop = threading.Event()


def _publish_audit_event(event: dict) -> None:
    if not rabbitmq_enabled():
        return

    try:
        connection = pika.BlockingConnection(get_connection_params())
        channel = connection.channel()
        declare_audit_queue(channel)
        channel.basic_publish(
            exchange="",
            routing_key=get_audit_queue_name(),
            body=json.dumps(event).encode("utf-8"),
            properties=pika.BasicProperties(
                content_type="application/json",
                delivery_mode=2,
            ),
        )
        connection.close()
    except Exception as exc:
        print(f"RabbitMQ audit publish failed: {exc}")


def _enqueue_notification_log(level: str, payload: dict) -> None:
    if not rabbitmq_enabled():
        return

    event = {
        "level": level,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "service": "NOTIFICATION-SERVICE",
        "payload": payload,
    }
    _publish_audit_event(event)


def _handle_leave_notification(ch, method, _properties, body):
    try:
        event = json.loads(body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        print(f"Invalid notification message: {exc}")
        ch.basic_ack(delivery_tag=method.delivery_tag)
        return

    print("=======================================================")
    print("  LEAVE NOTIFICATION RECEIVED")
    print(f"  Event Type     : {event.get('event_type')}")
    print(f"  Leave ID       : {event.get('leave_id')}")
    print(f"  Employee ID    : {event.get('employee_id')}")
    print(f"  Recipient ID   : {event.get('recipient_employee_id')}")
    print(f"  Message        : {event.get('message')}")
    print(f"  Timestamp      : {event.get('timestamp')}")
    print("=======================================================")

    _enqueue_notification_log(
        "info",
        {
            "source": "rabbitmq",
            "event_type": event.get("event_type"),
            "leave_id": event.get("leave_id"),
            "employee_id": event.get("employee_id"),
            "recipient_employee_id": event.get("recipient_employee_id"),
            "message": event.get("message"),
        },
    )
    ch.basic_ack(delivery_tag=method.delivery_tag)


def _run_notification_consumer() -> None:
    while not consumer_stop.is_set():
        if not rabbitmq_enabled():
            return

        try:
            connection = pika.BlockingConnection(get_connection_params())
            channel = connection.channel()
            declare_notification_topology(channel)
            channel.basic_qos(prefetch_count=1)
            channel.basic_consume(
                queue=NOTIFICATION_QUEUE,
                on_message_callback=_handle_leave_notification,
            )
            print(f"Listening for leave notifications on {NOTIFICATION_QUEUE}")
            while not consumer_stop.is_set():
                connection.process_data_events(time_limit=1)
            connection.close()
        except AMQPConnectionError as exc:
            if consumer_stop.is_set():
                break
            print(f"Notification consumer reconnecting: {exc}")
            time.sleep(5)
        except Exception as exc:
            if consumer_stop.is_set():
                break
            print(f"Notification consumer error: {exc}")
            time.sleep(5)


def _start_notification_consumer() -> None:
    global consumer_thread
    if not rabbitmq_enabled():
        return
    consumer_stop.clear()
    consumer_thread = threading.Thread(
        target=_run_notification_consumer,
        name="notification-consumer",
        daemon=True,
    )
    consumer_thread.start()


class ErrorLogRequest(BaseModel):
    service: str
    message: str
    status_code: int | None = None
    path: str | None = None
    context: dict | None = None


@app.on_event("startup")
async def startup():
    await eureka.init_async(
        eureka_server=SETTINGS["eureka_server"],
        app_name=SETTINGS["app_name"],
        instance_host=SETTINGS["instance_host"],
        instance_port=SETTINGS["instance_port"],
    )
    _start_notification_consumer()
    print(
        f"{SETTINGS['app_name']} registered with Eureka "
        f"at {SETTINGS['instance_host']}:{SETTINGS['instance_port']}"
    )


@app.on_event("shutdown")
def shutdown():
    consumer_stop.set()
    if consumer_thread and consumer_thread.is_alive():
        consumer_thread.join(timeout=5)


@app.get("/")
def root():
    return {
        "service": "NOTIFICATION-SERVICE",
        "status": "UP",
    }


@app.get("/health")
def health():
    return {"status": "UP"}


@app.post("/notify/error")
def log_error(request: ErrorLogRequest):
    parts = [f"ERROR [{request.service}]"]
    if request.status_code is not None:
        parts.append(str(request.status_code))
    if request.path:
        parts.append(request.path)
    parts.append(f": {request.message}")
    if request.context:
        parts.append(f" {request.context}")
    message_text = " ".join(parts)
    print(message_text)
    _enqueue_notification_log(
        "error",
        {
            "service": request.service,
            "message": request.message,
            "status_code": request.status_code,
            "path": request.path,
            "context": request.context,
        },
    )
    return {"status": "logged", "service": request.service}


if __name__ == "__main__":
    prepare_service_port(SETTINGS)
    uvicorn.run(app, host="0.0.0.0", port=SETTINGS["port"])
