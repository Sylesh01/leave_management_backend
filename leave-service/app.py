import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from shared.service_config import service_settings
from shared.notification_client import (
    register_error_logging,
    log_error,
)
from shared.event_publisher import LeaveNotificationEvent, publish_leave_notification
from shared.rabbitmq_config import (
    ROUTING_LEAVE_APPROVED,
    ROUTING_LEAVE_REJECTED,
    ROUTING_LEAVE_SUBMITTED,
)
from shared.eureka_lookup import get_service_url as lookup_service_url
from shared.service_runner import prepare_service_port
from shared.jwt_auth import get_current_user
from shared.authorization import (
    can_apply_leave,
    can_manage_team_requests,
    can_process_leave,
)
from shared.circuit_breaker import resilient_request, CircuitOpenError

from datetime import date, datetime
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
import py_eureka_client.eureka_client as eureka
import uvicorn
import json
import requests

from pydantic import BaseModel, field_validator, model_validator

SETTINGS = service_settings(default_port=8003, app_name="LEAVE-SERVICE")

prepare_service_port(SETTINGS)

BASE_DIR = Path(__file__).parent

VALID_LEAVE_TYPES = ("sick", "casual", "privilege")
BLOCKING_STATUSES = ("PENDING", "APPROVED")


def parse_leave_type(value: str) -> str:
    normalized = value.strip().lower()
    aliases = {
        "earned": "privilege",
        "privileged": "privilege",
        "privilaged": "privilege",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in VALID_LEAVE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"leave_type must be one of: {', '.join(VALID_LEAVE_TYPES)}",
        )
    return normalized


def inclusive_days(start: date, end: date) -> int:
    return (end - start).days + 1


def ranges_overlap(start1: date, end1: date, start2: date, end2: date) -> bool:
    return start1 <= end2 and start2 <= end1


def normalize_leave_balance(balance: dict) -> dict:
    normalized = dict(balance)
    if "earned" in normalized and "privilege" not in normalized:
        normalized["privilege"] = normalized.pop("earned")
    return normalized


class ApplyLeaveRequest(BaseModel):
    leave_type: str
    start_date: date
    end_date: date
    days: int
    reason: str


class RejectLeaveBody(BaseModel):
    rejection_comments: str | None = None


app = FastAPI(title="Leave Service")

register_error_logging(app, "LEAVE-SERVICE", SETTINGS["eureka_server"])

with open(BASE_DIR / "leaves.json", "r") as f:
    LEAVES = json.load(f)


def next_leave_id():
    if not LEAVES:
        return 1
    return max(leave["leave_id"] for leave in LEAVES) + 1


def parse_leave_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def get_blocking_leaves(employee_id: int):
    blocking = []
    for leave in LEAVES:
        if leave.get("employee_id") != employee_id:
            continue
        if leave.get("status") not in BLOCKING_STATUSES:
            continue
        start = parse_leave_date(leave.get("start_date"))
        end = parse_leave_date(leave.get("end_date"))
        if start is None or end is None:
            continue
        blocking.append((leave, start, end))
    return blocking


async def get_employee_service_url():
    return await lookup_service_url(
        SETTINGS["eureka_server"],
        "EMPLOYEE-SERVICE",
    )


def service_request(service_name: str, method: str, url: str, **kwargs):
    try:
        return resilient_request(service_name, method, url, **kwargs)
    except CircuitOpenError:
        raise HTTPException(
            status_code=503,
            detail=f"{service_name} temporarily unavailable",
        )
    except requests.RequestException:
        raise HTTPException(
            status_code=503,
            detail=f"Failed to contact {service_name}",
        )


def find_leave(leave_id: int):
    for leave in LEAVES:
        if leave.get("leave_id") == leave_id:
            return leave
    return None


def enrich_leave_row(leave: dict, name_map: dict) -> dict:
    employee_id = leave.get("employee_id")
    return {
        "leave_id": leave["leave_id"],
        "employee_id": employee_id,
        "employee_name": name_map.get(employee_id, "Unknown"),
        "leave_type": leave["leave_type"],
        "start_date": leave.get("start_date"),
        "end_date": leave.get("end_date"),
        "days": leave["days"],
        "reason": leave.get("reason"),
        "status": leave["status"],
        "rejection_comments": leave.get("rejection_comments"),
    }


