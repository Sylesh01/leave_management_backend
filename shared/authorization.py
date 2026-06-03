from fastapi import HTTPException
from requests import RequestException
from shared.circuit_breaker import resilient_request, CircuitOpenError
from shared.eureka_lookup import get_service_url


async def can_view_employee(
    user: dict,
    target_employee_id: int,
    eureka_server: str,
) -> bool:
    caller_id = user.get("employee_id")
    role = user.get("role")

    if role == "admin":
        return True

    if caller_id == target_employee_id:
        return True

    if role == "manager":
        employee_service_url = await get_service_url(
            eureka_server,
            "EMPLOYEE-SERVICE",
        )
        try:
            response = resilient_request(
                "EMPLOYEE-SERVICE",
                "get",
                f"{employee_service_url}/employees/manager/{caller_id}/reports",
                timeout=5,
            )
        except (CircuitOpenError, RequestException):
            raise HTTPException(
                status_code=503,
                detail="Employee service unavailable",
            )
        if response.status_code == 200:
            return any(
                report["employee_id"] == target_employee_id
                for report in response.json()
            )

    return False


def can_apply_leave(user: dict, emp_id: int) -> bool:
    return user.get("employee_id") == emp_id


def can_manage_team_requests(user: dict, emp_id: int) -> bool:
    role = user.get("role")
    if role == "admin":
        return True
    if role == "manager" and user.get("employee_id") == emp_id:
        return True
    return False


async def can_process_leave(
    user: dict,
    leave: dict,
    eureka_server: str,
) -> bool:
    if user.get("role") == "admin":
        return True

    if user.get("role") != "manager":
        return False

    caller_id = user.get("employee_id")
    if caller_id is None:
        return False

    employee_service_url = await get_service_url(
        eureka_server,
        "EMPLOYEE-SERVICE",
    )
    try:
        response = resilient_request(
            "EMPLOYEE-SERVICE",
            "get",
            f"{employee_service_url}/employees/manager/{caller_id}/reports",
            timeout=5,
        )
    except (CircuitOpenError, RequestException):
        raise HTTPException(
            status_code=503,
            detail="Employee service unavailable",
        )
    if response.status_code != 200:
        return False

    report_ids = {report["employee_id"] for report in response.json()}
    return leave.get("employee_id") in report_ids
