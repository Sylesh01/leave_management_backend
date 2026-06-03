import os

import pika

EXCHANGE = "leave.exchange"
NOTIFICATION_QUEUE = "notification.queue"
AUDIT_QUEUE = "leave-logs"

ROUTING_LEAVE_SUBMITTED = "leave.submitted"
ROUTING_LEAVE_APPROVED = "leave.approved"
ROUTING_LEAVE_REJECTED = "leave.rejected"

NOTIFICATION_ROUTING_KEYS = (
    ROUTING_LEAVE_SUBMITTED,
    ROUTING_LEAVE_APPROVED,
    ROUTING_LEAVE_REJECTED,
)


def rabbitmq_enabled() -> bool:
    return os.environ.get("RABBITMQ_ENABLED", "true").lower() != "false"


def get_connection_params() -> pika.ConnectionParameters:
    return pika.ConnectionParameters(
        host=os.environ.get("RABBITMQ_HOST", "rabbitmq"),
        port=int(os.environ.get("RABBITMQ_PORT", "5672")),
        credentials=pika.PlainCredentials(
            os.environ.get("RABBITMQ_USERNAME", "guest"),
            os.environ.get("RABBITMQ_PASSWORD", "guest"),
        ),
        heartbeat=60,
        blocked_connection_timeout=30,
    )


def get_audit_queue_name() -> str:
    return os.environ.get("RABBITMQ_QUEUE", AUDIT_QUEUE)


def declare_notification_topology(channel: pika.channel.Channel) -> None:
    channel.exchange_declare(
        exchange=EXCHANGE,
        exchange_type="topic",
        durable=True,
    )
    channel.queue_declare(queue=NOTIFICATION_QUEUE, durable=True)
    for routing_key in NOTIFICATION_ROUTING_KEYS:
        channel.queue_bind(
            exchange=EXCHANGE,
            queue=NOTIFICATION_QUEUE,
            routing_key=routing_key,
        )


def declare_audit_queue(channel: pika.channel.Channel) -> None:
    channel.queue_declare(queue=get_audit_queue_name(), durable=True)