def enrich_employee_history_row(leave: dict) -> dict:
    return {
        "leave_id": leave["leave_id"],
        "leave_type": leave["leave_type"],
        "start_date": leave.get("start_date"),
        "end_date": leave.get("end_date"),
        "days": leave["days"],
        "reason": leave.get("reason"),
        "status": leave["status"],
        "rejection_comments": leave.get("rejection_comments"),
        "processed_at": leave.get("processed_at"),
        "processed_by": leave.get("processed_by"),
        "reporting_manager": leave.get("reporting_manager"),
    }


def sort_requests(requests: list) -> list:
    return sorted(requests, key=lambda row: row["leave_id"], reverse=True)


@app.on_event("startup")
async def startup():
    await eureka.init_async(
        eureka_server=SETTINGS["eureka_server"],
        app_name=SETTINGS["app_name"],
        instance_host=SETTINGS["instance_host"],
        instance_port=SETTINGS["instance_port"],
    )
    print(
        f"{SETTINGS['app_name']} registered with Eureka "
        f"at {SETTINGS['instance_host']}:{SETTINGS['instance_port']}"
    )


@app.get("/health")
def health():
    return {"status": "UP"}


@app.post("/leaves/employee/{employee_id}/apply", status_code=201)
async def apply_leave(
    employee_id: int,
    request: ApplyLeaveRequest,
    http_request: Request,
):
    user = get_current_user(http_request)
    if not can_apply_leave(user, employee_id):
        raise HTTPException(
            status_code=403,
            detail="You can only apply leave for your own employee id",
        )

    leave_type = parse_leave_type(request.leave_type)
    if request.start_date > request.end_date:
        raise HTTPException(
            status_code=400,
            detail="start_date cannot be after end_date"
        )

    expected_days = (
        request.end_date - request.start_date
    ).days + 1

    if request.days != expected_days:
        raise HTTPException(
            status_code=400,
            detail=(
                f"days must be {expected_days} for the given date range"
            ),
        )

    if request.days <= 0:
        raise HTTPException(
            status_code=400,
            detail="days must be greater than 0"
        )

    if not request.reason or not request.reason.strip():
        raise HTTPException(
            status_code=400,
            detail="reason cannot be empty"
        )

    employee_service_url = await get_employee_service_url()

    context_response = service_request(
        "EMPLOYEE-SERVICE",
        "get",
        f"{employee_service_url}/employees/{employee_id}/leave-apply-context",
        timeout=5,
    )
    if context_response.status_code == 404:
        raise HTTPException(status_code=404, detail="Employee not found")
    if context_response.status_code != 200:
        raise HTTPException(
            status_code=context_response.status_code,
            detail="Failed to fetch employee leave context",
        )

    context = context_response.json()

    if context.get("manager_id") is None or context.get("reporting_manager") is None:
        raise HTTPException(
            status_code=400,
            detail="No reporting manager assigned for this employee",
        )

    reporting_manager = context["reporting_manager"]
    leave_balance = normalize_leave_balance(context["leave_balance"])
    remaining = leave_balance.get(leave_type, 0)

    if remaining < request.days:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Insufficient {leave_type} leave balance: "
                f"{remaining} remaining, {request.days} requested"
            ),
        )

    for existing_leave, existing_start, existing_end in get_blocking_leaves(
        employee_id
    ):
        if ranges_overlap(
            request.start_date,
            request.end_date,
            existing_start,
            existing_end,
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Leave dates overlap with an existing "
                    f"{existing_leave['status']} leave "
                    f"(id {existing_leave['leave_id']}, "
                    f"{existing_start} to {existing_end})"
                ),
            )

    leave = {
        "leave_id": next_leave_id(),
        "employee_id": employee_id,
        "leave_type": leave_type,
        "start_date": request.start_date.isoformat(),
        "end_date": request.end_date.isoformat(),
        "days": request.days,
        "reason": request.reason,
        "status": "PENDING",
        "reporting_manager": reporting_manager,
        "rejection_comments": None,
        "processed_at": None,
        "processed_by": None,
    }

    LEAVES.append(leave)

    leave_id = leave["leave_id"]
    publish_leave_notification(
        LeaveNotificationEvent.create(
            event_type="leave.submitted",
            leave_id=leave_id,
            employee_id=employee_id,
            recipient_employee_id=employee_id,
            message=(
                f"Leave request {leave_id} submitted "
                f"({request.days} days {leave_type}, "
                f"{request.start_date.isoformat()} to {request.end_date.isoformat()})"
            ),
        ),
        ROUTING_LEAVE_SUBMITTED,
    )
    publish_leave_notification(
        LeaveNotificationEvent.create(
            event_type="leave.submitted",
            leave_id=leave_id,
            employee_id=employee_id,
            recipient_employee_id=reporting_manager["employee_id"],
            message=(
                f"New leave request {leave_id} from employee {employee_id} "
                "pending approval"
            ),
        ),
        ROUTING_LEAVE_SUBMITTED,
    )

    return {
        "message": "Leave submitted",
        "leave": leave,
    }


