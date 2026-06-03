import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

import pika
from pika.exceptions import AMQPConnectionError

from shared.rabbitmq_config import (
    EXCHANGE,
    declare_notification_topology,
    get_connection_params,
    rabbitmq_enabled,
)


@dataclass
class LeaveNotificationEvent:
    event_type: str
    leave_id: int
    employee_id: int
    recipient_employee_id: int
    message: str
    timestamp: str

    @classmethod
    def create(
        cls,
        *,
        event_type: str,
        leave_id: int,
        employee_id: int,
        recipient_employee_id: int,
        message: str,
    ) -> "LeaveNotificationEvent":
        return cls(
            event_type=event_type,
            leave_id=leave_id,
            employee_id=employee_id,
            recipient_employee_id=recipient_employee_id,
            message=message,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )


def publish_leave_notification(
    event: LeaveNotificationEvent,
    routing_key: str,
) -> None:
    if not rabbitmq_enabled():
        print(
            f"Notification for employee {event.recipient_employee_id}: "
            f"{event.message} (RabbitMQ disabled)"
        )
        return

    try:
        connection = pika.BlockingConnection(get_connection_params())
        channel = connection.channel()
        declare_notification_topology(channel)
        channel.basic_publish(
            exchange=EXCHANGE,
            routing_key=routing_key,
            body=json.dumps(asdict(event)).encode("utf-8"),
            properties=pika.BasicProperties(
                content_type="application/json",
                delivery_mode=2,
            ),
        )
        connection.close()
    except AMQPConnectionError as exc:
        print(
            f"Notification for employee {event.recipient_employee_id}: "
            f"{event.message} (RabbitMQ unavailable: {exc})"
        )
    except Exception as exc:
        print(
            f"Notification for employee {event.recipient_employee_id}: "
            f"{event.message} (RabbitMQ publish failed: {exc})"
        )
