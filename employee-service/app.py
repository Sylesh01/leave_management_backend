import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from shared.service_config import service_settings
from shared.notification_client import register_error_logging
from shared.service_runner import prepare_service_port
from shared.jwt_auth import get_current_user

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
import py_eureka_client.eureka_client as eureka
import json
import uvicorn

SETTINGS = service_settings(default_port=8002, app_name="EMPLOYEE-SERVICE")

prepare_service_port(SETTINGS)

BASE_DIR = Path(__file__).parent
with open(BASE_DIR / "employees.json", "r") as f:
    EMPLOYEES = json.load(f)

app = FastAPI(title="Employee Service")

register_error_logging(app, "EMPLOYEE-SERVICE", SETTINGS["eureka_server"])

LEAVE_QUOTAS = {
    "sick": 10,
    "casual": 12,
    "privilege": 15,
}

DEFAULT_LEAVE_BALANCE = dict(LEAVE_QUOTAS)
VALID_LEAVE_TYPES = tuple(LEAVE_QUOTAS.keys())


class LeaveDeduction(BaseModel):
    leave_type: str
    days: int


class EmployeeCreate(BaseModel):
    username: str
    password: str
    name: str
    role: str
    department: str
    manager_id: int | None = None


def get_next_employee_id() -> int:
    return max((emp["id"] for emp in EMPLOYEES), default=100) + 1


def find_employee_by_username(username: str):
    return next((emp for emp in EMPLOYEES if emp["username"] == username), None)


def normalize_leave_balance(balance):
    normalized = dict(balance)
    if "earned" in normalized and "privilege" not in normalized:
        normalized["privilege"] = normalized.pop("earned")
    return {
        leave_type: normalized.get(leave_type, 0)
        for leave_type in LEAVE_QUOTAS
    }


def build_leave_details(emp):
    balance = normalize_leave_balance(emp.get("leave_balance", {}))
    details = {}
    total_used = 0
    total_remaining = 0

    for leave_type, allocated in LEAVE_QUOTAS.items():
        remaining = balance.get(leave_type, 0)
        used = allocated - remaining
        details[leave_type] = {
            "allocated": allocated,
            "used": used,
            "remaining": remaining,
        }
        total_used += used
        total_remaining += remaining

    details["total"] = {
        "allocated": sum(LEAVE_QUOTAS.values()),
        "used": total_used,
        "remaining": total_remaining,
    }
    return details


def leave_details_entry(emp, subject_employee_id):
    return {
        "employee_id": emp["id"],
        "name": emp["name"],
        "is_self": emp["id"] == subject_employee_id,
        "leaves": build_leave_details(emp),
    }


def find_employee(employee_id):
    for emp in EMPLOYEES:
        if emp["id"] == employee_id:
            return emp
    return None


def build_reporting_manager(employee):
    manager_id = employee.get("manager_id")
    if manager_id is None:
        return None

    manager = find_employee(manager_id)
    if manager is None:
        return None

    return {
        "employee_id": manager["id"],
        "name": manager["name"],
        "username": manager["username"],
    }


def build_leave_details_response(employee_id):
    emp = find_employee(employee_id)
    if emp is None:
        raise HTTPException(status_code=404, detail="Employee not found")

    if emp["role"] == "manager":
        employees = [leave_details_entry(emp, employee_id)]
        for report in EMPLOYEES:
            if report.get("manager_id") == employee_id:
                employees.append(leave_details_entry(report, employee_id))
    else:
        employees = [leave_details_entry(emp, employee_id)]

    return {
        "employee_id": employee_id,
        "role": emp["role"],
        "employees": employees,
    }


def can_view_employee_local(user: dict, target_employee_id: int) -> bool:
    caller_id = user.get("employee_id")
    role = user.get("role")

    if role == "admin":
        return True

    if caller_id == target_employee_id:
        return True

    if role == "manager":
        return any(
            emp["id"] == target_employee_id
            and emp.get("manager_id") == caller_id
            for emp in EMPLOYEES
        )

    return False


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


@app.get("/employee/username/{username}")
def get_employee_by_username(username: str):
    emp = next((e for e in EMPLOYEES if e["username"] == username), None)
    if emp is None:
        raise HTTPException(status_code=404, detail="User not found")
    return emp


@app.post("/employees", status_code=201)
def create_employee(request: EmployeeCreate, http_request: Request):
    user = get_current_user(http_request)
    if user.get("role") != "admin":
        raise HTTPException(
            status_code=403,
            detail="Only admins can create employees",
        )

    if find_employee_by_username(request.username) is not None:
        raise HTTPException(status_code=400, detail="Username already exists")

    if request.role not in {"employee", "manager", "admin"}:
        raise HTTPException(
            status_code=400,
            detail="role must be one of: employee, manager, admin",
        )

    employee = {
        "id": get_next_employee_id(),
        "username": request.username,
        "password": request.password,
        "name": request.name,
        "role": request.role,
        "department": request.department,
        "manager_id": request.manager_id,
        "leave_balance": dict(DEFAULT_LEAVE_BALANCE),
    }
    EMPLOYEES.append(employee)
    response = {k: v for k, v in employee.items() if k != "password"}
    return response


@app.get("/employees/summaries")
def get_employee_summaries():
    return [
        {"employee_id": emp["id"], "name": emp["name"]}
        for emp in EMPLOYEES
    ]


@app.get("/employees/manager/{manager_id}/reports")
def get_manager_reports(manager_id: int):
    return [
        {"employee_id": emp["id"], "name": emp["name"]}
        for emp in EMPLOYEES
        if emp.get("manager_id") == manager_id
    ]


@app.get("/employees/{employee_id}/leave-details")
async def get_employee_leave_details(employee_id: int, request: Request):
    user = get_current_user(request)
    if not can_view_employee_local(user, employee_id):
        raise HTTPException(
            status_code=403,
            detail="Not allowed to view this employee's leave details",
        )
    return build_leave_details_response(employee_id)


@app.get("/employees/{employee_id}/leave-apply-context")
def get_leave_apply_context(employee_id: int):
    emp = find_employee(employee_id)
    if emp is None:
        raise HTTPException(status_code=404, detail="Employee not found")

    return {
        "employee_id": employee_id,
        "manager_id": emp.get("manager_id"),
        "leave_balance": normalize_leave_balance(emp["leave_balance"]),
        "reporting_manager": build_reporting_manager(emp),
    }


@app.put("/employees/{employee_id}/leave-balance")
def update_leave_balance(employee_id: int, request: LeaveDeduction):
    if request.leave_type not in VALID_LEAVE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"leave_type must be one of: {', '.join(VALID_LEAVE_TYPES)}",
        )

    emp = find_employee(employee_id)
    if emp is None:
        raise HTTPException(status_code=404, detail="Employee not found")

    balance = normalize_leave_balance(emp["leave_balance"])
    emp["leave_balance"] = balance

    if balance[request.leave_type] < request.days:
        raise HTTPException(
            status_code=400,
            detail="Insufficient leave balance",
        )

    balance[request.leave_type] -= request.days

    return {
        "message": "Balance updated",
        "employee_id": employee_id,
        "leave_balance": balance,
    }


if __name__ == "__main__":
    prepare_service_port(SETTINGS)
    uvicorn.run(app, host="0.0.0.0", port=SETTINGS["port"])