@app.get("/leaves/employee/{employee_id}/history")
def get_employee_leave_history(employee_id: int, http_request: Request):
    user = get_current_user(http_request)
    if not can_apply_leave(user, employee_id):
        raise HTTPException(
            status_code=403,
            detail="You can only view your own leave application history",
        )

    applications = [
        enrich_employee_history_row(leave)
        for leave in LEAVES
        if leave.get("employee_id") == employee_id
    ]

    return {
        "employee_id": employee_id,
        "applications": sort_requests(applications),
    }


@app.get("/leaves/manager/{manager_id}/team-requests")
async def get_manager_team_requests(manager_id: int,
http_request: Request
):
    user = get_current_user(http_request)
    if not can_manage_team_requests(user, manager_id):
        raise HTTPException(
            status_code=403,
            detail="Not allowed to view team leave requests",
        )
    employee_service_url = await get_employee_service_url()
    reports_response = service_request(
        "EMPLOYEE-SERVICE",
        "get",
        f"{employee_service_url}/employees/manager/{manager_id}/reports",
        timeout=5,
    )
    if reports_response.status_code != 200:
        raise HTTPException(
            status_code=reports_response.status_code,
            detail="Failed to fetch manager reports",
        )

    reports = reports_response.json()
    report_ids = {report["employee_id"] for report in reports}
    name_map = {report["employee_id"]: report["name"] for report in reports}

    request = [
        enrich_leave_row(leave, name_map)
        for leave in LEAVES
        if leave.get("employee_id") in report_ids
    ]

    return {
        "manager_id": manager_id,
        "requests": sort_requests(request),
    }


@app.get("/leaves/all-requests")
async def get_all_requests(
    http_request: Request
):
    user = get_current_user(http_request)
    if user.get("role") != "admin":
        raise HTTPException(
            status_code=403,
            detail="Only admins can view all leave requests",
        )
    employee_service_url = await get_employee_service_url()
    summaries_response = service_request(
        "EMPLOYEE-SERVICE",
        "get",
        f"{employee_service_url}/employees/summaries",
        timeout=5,
    )
    if summaries_response.status_code != 200:
        raise HTTPException(
            status_code=summaries_response.status_code,
            detail="Failed to fetch employee summaries",
        )

    name_map = {
        row["employee_id"]: row["name"]
        for row in summaries_response.json()
    }

    request = [enrich_leave_row(leave, name_map) for leave in LEAVES]

    return {
        "requests": sort_requests(request),
    }


@app.get("/employees/{emp_id}/team-leave-requests")
async def team_leave_requests(emp_id: int, http_request: Request):
    user = get_current_user(http_request)

    if not can_manage_team_requests(user, emp_id):
        raise HTTPException(
            status_code=403,
            detail="Not allowed to view team leave requests",
        )

    if user.get("role") == "admin":
        data = await get_all_requests(http_request)
        return {
            "manager_id": emp_id,
            "requests": data.get("requests", []),
        }

    return await get_manager_team_requests(emp_id, http_request)


@app.get("/leaves/{leave_id}")
def get_leave(leave_id: int):
    leave = find_leave(leave_id)
    if leave is None:
        raise HTTPException(status_code=404, detail="Leave not found")
    return leave


@app.put("/leaves/{leave_id}/approve")
async def approve_leave(leave_id: int, http_request: Request):
    user = get_current_user(http_request)
    leave = find_leave(leave_id)
    if leave is None:
        raise HTTPException(status_code=404, detail="Leave not found")

    if not await can_process_leave(user, leave, SETTINGS["eureka_server"]):
        raise HTTPException(
            status_code=403,
            detail="Not allowed to approve this leave request",
        )

    if leave["status"] != "PENDING":
        raise HTTPException(status_code=400, detail="Leave already processed")

    employee_service_url = await get_employee_service_url()
    deduct_response = service_request(
        "EMPLOYEE-SERVICE",
        "put",
        f"{employee_service_url}/employees/{leave['employee_id']}/leave-balance",
        json={
            "leave_type": leave["leave_type"],
            "days": leave["days"],
        },
        timeout=5,
    )

    if deduct_response.status_code != 200:
        try:
            detail = deduct_response.json().get("detail", "Balance update failed")
        except Exception:
            detail = "Balance update failed"
        raise HTTPException(status_code=400, detail=detail)

    leave["status"] = "APPROVED"
    leave["processed_at"] = datetime.utcnow().isoformat()
    leave["processed_by"] = user["employee_id"]
    leave["rejection_comments"] = None

    publish_leave_notification(
        LeaveNotificationEvent.create(
            event_type="leave.approved",
            leave_id=leave_id,
            employee_id=leave["employee_id"],
            recipient_employee_id=leave["employee_id"],
            message=f"Leave request {leave_id} approved",
        ),
        ROUTING_LEAVE_APPROVED,
    )

    return {
        "message": "Leave approved",
        "leave": leave,
    }


@app.put("/leaves/{leave_id}/reject")
async def reject_leave(
    leave_id: int,
    http_request: Request,
    body: RejectLeaveBody | None = None,
):
    user = get_current_user(http_request)
    leave = find_leave(leave_id)
    if leave is None:
        raise HTTPException(status_code=404, detail="Leave not found")

    if not await can_process_leave(user, leave, SETTINGS["eureka_server"]):
        raise HTTPException(
            status_code=403,
            detail="Not allowed to reject this leave request",
        )

    if leave["status"] != "PENDING":
        raise HTTPException(status_code=400, detail="Leave already processed")

    comments = body.rejection_comments if body else None
    if comments is not None:
        comments = comments.strip() or None

    leave["status"] = "REJECTED"
    leave["rejection_comments"] = comments
    leave["processed_at"] = datetime.utcnow().isoformat()
    leave["processed_by"] = user["employee_id"]

    message = f"Leave request {leave_id} rejected"
    if comments:
        message += f": {comments}"

    publish_leave_notification(
        LeaveNotificationEvent.create(
            event_type="leave.rejected",
            leave_id=leave_id,
            employee_id=leave["employee_id"],
            recipient_employee_id=leave["employee_id"],
            message=message,
        ),
        ROUTING_LEAVE_REJECTED,
    )

    return {
        "message": "Leave rejected",
        "leave": leave,
    }


@app.exception_handler(ValueError)
async def value_error_handler(request, exc):
    await log_error(
        SETTINGS["eureka_server"],
        "LEAVE-SERVICE",
        str(exc),
        400,
        request.url.path,
    )
    return JSONResponse(status_code=400, content={"detail": str(exc)})


if __name__ == "__main__":
    prepare_service_port(SETTINGS)
    uvicorn.run(app, host="0.0.0.0", port=SETTINGS["port"])
